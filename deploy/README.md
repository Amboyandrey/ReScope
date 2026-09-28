# Kubernetes deployment (AWS, k3s, Argo CD)

A second production path beside `infra/docker-compose.prod.yml`: Terraform provisions one AWS node
running k3s, GitHub Actions builds, scans and publishes images, and Argo CD reconciles two
environments (`rescope-staging`, `rescope-prod`) from this repo.

```
push to main ──► CI (tests) ──► CD: build ─► Trivy gate ─► GHCR ─► bump staging tag in git
                                                                          │
                          Argo CD (in cluster) ◄── watches deploy/ ◄──────┘
                          ├─ rescope-staging   auto-sync
                          └─ rescope-prod      manual sync, after a promotion PR is merged
```

| Path | What it holds |
|---|---|
| `terraform/` | VPC, security group (no SSH; 6443 from admin CIDRs only), spot EC2 node with k3s, Elastic IP, S3 backup bucket, least-privilege instance role, monthly budget alert |
| `helm/rescope/` | The app: Postgres + pgvector, Redis, TEI, api, worker, scraper, web, migration Job, Ingress + wildcard cert, NetworkPolicies, backup CronJob, SLO rules and Grafana dashboard |
| `argocd/` | App of apps: cert-manager, sealed-secrets, kube-prometheus-stack, `platform/`, and the two ReScope environments |
| `environments/<env>/` | Per-environment domain, image tags (written by CI) and sealed secrets |
| `platform/` | Let's Encrypt DNS-01 ClusterIssuer, Traefik metrics scraping, platform sealed secrets |
| `scripts/` | `bootstrap.sh`, `seal-secrets.sh`, `restore-drill.sh` |

Rough cost while running: t3.xlarge spot (~$35), 60 GB gp3 (~$5), Elastic IP (~$4). Run
`terraform destroy` when not demoing.

## First-time setup

Tools: `aws`, `terraform` >= 1.10, `kubectl`, `helm`, `kubeseal`, `yq`.

1. **State bucket** (once per account):
   ```bash
   aws s3api create-bucket --bucket rescope-tfstate-<account-id> --region ap-southeast-1 \
     --create-bucket-configuration LocationConstraint=ap-southeast-1
   aws s3api put-bucket-versioning --bucket rescope-tfstate-<account-id> --versioning-configuration Status=Enabled
   ```
2. **Provision**:
   ```bash
   cd deploy/terraform
   cp backend.hcl.example backend.hcl && cp terraform.tfvars.example terraform.tfvars   # edit both
   terraform init -backend-config=backend.hcl
   terraform apply
   ```
   Activate the `Project` cost allocation tag in the Billing console so the budget filter matches.
3. **DNS**: point each environment's domain and its wildcard (`rescope.example.com`,
   `*.rescope.example.com`, and the same for the staging domain) at `node_public_ip`. Use two
   separate domains; staging must not be a subdomain of prod, or prod's wildcard would claim it.
4. **Kubeconfig** (no SSH; Session Manager instead):
   ```bash
   aws ssm start-session --target "$(terraform output -raw instance_id)"
   sudo cat /etc/rancher/k3s/k3s.yaml     # copy locally, replace 127.0.0.1 with node_public_ip
   ```
5. **Repo settings**: set the domains in `environments/*/values.yaml`, the ACME email in
   `platform/cluster-issuer.yaml`, and `backup.bucket` from `terraform output backups_bucket`.
   In GitHub, allow Actions to create pull requests (Settings > Actions > General), and after the
   first CD run make the three `rescope-*` GHCR packages public (or set `imagePullSecrets`).
6. **Argo CD**: `deploy/scripts/bootstrap.sh`. It installs Argo CD and applies `argocd/root.yaml`;
   everything else syncs from git. Admin password:
   `kubectl -n argocd get secret argocd-initial-admin-secret -o jsonpath='{.data.password}' | base64 -d`.
7. **Secrets**, once the sealed-secrets controller is running. Plaintext stays in the gitignored
   `deploy/.secrets/`; only ciphertext is committed.
   ```bash
   # deploy/.secrets/platform.env: CLOUDFLARE_API_TOKEN=..., SLACK_WEBHOOK_URL=...
   # deploy/.secrets/<env>.env: POSTGRES_PASSWORD, RESCOPE_APP_ROLE_PASSWORD, MASTER_KEY,
   #                            ANTHROPIC_API_KEY, BROWSER_USE_API_KEY (see infra/.env.example)
   # Use `openssl rand -hex 32` for the two passwords so they are URL-safe.
   deploy/scripts/seal-secrets.sh platform
   deploy/scripts/seal-secrets.sh staging
   deploy/scripts/seal-secrets.sh prod
   ```
   Commit the generated files through a PR. Back up the controller's key, or the ciphertext in git
   cannot be decrypted by a rebuilt cluster:
   `kubectl -n kube-system get secret -l sealedsecrets.bitnami.com/sealed-secrets-key -o yaml > sealed-secrets-key.yaml`
   (store it outside git).

## Day to day

- **Deploy to staging**: merge to `main`. CI passes, CD builds and scans the images, then commits the
  new tags to `environments/staging/values.yaml`; Argo CD syncs within about three minutes. The
  migration Job runs after Postgres is healthy and before new app pods roll out.
- **Promote to prod**: run the *Promote to prod* workflow. It opens a PR copying staging's tags to
  prod; merge it, then press Sync on `rescope-prod` in Argo CD.
- **Roll back**: revert the tag commit (staging) or the promotion PR (prod) and sync. Image tags are
  commit SHAs, so every previous release is still in GHCR. Migrations are forward-only; a rollback
  across a schema change needs a matching down-migration or a restore.
- **Watch**: Grafana (`kubectl -n monitoring port-forward svc/kube-prometheus-stack-grafana 3000:80`)
  has one *ReScope* dashboard per environment: 30-day availability against the 99.5% SLO, error
  budget left, burn rate, p95 latency, queue depth and restarts.

### Alerts (to Slack)

| Alert | Fires when | First check |
|---|---|---|
| `RescopeErrorBudgetFastBurn` | 5xx ratio > 14.4x budget over 1h and 5m | Recent deploy? `kubectl -n <ns> logs deploy/rescope-api`, roll back |
| `RescopeErrorBudgetSlowBurn` | 5xx ratio > 6x budget over 6h and 30m | Errors tied to one provider or tenant in the API logs |
| `RescopeApiLatencyHigh` | p95 > 2s for 15m | Postgres CPU, TEI latency; chat SSE streams inflate this |
| `RescopeScrapeQueueBacklog` | > 50 scrape jobs queued for 30m | Scraper pod state, Chromium OOMs, platform killswitch |
| `RescopePodRestarting` | > 3 restarts in 15m | `kubectl -n <ns> describe pod`, then look for OOMKilled |
| `RescopeBackupStale` | No successful backup in 26h | `kubectl -n <ns> get jobs`, then the backup Job's logs |

### Backups and restore drill

A CronJob writes a custom-format `pg_dump` to `s3://<bucket>/<namespace>/` nightly at 03:00 UTC;
S3 keeps 30 days. Prove the backups restore, rather than assuming they do, at least monthly:

```bash
deploy/scripts/restore-drill.sh staging "$(terraform -chdir=deploy/terraform output -raw backups_bucket)"
```

It restores the newest dump into a scratch database beside the live one, prints row counts side by
side and the elapsed time (your measured restore time), then drops the scratch database.

### Game day

Break things on purpose in staging and record what happened in `docs/postmortems/`:

1. `kubectl -n rescope-staging delete pod rescope-postgres-0`: does the API recover without a
   restart, and does the fast-burn alert fire and resolve?
2. Scale `rescope-scraper` to 0 and queue several scrapes: does the backlog alert fire?
3. Suspend the backup CronJob for a day: does `RescopeBackupStale` fire?
4. Push an image that fails its readiness probe: does the rolling update hold at the old version?

## Teardown

```bash
cd deploy/terraform && terraform destroy
```

The backup bucket is emptied by its lifecycle rule; delete remaining object versions first if
`destroy` refuses to remove a non-empty bucket.
