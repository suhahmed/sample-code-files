# flask-gitops-demo — DevSecOps CI/CD with GitHub Actions + ArgoCD

A small Flask service with a complete **GitOps** pipeline: GitHub Actions builds, tests, scans,
signs and publishes the image; ArgoCD pulls the desired state from this repo and deploys it.
CI never holds cluster credentials.

```
 dev ──PR──► GitHub ──► CI (GitHub Actions)
                         ├─ 1. Lint (ruff) + unit tests (pytest, ≥80% coverage gate)
                         ├─ 2. SAST (Bandit, CodeQL) · SCA (pip-audit, Dependabot) · secrets (Gitleaks)
                         ├─ 3. IaC: Hadolint · kubeconform · Trivy config scan
                         ├─ 4. Build image → Trivy CVE gate (HIGH/CRITICAL)
                         ├─ 5. main only: push to GHCR · SBOM (SPDX) · SLSA provenance · cosign keyless sign
                         └─ 6. main only: bump tag in k8s/overlays/dev → commit
                                              │
                    ArgoCD (in cluster) ◄─────┘ watches k8s/overlays/*
                         ├─ flask-demo-dev   auto-sync + prune + self-heal
                         └─ flask-demo-prod  syncs after a reviewed "promote" PR is merged
```

## Repo layout

| Path | Purpose |
|---|---|
| `app/`, `tests/` | Flask app (`/`, `/healthz`, `/readyz`, `/metrics`) and pytest suite |
| `Dockerfile` | Multi-stage, slim, non-root (UID 10001), gunicorn |
| `k8s/base` | Deployment (hardened securityContext, probes, limits), Service, ConfigMap, NetworkPolicy, PDB |
| `k8s/overlays/{dev,prod}` | Namespace (Pod Security `restricted`), replicas, env, **image tag** |
| `argocd/` | AppProject (least privilege), dev/prod Applications, app-of-apps root |
| `.github/workflows/ci.yml` | Main DevSecOps pipeline |
| `.github/workflows/promote-prod.yml` | Verifies cosign signature, opens prod promotion PR |
| `.github/workflows/codeql.yml` | CodeQL SAST (PR, main, weekly) |
| `.github/dependabot.yml` | Weekly pip / Docker / Actions updates |

## Setup (existing EKS / GKE / AKS cluster with ArgoCD installed)

1. **Create the repo** and push this code to `main`.
2. **Replace `OWNER`** with your GitHub user/org (lowercase) everywhere:
   ```bash
   grep -rl OWNER k8s argocd | xargs sed -i 's/OWNER/<your-github-owner>/g'
   ```
3. **GitHub settings**
   - *Settings → Actions → General → Workflow permissions*: Read and write; allow Actions to create PRs.
   - *Settings → Environments*: create `dev` and `production`; add **required reviewers** to `production`.
   - *Branch protection on `main`*: require PR + checks `Lint & unit tests`, `SAST, SCA & secret scan`,
     `Dockerfile & K8s manifest checks`, `Build, scan & sign image`, `CodeQL`.
     If protection blocks the bot's dev-tag commit, allow `github-actions[bot]` to bypass, or push with a
     GitHub App token / deploy key instead of `GITHUB_TOKEN`.
   - Org-owned repo? Add a `GITLEAKS_LICENSE` secret (free) and uncomment it in `ci.yml`.
4. **Package visibility**: after the first push, make the GHCR package public, *or* give the cluster a pull
   secret:
   ```bash
   kubectl create secret docker-registry ghcr -n flask-demo-dev \
     --docker-server=ghcr.io --docker-username=<user> --docker-password=<PAT with read:packages>
   ```
   (and add `imagePullSecrets` to the Deployment).
5. **Private repo?** Register it with ArgoCD:
   `argocd repo add https://github.com/<owner>/flask-gitops-demo.git --username <user> --password <PAT>`
6. **Bootstrap ArgoCD** (one time):
   ```bash
   kubectl apply -n argocd -f argocd/root-app.yaml
   argocd app list   # flask-demo-root, flask-demo-dev, flask-demo-prod
   ```
7. *(Optional)* Add a GitHub webhook → `https://<argocd-host>/api/webhook` for instant syncs instead of
   the ~3 min poll.

## Day-to-day flow

- **Feature work**: open a PR → all checks run (no image push). Merge when green.
- **Dev deploy**: merge to `main` → image `ghcr.io/<owner>/flask-gitops-demo:sha-xxxxxxx` is pushed,
  signed, and its tag committed to `k8s/overlays/dev` → ArgoCD syncs dev.
- **Prod deploy**: *Actions → Promote to prod → Run* (optionally pass a tag). The job verifies the
  cosign signature came from this repo's `ci.yml` on `main`, then opens a PR. Merge it → ArgoCD syncs prod.
- **Rollback**: `git revert` the deploy commit (or `argocd app rollback flask-demo-prod`; self-heal will
  re-apply git afterwards, so revert in git to make it stick).

## Verify locally

```bash
python -m venv .venv && . .venv/bin/activate
pip install -r requirements-dev.txt
ruff check . && ruff format --check . && pytest
bandit -r app -ll && pip-audit -r requirements.txt --strict
kubectl kustomize k8s/overlays/dev
docker build -t flask-gitops-demo . && docker run -p 8080:8080 flask-gitops-demo
```

```bash
# Verify a published image's signature yourself
cosign verify ghcr.io/<owner>/flask-gitops-demo:sha-xxxxxxx \
  --certificate-identity-regexp '^https://github.com/<owner>/flask-gitops-demo/.github/workflows/ci.yml@refs/heads/main$' \
  --certificate-oidc-issuer https://token.actions.githubusercontent.com
```

## Hardening ideas (next steps)

- Pin every third-party action to a full commit SHA (Dependabot will keep them updated).
- Enforce signatures at admission with **Kyverno** `verifyImages` or Sigstore **policy-controller**,
  so only cosign-signed images from this workflow can run.
- Add **DAST** (OWASP ZAP baseline) against the dev URL after ArgoCD reports `Healthy`.
- Use **Argo Rollouts** for canary/blue-green in prod, gated on Prometheus metrics.
- Manage secrets with External Secrets Operator or Sealed Secrets (never plain Secrets in git).
- With multiple gunicorn workers, enable `prometheus_client` multiprocess mode
  (`PROMETHEUS_MULTIPROC_DIR`) so `/metrics` aggregates across workers.
