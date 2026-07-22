# Running This Locally on WSL2 / Ubuntu

This uses **kind** (Kubernetes-in-Docker) — a real, spec-compliant local
Kubernetes cluster running as Docker containers. It's the standard way to
test Kubernetes manifests locally without a cloud account.

## 1. Prerequisites

Inside your WSL2 Ubuntu shell:

```bash
# Docker: easiest is Docker Desktop for Windows with the WSL2 integration
# enabled for your Ubuntu distro (Settings -> Resources -> WSL Integration).
# Confirm it's visible from WSL:
docker version

# kubectl
curl -LO "https://dl.k8s.io/release/$(curl -L -s https://dl.k8s.io/release/stable.txt)/bin/linux/amd64/kubectl"
sudo install -o root -g root -m 0755 kubectl /usr/local/bin/kubectl
kubectl version --client

# kind
curl -Lo ./kind https://kind.sigs.k8s.io/dl/latest/kind-linux-amd64
chmod +x ./kind
sudo mv ./kind /usr/local/bin/kind
kind version

# Helm
curl https://raw.githubusercontent.com/helm/helm/main/scripts/get-helm-3 | bash
helm version
```

## 2. Create the local cluster

A single command works, but NetworkPolicy enforcement (item 16) needs a
CNI that actually enforces policies — kind's default `kindnet` does not.
Use this cluster config to disable the default CNI so we can install
Calico instead:

```yaml
# kind-config.yaml
kind: Cluster
apiVersion: kind.x-k8s.io/v1alpha4
networking:
  disableDefaultCNI: true
nodes:
  - role: control-plane
    extraPortMappings:
      - containerPort: 80
        hostPort: 80
      - containerPort: 443
        hostPort: 443
```

```bash
kind create cluster --name demo --config kind-config.yaml

# Install Calico (provides real NetworkPolicy enforcement)
kubectl apply -f https://raw.githubusercontent.com/projectcalico/calico/v3.28.0/manifests/calico.yaml

# Wait for it to be ready
kubectl -n kube-system rollout status daemonset/calico-node --timeout=180s
```

If you don't care about testing NetworkPolicy enforcement specifically,
skip Calico and just run `kind create cluster --name demo` — kindnet is
fine for everything else in this project.

## 3. Install cluster add-ons used by this project

```bash
# metrics-server (needed for HPA CPU metrics, item 3)
kubectl apply -f https://github.com/kubernetes-sigs/metrics-server/releases/latest/download/components.yaml
# kind clusters need --kubelet-insecure-tls since kind doesn't issue
# real kubelet certs; patch it in:
kubectl patch deployment metrics-server -n kube-system --type='json' \
  -p='[{"op":"add","path":"/spec/template/spec/containers/0/args/-","value":"--kubelet-insecure-tls"}]'

# ingress-nginx (needed for item 5's Ingress)
kubectl apply -f https://raw.githubusercontent.com/kubernetes/ingress-nginx/main/deploy/static/provider/kind/deploy.yaml
kubectl -n ingress-nginx rollout status deployment/ingress-nginx-controller --timeout=180s

# ArgoCD (needed for item 10's GitOps workflow) - optional, skip if you
# just want to test raw manifests/Helm without GitOps
kubectl create namespace argocd
kubectl apply -n argocd -f https://raw.githubusercontent.com/argoproj/argo-cd/stable/manifests/install.yaml
kubectl -n argocd rollout status deployment/argocd-server --timeout=300s
```

## 4. Build and load the app images

kind clusters can't pull from Docker Hub by default for locally-built
images — you build locally, then explicitly load the image into kind's
internal registry:

```bash
cd apps/backend  && docker build -t demo-backend:local .  && cd -
cd apps/frontend && docker build -t demo-frontend:local . && cd -

kind load docker-image demo-backend:local  --name demo
kind load docker-image demo-frontend:local --name demo
```

Re-run these two `kind load` commands any time you rebuild an image —
kind's cluster nodes have their own isolated image store, separate from
your host Docker.

## 5. Deploy — pick ONE of the two paths below

### Path A: raw manifests (good for seeing each item individually)

```bash
kubectl apply -f k8s/00-namespace.yaml
kubectl apply -f k8s/01-configmap.yaml
kubectl apply -f k8s/02-secret.yaml
kubectl apply -f k8s/03-deployment.yaml
kubectl apply -f k8s/04-service.yaml
kubectl apply -f k8s/05-hpa.yaml
kubectl apply -f k8s/06-pdb.yaml
kubectl apply -f k8s/07-networkpolicy.yaml   # requires Calico, see step 2

# Generate a self-signed cert + secret for Ingress TLS (item 5)
openssl req -x509 -nodes -days 365 -newkey rsa:2048 \
  -keyout /tmp/tls.key -out /tmp/tls.crt -subj "/CN=demo.local"
kubectl create secret tls demo-tls --cert=/tmp/tls.crt --key=/tmp/tls.key -n demo-dev
kubectl apply -f k8s/08-ingress.yaml

kubectl apply -f k8s/09-statefulset.yaml
kubectl apply -f k8s/10-sidecar-tls.yaml       # reuses the demo-tls secret above
kubectl apply -f k8s/canary/canary-deployment.yaml
kubectl apply -f k8s/bluegreen/bluegreen-deployment.yaml
kubectl apply -f k8s/logging/fluent-bit.yaml
```

### Path B: Helm umbrella chart (good for the dev/staging/prod story)

```bash
cd helm/umbrella
helm install demo-dev . -f values.yaml -f values-dev.yaml \
  -n demo-dev --create-namespace

# check what a different environment would render, without installing it
helm template demo-prod . -f values.yaml -f values-prod.yaml
```

## 6. Verify it's actually working

```bash
kubectl get pods -n demo-dev
kubectl get svc -n demo-dev
kubectl get hpa -n demo-dev
kubectl get pdb -n demo-dev

# Port-forward and hit it directly (works without Ingress)
kubectl -n demo-dev port-forward svc/frontend 5000:5000 &
curl http://localhost:5000/

# Or via Ingress, if you set that up:
echo "127.0.0.1 demo.local" | sudo tee -a /etc/hosts
curl -k https://demo.local/
curl -k https://demo.local/api/
```

## 7. Try the interesting failure/scaling scenarios

```bash
# Watch HPA react to load (item 3)
kubectl -n demo-dev run load-gen --image=busybox --restart=Never -- \
  /bin/sh -c "while true; do wget -q -O- http://backend:8000/; done"
kubectl -n demo-dev get hpa backend-hpa --watch

# Test PDB protection during a drain (item 8)
kubectl get nodes
kubectl drain <node-name> --ignore-daemonsets --delete-emptydir-data
# watch that at least minAvailable backend pods stay up throughout

# Test NetworkPolicy is actually enforced (item 16, needs Calico)
kubectl run -n demo-dev test-pod --image=busybox --restart=Never -- sleep 3600
kubectl -n demo-dev exec test-pod -- wget -qO- --timeout=3 http://backend:8000/
# should FAIL - test-pod isn't labeled app=frontend, so the NetworkPolicy blocks it
```

## Cleanup

```bash
kind delete cluster --name demo
```

That tears down everything — cluster, all workloads, all add-ons — with
one command, since it's all just Docker containers on your machine.
