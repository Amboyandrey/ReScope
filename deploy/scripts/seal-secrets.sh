#!/usr/bin/env bash
# Seals plaintext secrets from deploy/.secrets/ into files that are safe to commit.
#   seal-secrets.sh staging|prod   reads deploy/.secrets/<env>.env, writes environments/<env>/sealed-secrets.yaml
#   seal-secrets.sh platform       reads deploy/.secrets/platform.env, writes platform/sealed-*.yaml
# Needs kubectl pointed at the cluster, kubeseal and yq (mikefarah).
set -euo pipefail

target="${1:?usage: seal-secrets.sh staging|prod|platform}"
deploy_dir="$(cd "$(dirname "$0")/.." && pwd)"
env_file="$deploy_dir/.secrets/$target.env"
[[ -f "$env_file" ]] || { echo "missing $env_file" >&2; exit 1; }

seal() { # namespace name then kubectl create secret generic arguments
  local ns="$1" name="$2"; shift 2
  kubectl create secret generic "$name" --namespace "$ns" --dry-run=client -o yaml "$@" \
    | kubeseal --format yaml
}

case "$target" in
  staging|prod)
    seal "rescope-$target" rescope-secrets --from-env-file="$env_file" \
      | yq '{"secret": {"sealedData": .spec.encryptedData}}' \
      > "$deploy_dir/environments/$target/sealed-secrets.yaml"
    echo "wrote environments/$target/sealed-secrets.yaml"
    ;;
  platform)
    # shellcheck disable=SC1090
    source "$env_file"
    seal cert-manager cloudflare-api-token --from-literal=api-token="${CLOUDFLARE_API_TOKEN:?}" \
      > "$deploy_dir/platform/sealed-cloudflare-api-token.yaml"
    seal monitoring alertmanager-slack --from-literal=url="${SLACK_WEBHOOK_URL:?}" \
      > "$deploy_dir/platform/sealed-alertmanager-slack.yaml"
    echo "wrote platform/sealed-cloudflare-api-token.yaml and platform/sealed-alertmanager-slack.yaml"
    ;;
  *)
    echo "unknown target: $target" >&2; exit 1
    ;;
esac
