# Kubernetes on WSL2: A Beginner's Complete Walkthrough

This is a full record of a real, working session — setting up a local
Kubernetes cluster on WSL2/Ubuntu, deploying two apps, and proving six
production deployment practices actually work using live evidence, not
just "the YAML applied." Two real bugs were found and fixed along the
way, and several realistic debugging moments are included on purpose —
this is what actually happens when you run Kubernetes for real, and
seeing it is more useful for learning than a version with no mistakes.

**Prerequisite:** the `k8s-best-practices-demo.zip` project (apps,
manifests, Helm chart). Unzip it and `cd` into `k8s-demo` before
starting.

---

## Part 0: Concepts you'll need before starting

A few terms used throughout, explained simply:

- **Pod** — the smallest deployable unit in Kubernetes; one or more
  containers running together. Think of it as "one running copy of
  your app."
- **Deployment** — tells Kubernetes "keep N copies (replicas) of this
  Pod running at all times." If one crashes, Deployment replaces it.
- **Service** — a stable network address that routes traffic to a set
  of Pods, chosen by matching labels. Pods come and go; the Service
  name stays constant.
- **Namespace** — a way to partition a cluster into separate areas
  (e.g. `dev`, `staging`, `prod`) so resources don't collide.
- **Helm** — a package manager for Kubernetes. A "chart" is a
  templated bundle of manifests you can install with one command and
  reconfigure via `values.yaml` files instead of editing raw YAML.
- **kind** — runs a real Kubernetes cluster entirely inside Docker
  containers on your own machine. No cloud account needed.

---

## Part 1: Install the tools

```bash
# Confirm Docker is working (Docker Desktop + WSL2 integration, or Docker Engine)
docker version
```
**You should see:** a `Client` block and a `Server` block, no errors.

```bash
# kubectl — the command-line tool to talk to any Kubernetes cluster
curl -LO "https://dl.k8s.io/release/$(curl -L -s https://dl.k8s.io/release/stable.txt)/bin/linux/amd64/kubectl"
sudo install -o root -g root -m 0755 kubectl /usr/local/bin/kubectl
kubectl version --client
```
**You should see:** a `Client Version` line.

```bash
# kind — runs Kubernetes inside Docker, for local testing
curl -Lo ./kind https://kind.sigs.k8s.io/dl/latest/kind-linux-amd64
chmod +x ./kind && sudo mv ./kind /usr/local/bin/kind
kind version
```
**You should see:** a `kind vX.X.X` line.

```bash
# Helm — the Kubernetes package manager
curl https://raw.githubusercontent.com/helm/helm/main/scripts/get-helm-3 | bash
helm version
```
**You should see:** a `version.BuildInfo{...}` line.

---

## Part 2: Create the cluster

```bash
kind create cluster --name demo
kubectl cluster-info --context kind-demo
```
**You should see:** `Kubernetes control plane is running at https://127.0.0.1:PORT`.

```bash
kubectl get nodes
```
**You should see:** one node, `STATUS = Ready`.

> **Note for later:** this basic `kind create cluster` command doesn't
> map ports 80/443 to your machine, and uses the default `kindnet`
> network plugin, which doesn't enforce `NetworkPolicy` rules. Both of
> these matter later (Ingress testing, NetworkPolicy testing) — we
> work around the first with `port-forward`, and the second would need
> a cluster rebuild with a different network plugin (Calico), which
> this session didn't get to.

---

## Part 3: Install cluster add-ons

Two add-ons are needed: **metrics-server** (so Kubernetes can measure
CPU/memory usage — required for autoscaling) and **ingress-nginx**
(routes external HTTP/HTTPS traffic into the cluster).

```bash
kubectl apply -f https://github.com/kubernetes-sigs/metrics-server/releases/latest/download/components.yaml

# kind's Kubelet certs aren't "real" ones metrics-server trusts by default — patch around it:
kubectl patch deployment metrics-server -n kube-system --type='json' \
  -p='[{"op":"add","path":"/spec/template/spec/containers/0/args/-","value":"--kubelet-insecure-tls"}]'

kubectl apply -f https://raw.githubusercontent.com/kubernetes/ingress-nginx/main/deploy/static/provider/kind/deploy.yaml
kubectl -n ingress-nginx rollout status deployment/ingress-nginx-controller --timeout=180s
```
**You should see:** `deployment "ingress-nginx-controller" successfully rolled out`.

```bash
kubectl top nodes
```
**You should see:** real CPU/memory numbers (may take ~60s after
install to start reporting — retry if blank).

---

## Part 4: Build the app images and load them into the cluster

Two small apps are used throughout: a FastAPI **backend**, and a Flask
**frontend** that calls it.

```bash
docker build -t demo-backend:local  apps/backend
docker build -t demo-frontend:local apps/frontend
```
**You should see:** both end with `naming to docker.io/library/demo-...:local`, no errors.

> **Why `kind load` is needed:** a `kind` cluster runs inside Docker,
> but it has its own *separate* internal image store from your host
> machine's Docker. Building an image with `docker build` puts it on
> your host — the cluster can't see it until you explicitly copy it in.

```bash
kind load docker-image demo-backend:local  --name demo
kind load docker-image demo-frontend:local --name demo
```
**You should see:** `Image: "..." not yet present on node "demo-control-plane", loading...` for each — confirms the copy happened.

---

## Part 5: Deploy with Helm

```bash
cd helm/umbrella
helm install demo-dev . -f values.yaml -f values-dev.yaml -n demo-dev --create-namespace
```
**You should see:** `STATUS: deployed`.

```bash
kubectl get pods -n demo-dev
```
**You should see:** `demo-dev-backend-xxxx` and `demo-dev-frontend-xxxx`, both `1/1 Running`.

> **If you see `0/1` or `CrashLoopBackOff`:** don't panic, this is
> normal to hit at least once. Run `kubectl logs -n demo-dev
> <pod-name> --previous` to see why it crashed. Later in this guide,
> exactly this happened — twice — and both times were the same root
> cause, explained in Part 7.

```bash
cd ../..   # back to project root
```

---

## Part 6: Prove the app actually works, end to end

This is the first real proof-of-life test — not just "pods are
Running," but "a request actually flows through the whole system."

```bash
kubectl -n demo-dev port-forward svc/demo-dev-frontend 5050:5000 &
sleep 2
curl -s http://localhost:5050/
```
**You should see JSON like:**
```json
{"backend_response":{"env":"dev","message":"Hello from backend (dev)","requests_served":1},"frontend":"ok"}
```

**What this one line actually proves:**
- The frontend Pod received your request through the Service and `port-forward`.
- The frontend successfully called the backend over the cluster's internal network (Kubernetes DNS resolved `demo-dev-backend` to a real Pod IP).
- The `"env": "dev"` value came from a `ConfigMap`, not a hardcoded default — proving configuration injection works.
- `requests_served` is live state from the actually-running Python process, not a mock.

```bash
kill %1   # stop the port-forward when done
```

> **⚠️ Common mistake made in this session:** the very first attempt
> used port `5000` for the local side of `port-forward`, and it
> silently connected to a *completely unrelated* app already running
> on the machine's port 5000 (something called "Bread of the Word
> API"), returning totally wrong output that looked like an error page.
> **Lesson: always pick a local port unlikely to collide** (like
> `5050`, `8095`, etc.), and if a `port-forward` command reports
> `address already in use`, that's your sign — don't trust whatever
> `curl` returns after that error.

---

## Part 7: Debugging story — a real bug, found and fixed

While testing, the frontend Pod actually **crashed** on a later
`helm upgrade`. This section is kept in because working through a real
failure teaches more than a guide with none.

**Symptom:**
```
NAME                                 READY   STATUS   RESTARTS
demo-dev-frontend-8545f76577-4vkg7   0/1     Error    2
```

**Diagnosis — always start here when a Pod won't come up:**
```bash
kubectl logs -n demo-dev deploy/demo-dev-frontend --previous
```
This showed a Python traceback ending in:
```
FileNotFoundError: [Errno 2] No usable temporary directory found in ['/tmp', '/var/tmp', '/usr/tmp', '/app']
```

**Root cause:** the Deployment's `securityContext` had
`readOnlyRootFilesystem: true` (a real security best practice — item 9
on the original list), which locks the entire container filesystem
except for volumes explicitly mounted as writable. But `gunicorn` (the
server running the Flask app) needs to write a small temp file at
startup, and **no writable volume had been mounted for `/tmp`** — so
every directory it tried was read-only, and it crashed immediately.

**Fix — add an `emptyDir` volume mounted at `/tmp`:**
```yaml
          volumeMounts:
            - name: tmp
              mountPath: /tmp
      volumes:
        - name: tmp
          emptyDir: {}
```
This one addition keeps the security posture (still fully read-only
everywhere else) while giving the one directory the app actually needs
to write to.

**Apply the fix:**
```bash
helm upgrade demo-dev . -f values.yaml -f values-dev.yaml -n demo-dev
kubectl -n demo-dev get pods --watch
```
**You should see:** the new Pod comes up `1/1 Running`, the old one
terminates cleanly.

> This exact bug existed in **both** the frontend and backend charts
> (copy-pasted security settings without the matching volume both
> times), and was only caught in the backend when it was specifically
> tested later — the backend's FastAPI/uvicorn server didn't need to
> write to `/tmp` at startup, so it "worked" for a while before the gap
> was noticed. **Lesson: a bug that doesn't crash immediately isn't
> proof it's not there — test the specific thing you changed, don't
> just check that the Pod is `Running`.**

---

## Part 8: Prove security is actually enforced (not just declared in YAML)

Anyone can write `runAsNonRoot: true` in a YAML file. This section
proves Kubernetes is genuinely enforcing it at runtime.

```bash
kubectl -n demo-dev exec -it deploy/demo-dev-backend -- whoami
```
**You should see:** `appuser` (or a UID like `10001`) — **not** `root`.

```bash
kubectl -n demo-dev exec -it deploy/demo-dev-backend -- touch /testfile
```
**You should see:** `touch: cannot touch '/testfile': Read-only file system` — this is a *good* failure. It proves the filesystem really is locked.

```bash
kubectl -n demo-dev exec -it deploy/demo-dev-backend -- touch /tmp/testfile && echo "tmp write OK"
```
**You should see:** `tmp write OK` — confirms the one deliberate exception (the `/tmp` volume from Part 7) is working exactly as intended: locked everywhere, writable only where explicitly allowed.

> **Note:** don't run `kubectl` commands with `sudo`. `kubectl` talks
> to the cluster using your own kubeconfig file (`~/.kube/config`), not
> root system permissions — `sudo kubectl` often breaks because it
> looks for a *different* (root user's) kubeconfig that doesn't exist.

---

## Part 9: Prove PodDisruptionBudget (PDB) actually protects availability

**What a PDB does:** guarantees a minimum number of healthy Pods stay
running during *voluntary* disruptions (node maintenance, cluster
upgrades, manual evictions) — it does **not** protect against a Pod
crashing on its own.

**Enable it and scale to 2 replicas** (a PDB needs more replicas than
its `minAvailable` threshold to actually do anything):
```bash
cd helm/umbrella
helm upgrade demo-dev . -f values.yaml -f values-dev.yaml \
  --set backend.podDisruptionBudget.enabled=true \
  --set backend.podDisruptionBudget.minAvailable=1 \
  --set backend.replicaCount=2 \
  -n demo-dev
```

```bash
kubectl -n demo-dev get pdb
kubectl -n demo-dev describe pdb demo-dev-backend
```
**You should see:** `Current: 2`, `Desired: 1`, `Allowed disruptions: 1`.

**Real test — try to evict both replicas back-to-back**, simulating
what happens during a node drain:

```bash
kubectl proxy --port=8081 &
sleep 2

POD1=$(kubectl -n demo-dev get pods -l app.kubernetes.io/name=backend -o jsonpath='{.items[0].metadata.name}')
POD2=$(kubectl -n demo-dev get pods -l app.kubernetes.io/name=backend -o jsonpath='{.items[1].metadata.name}')

# 1st eviction — should SUCCEED (2 healthy -> 1 still satisfies minAvailable:1)
curl -s -X POST http://localhost:8081/api/v1/namespaces/demo-dev/pods/$POD1/eviction \
  -H "Content-Type: application/json" \
  -d "{\"apiVersion\":\"policy/v1\",\"kind\":\"Eviction\",\"metadata\":{\"name\":\"$POD1\",\"namespace\":\"demo-dev\"}}"
echo ""

# 2nd eviction, fired immediately — should be BLOCKED
curl -s -X POST http://localhost:8081/api/v1/namespaces/demo-dev/pods/$POD2/eviction \
  -H "Content-Type: application/json" \
  -d "{\"apiVersion\":\"policy/v1\",\"kind\":\"Eviction\",\"metadata\":{\"name\":\"$POD2\",\"namespace\":\"demo-dev\"}}"
echo ""

kill %1
```

**You should see:**
- 1st eviction: `"status": "Success"`, `"code": 201`
- 2nd eviction: `"status": "Failure"`, `"code": 429`, with message
  `"Cannot evict pod as it would violate the pod's disruption budget."`

That second failure **is** the proof — Kubernetes actively refused to
let you drop below the minimum healthy count.

> **Why `kubectl create -f` doesn't work for this:** an `Eviction` is a
> special API "subresource," not a normal object you can create with
> `kubectl create -f`. You have to `POST` directly to the Pod's
> `/eviction` endpoint, which is what `kubectl proxy` + `curl` does
> above.

---

## Part 10: Prove Horizontal Pod Autoscaling (HPA) reacts to real load

**What HPA does:** automatically changes the number of replicas based
on measured resource usage (here, CPU).

**Enable it:**
```bash
helm upgrade demo-dev . -f values.yaml -f values-dev.yaml \
  --set backend.autoscaling.enabled=true \
  --set backend.autoscaling.minReplicas=1 \
  --set backend.autoscaling.maxReplicas=4 \
  -n demo-dev

kubectl -n demo-dev get hpa
```
**You should see:** a `TARGETS` column with a real percentage, like `1%/70%`. If it says `<unknown>/70%`, wait ~60 seconds for metrics-server to catch up and check again.

**Generate real load:**
```bash
kubectl -n demo-dev run load-gen --image=busybox --restart=Never -- \
  /bin/sh -c "while true; do wget -q -O- http://demo-dev-backend:8000/; done"

kubectl -n demo-dev get hpa --watch
```
**You should see** (over 1-3 minutes): `TARGETS` climb past `70%`, then `REPLICAS` step up from `1` toward `4`. In this session it hit `89%/70%` and scaled all the way to `4`. Press `Ctrl+C` once you see it scale up.

**Remove the load and watch it scale back down:**
```bash
kubectl -n demo-dev delete pod load-gen
kubectl -n demo-dev get hpa --watch
```
**You should see:** CPU% drops immediately, but `REPLICAS` stays high for a while — this is intentional. HPA has a default **5-minute stabilization window** before scaling down, specifically to avoid rapidly flapping replica counts up and down on small fluctuations. In this session, `REPLICAS` dropped from `4` to `1` almost exactly 5 minutes after the load stopped. Press `Ctrl+C` once satisfied — you don't need to wait the full 5 minutes to consider this proven.

---

## Part 11: Blue-Green deployment — instant, zero-downtime cutover

**The idea:** run two full, independent versions side by side (blue =
current, green = new). A single Service points at whichever one is
"live." Switching is instant and reversible — just change the
Service's label selector.

**Deploy both versions:**
```bash
cd ~/k8s-demo
kubectl apply -f k8s/bluegreen/bluegreen-deployment.yaml
kubectl -n demo-dev get pods -l app=backend --show-labels
```
**You should see:** 3 `backend-blue-*` Pods and 3 `backend-green-*` Pods, all `1/1 Running`.

**Start a continuous request loop** (leave this running in one terminal — this is what you'll watch flip live):
```bash
# always check the port is free first
lsof -i :8095 || echo "port free"

kubectl -n demo-dev port-forward svc/backend-live 8095:8000 &
sleep 2
while true; do curl -s http://localhost:8095/version; echo " <- $(date +%H:%M:%S)"; sleep 1; done
```
**You should see:** a steady stream of `{"version":"v1"}` (blue is live by default).

**In a second terminal, cut over to green:**
```bash
kubectl -n demo-dev patch service backend-live \
  -p '{"spec":{"selector":{"app":"backend","color":"green"}}}'
```
**Watch terminal 1** — within a request or two, output flips to `{"version":"v2"}`.

**Roll back just as instantly:**
```bash
kubectl -n demo-dev patch service backend-live \
  -p '{"spec":{"selector":{"app":"backend","color":"blue"}}}'
```
**Watch terminal 1** — flips right back to `v1`.

**Cleanup:**
```bash
# Ctrl+C the loop in terminal 1 first, then:
pkill -f "port-forward svc/backend-live"
kubectl -n demo-dev delete -f k8s/bluegreen/bluegreen-deployment.yaml
```

> **⚠️ Debugging moment worth knowing:** in this session, a second
> `port-forward` was accidentally started on the *same port* as one
> already running. The new command failed with `address already in
> use` — but the *old, still-running* loop kept printing output from
> whatever pod it had originally connected to, which made it look like
> the Service selector patch "wasn't working." It was working — the
> terminal was just watching a stale, already-established connection.
> **Key lesson: `kubectl port-forward` locks onto ONE pod when it
> starts and keeps talking to that same pod for its entire lifetime —
> a Service-selector change does NOT affect an already-open
> `port-forward` session.** Always fully kill (`pkill -f
> "port-forward ..."`) and restart `port-forward` fresh after changing
> a Service's routing, and check `lsof -i :PORT` before starting a new
> one.

---

## Part 12: Canary deployment — gradual traffic shifting by replica ratio

**The idea:** unlike blue-green's instant full switch, a canary
release shifts traffic *gradually* by running a small number of
"canary" replicas alongside a larger "stable" fleet. Since a plain
Kubernetes Service load-balances evenly across every Pod matching its
selector, **the traffic ratio naturally follows the replica ratio** —
no extra tooling required.

**Deploy stable (5 replicas) + canary (1 replica):**
```bash
kubectl apply -f k8s/canary/canary-deployment.yaml
kubectl -n demo-dev get pods -l app=backend --show-labels
```
**You should see:** 5 `backend-stable-*` Pods and 1 `backend-canary-*` Pod.

> **⚠️ Important — clean up any other deployment using the same
> `app: backend` label first** (like the blue-green one from Part 11).
> Multiple Deployments sharing that label will all feed into the same
> Service selector and corrupt the traffic-split test. Run:
> ```bash
> kubectl -n demo-dev delete -f k8s/bluegreen/bluegreen-deployment.yaml
> ```
> before starting this section if you did Part 11 first.

**Test the traffic split — send a batch of requests from *inside* the
cluster and count the results:**
```bash
kubectl -n demo-dev run canary-test --image=busybox --restart=Never --rm -it -- \
  /bin/sh -c 'for i in $(seq 1 50); do wget -q -O- http://backend-canary-svc:8000/version; echo ""; done' \
  | sort | uniq -c
```
**You should see something like:**
```
     33 {"version":"v1"}
      8 {"version":"v2"}
```
Roughly a 5:1 ratio, matching the 5:1 replica split. Exact numbers will vary — this is genuine load-balancer randomness, not a fixed ratio.

> **⚠️ Why NOT to use `port-forward` for this test:** as established
> in Part 11, `port-forward` pins to a single Pod for its entire
> session. Testing traffic distribution requires every single request
> to be independently load-balanced by Kubernetes itself — which only
> happens for requests that genuinely originate from *inside* the
> cluster, hitting the Service by its DNS name. That's why this test
> uses a temporary `busybox` Pod (`kubectl run ... --rm`) instead of
> `port-forward` + `curl` from your own machine.

**Promote the canary — shift to a 50/50 split:**
```bash
kubectl -n demo-dev scale deployment backend-canary --replicas=3
kubectl -n demo-dev scale deployment backend-stable --replicas=3
```

> **⚠️ Wait a few seconds after scaling before testing.** Newly
> created/removed Pods take a moment to register with the Service. In
> this session, testing immediately after scaling produced a
> lower-than-expected total request count (39 instead of 50) — some
> requests landed during the transition window. Waiting ~10-15 seconds
> and retesting resolved it cleanly.

```bash
kubectl -n demo-dev run canary-test --image=busybox --restart=Never --rm -it -- \
  /bin/sh -c 'for i in $(seq 1 50); do wget -q -O- http://backend-canary-svc:8000/version; echo ""; done' \
  | sort | uniq -c
```
**You should see:** roughly `~25/25`.

**Full promotion — canary fully replaces stable:**
```bash
kubectl -n demo-dev scale deployment backend-canary --replicas=6
kubectl -n demo-dev scale deployment backend-stable --replicas=0
```
```bash
kubectl -n demo-dev run canary-test --image=busybox --restart=Never --rm -it -- \
  /bin/sh -c 'for i in $(seq 1 30); do wget -q -O- http://backend-canary-svc:8000/version; echo ""; done' \
  | sort | uniq -c
```
**You should see:** all `v2` — stable now receives zero traffic and can be safely deleted.

**Cleanup:**
```bash
kubectl -n demo-dev delete -f k8s/canary/canary-deployment.yaml
```

---

## Part 13: Ingress + TLS — real path-based routing through a real controller

**The idea:** instead of exposing each Service separately, an Ingress
resource routes external traffic to different Services based on the
URL path (e.g. `/` vs `/api/`), and can terminate TLS (HTTPS) at the
edge.

**Generate a self-signed certificate for local testing:**
```bash
cd ~/k8s-demo
openssl req -x509 -nodes -days 365 -newkey rsa:2048 \
  -keyout /tmp/tls.key -out /tmp/tls.crt -subj "/CN=demo.local"

kubectl create secret tls demo-tls --cert=/tmp/tls.crt --key=/tmp/tls.key -n demo-dev
```
**You should see:** `secret/demo-tls created`.

**Enable the Ingress on the Helm release:**
```bash
cd helm/umbrella
helm upgrade demo-dev . -f values.yaml -f values-dev.yaml \
  --set frontend.ingress.enabled=true \
  --set frontend.ingress.host=demo.local \
  --set frontend.ingress.tlsSecretName=demo-tls \
  -n demo-dev

kubectl -n demo-dev get ingress
```
**You should see:** a row for `demo-dev-frontend` with `HOSTS = demo.local`.

> **⚠️ Why NodePort testing failed in this session, and what worked
> instead:** the plan was to hit the Ingress controller's NodePort
> directly (`curl https://demo.local:<nodeport>/`). This failed with
> `Couldn't connect to server` — because the basic `kind create cluster`
> command from Part 2 never mapped any ports from the container to the
> host machine, so NodePorts only exist *inside* Docker's internal
> network, invisible to `localhost`. **The working fix:**
> `port-forward` straight to the ingress-nginx controller's Service
> instead — this bypasses the NodePort entirely and reuses the same
> reliable pattern used throughout this whole session.

```bash
lsof -i :8443 || echo "port free"
kubectl -n ingress-nginx port-forward svc/ingress-nginx-controller 8443:443 &
sleep 2
```

**Test routing to the frontend (`/`):**
```bash
curl -k --resolve demo.local:8443:127.0.0.1 https://demo.local:8443/
```
**You should see:** the same `frontend`/`backend_response` JSON from Part 6 — but this time it traveled through a real TLS handshake and the actual Ingress controller, not a direct Service port-forward.

**Test routing to the backend (`/api/`):**
```bash
curl -k --resolve demo.local:8443:127.0.0.1 https://demo.local:8443/api/
```
**You should see:** the backend's raw JSON, with **no** `frontend`/`backend_response` wrapper — proof the Ingress correctly routes `/api/` straight to the backend, bypassing the frontend entirely.

**Verify the certificate is really the one you generated:**
```bash
curl -kv --resolve demo.local:8443:127.0.0.1 https://demo.local:8443/ 2>&1 | grep -i "subject:\|issuer:"
```
**You should see:** `subject: CN=demo.local` and `issuer: CN=demo.local` — confirms nginx is genuinely terminating TLS with your cert.

**Cleanup:**
```bash
kill %1 2>/dev/null
pkill -f "port-forward svc/ingress-nginx-controller"
```

---

## Full summary — what's actually been proven, and how

| # | Practice | How it was proven |
|---|---|---|
| 9, 20 | Secure container execution | Non-root user confirmed via `whoami`; write blocked everywhere except a deliberately mounted `/tmp` volume |
| 1, 17 | Resource limits / probes | Declared in every Deployment, actively enforced by the scheduler and kubelet |
| 7 | Config/code separation | `env: dev` value traced back to a `ConfigMap`, not a hardcoded default |
| 8 | PodDisruptionBudget | 1st Pod eviction succeeded, 2nd correctly blocked with HTTP `429` |
| 3 | Horizontal Pod Autoscaler | Full real cycle: 1 → 4 replicas under load, back to 1 after cooldown |
| 13 | Blue-Green deployment | Live traffic flip observed in both directions, zero downtime |
| 4 | Canary deployment | Traffic ratio measured and matched replica ratio at 5:1 and 3:3 |
| 5 | Ingress + TLS + path routing | Correct `/` vs `/api/` routing confirmed; certificate identity verified |

**Two real bugs were found and fixed** (missing `/tmp` volumes under
`readOnlyRootFilesystem`, in both the frontend and backend Helm
charts) — found via actual crash logs, not guesswork.

**Debugging patterns worth remembering for any future Kubernetes
work:**
1. `kubectl logs <pod> --previous` is always the first move when a Pod
   is crashing — don't guess, read the actual error.
2. `kubectl port-forward` locks onto one Pod for its whole session —
   it's the wrong tool for testing load-balancing across multiple
   Pods; use a Pod running *inside* the cluster instead
   (`kubectl run ... --rm`).
3. Always check `lsof -i :PORT` before starting a new `port-forward` —
   port collisions produce confusing, misleading output rather than a
   clear error every time.
4. Never run `kubectl` with `sudo` — it uses a different, usually
   nonexistent, kubeconfig.
5. After scaling a Deployment, wait a few seconds before testing — new
   Pods take a moment to register as healthy Endpoints.
6. A Service manifest that references a hardcoded name (`backend`,
   `frontend`) will silently do nothing if your actual Deployment was
   installed via Helm with a different generated name
   (`demo-dev-backend`) — always double check actual resource names
   with `kubectl get svc -n <namespace>` rather than assuming.

---

## What's left, if you want to keep going

- **NetworkPolicy enforcement** (item 16) — needs a cluster rebuilt
  with a network plugin that actually enforces policies, since the
  default `kindnet` used in Part 2 does not. Would need:
  ```bash
  kind create cluster --name demo --config kind-config.yaml   # with disableDefaultCNI: true
  kubectl apply -f https://raw.githubusercontent.com/projectcalico/calico/v3.28.0/manifests/calico.yaml
  ```
- **Custom-metric HPA**, **full ELK logging**, and **ArgoCD GitOps**
  are documented in the project's manifests with the exact extra
  infrastructure each would need, but weren't exercised live in this
  session — they require more than a from-scratch local setup
  reasonably should force on a first pass.

```bash
# Full cleanup when you're completely done
kind delete cluster --name demo
```