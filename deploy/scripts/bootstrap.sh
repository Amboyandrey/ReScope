#!/usr/bin/env bash
# One-time: installs Argo CD on a fresh cluster and hands everything else to the root app.
# Needs kubectl pointed at the new cluster and helm.
set -euo pipefail

deploy_dir="$(cd "$(dirname "$0")/.." && pwd)"

helm upgrade --install argocd argo-cd \
  --repo https://argoproj.github.io/argo-helm --version 10.9.2 \
  --namespace argocd --create-namespace --wait

kubectl apply -f "$deploy_dir/argocd/root.yaml"
echo "root app applied; watch with: kubectl -n argocd get applications -w"
