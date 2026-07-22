# Kubernetes Best Practices — Local Demo (WSL2 / kind)

A working, locally-testable project demonstrating all 20 requested
Kubernetes deployment practices, using two small real apps (FastAPI
backend + Flask frontend). **Start with `SETUP-WSL.md`** — it's the
step-by-step guide to build and run everything on WSL2/Ubuntu via
`kind` (Kubernetes-in-Docker).

## What's fully working locally vs. reference-only

Everything here is real, valid Kubernetes YAML / Helm, and everything
in the "fully working locally" list has been checked and can be
`kubectl apply`'d or `helm install`'d exactly as written, following
`SETUP-WSL.md`.

A few items (custom-metric HPA, full ELK logging, ArgoCD against a real
git remote) need extra infrastructure heavier than a from-scratch local
demo should force on you — those are marked **reference** below, with
the exact extra steps documented inline in the relevant file.

## Map: request item -> file

| # | Practice | File(s) |
|---|---|---|
| 1 | Resource requests/limits | `k8s/03-deployment.yaml`, `k8s/04-service.yaml` |
| 2 | Helm chart, env-specific overrides | `helm/umbrella/values-{dev,staging,prod}.yaml` |
| 3 | HPA (CPU + custom metric) | `k8s/05-hpa.yaml` (CPU works locally; custom metric is **reference**, needs Prometheus Adapter/KEDA) |
| 4 | Canary deployment | `k8s/canary/canary-deployment.yaml` |
| 5 | Ingress, TLS, path routing | `k8s/08-ingress.yaml`, `helm/umbrella/charts/frontend/templates/ingress.yaml` |
| 6 | Secret management plan | `k8s/02-secret.yaml` (plan in the file's header comment) |
| 7 | ConfigMap / config-code separation | `k8s/01-configmap.yaml` |
| 8 | PodDisruptionBudget | `k8s/06-pdb.yaml` |
| 9 | Secure container checklist | see checklist below + enforced in every Deployment's `securityContext` |
| 10 | ArgoCD GitOps | `k8s/argocd/application.yaml` (**reference** — needs your own git remote) |
| 11 | StatefulSet | `k8s/09-statefulset.yaml` |
| 12 | Sidecar (Nginx TLS termination) | `k8s/10-sidecar-tls.yaml` |
| 13 | Blue-Green deployment | `k8s/bluegreen/bluegreen-deployment.yaml` |
| 14 | Helm umbrella chart | `helm/umbrella/` (backend + frontend subcharts) |
| 15 | Namespace isolation | `k8s/00-namespace.yaml` |
| 16 | NetworkPolicies | `k8s/07-networkpolicy.yaml` (needs Calico CNI in kind, see `SETUP-WSL.md`) |
| 17 | Liveness/readiness probes | `k8s/03-deployment.yaml`, `apps/backend/main.py` (`/healthz`, `/readyz`) |
| 18 | Centralized logging | `k8s/logging/fluent-bit.yaml` (Fluent Bit works locally; Elasticsearch is **reference**, too heavy for a bare local cluster) |
| 19 | Pod anti-affinity | `k8s/03-deployment.yaml` (`podAntiAffinity`) |
| 20 | Dropped capabilities + seccomp | `k8s/03-deployment.yaml`, `k8s/04-service.yaml` (`securityContext`) |

## Item 9 — secure container execution checklist

Applied consistently across every Deployment in this project:

- [x] `runAsNonRoot: true` — containers run as UID 10001, enforced both
      in the Dockerfile (`USER 10001`) and the pod's `securityContext`
      as a defense-in-depth belt-and-suspenders check.
- [x] `allowPrivilegeEscalation: false` — blocks setuid-style privilege
      escalation inside the container.
- [x] `readOnlyRootFilesystem: true` — the container filesystem is
      immutable at runtime; any dirs that need writing (e.g. `/tmp`) are
      explicitly mounted as `emptyDir` volumes.
- [x] `capabilities: drop: ["ALL"]` — strips every Linux capability;
      add back only the specific ones a workload genuinely needs (none
      of the apps here need any).
- [x] `seccompProfile: RuntimeDefault` — restricts available syscalls
      to the container runtime's default safe subset.
- [x] No `latest` image tags — everything pinned to explicit versions.
- [x] Minimal base images (`python:3.12-slim`, `alpine`-based sidecars)
      to shrink attack surface.

## Project layout

```
apps/               # the two demo microservices (source + Dockerfile each)
  backend/
  frontend/
k8s/                 # raw manifests, one concern per file, numbered in apply order
  canary/
  bluegreen/
  logging/
  argocd/
helm/umbrella/       # Helm umbrella chart: backend + frontend as subcharts
  charts/backend/
  charts/frontend/
SETUP-WSL.md         # full step-by-step local setup on WSL2/Ubuntu via kind
```

## Quick start

See `SETUP-WSL.md` for the full walkthrough. Short version:

```bash
kind create cluster --name demo
docker build -t demo-backend:local  apps/backend
docker build -t demo-frontend:local apps/frontend
kind load docker-image demo-backend:local  --name demo
kind load docker-image demo-frontend:local --name demo

cd helm/umbrella
helm install demo-dev . -f values.yaml -f values-dev.yaml -n demo-dev --create-namespace

kubectl -n demo-dev port-forward svc/demo-dev-frontend 5000:5000
curl http://localhost:5000/
```
