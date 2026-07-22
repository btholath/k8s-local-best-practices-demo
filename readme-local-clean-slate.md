Here's the full teardown, in order — this gets you back to nothing, cleanly.

## 1. Stop any lingering background processes first

Stale `port-forward`/`proxy` sessions from earlier in the session are almost certainly still running and holding ports open. Kill them all before touching the cluster:

```bash
pkill -f "port-forward" 2>/dev/null
pkill -f "kubectl proxy" 2>/dev/null
jobs
```
**Expect:** `jobs` shows nothing running (or prints nothing at all). If anything's still listed, `kill %N` for that job number.

## 2. Delete the Helm release (removes all app resources cleanly)

```bash
cd ~/k8s-demo/helm/umbrella 2>/dev/null
helm uninstall demo-dev -n demo-dev
```
**Expect:** `release "demo-dev" uninstalled`.

## 3. Delete any raw manifests applied outside Helm

These may or may not still exist depending on what you cleaned up already, but it's safe to run all of them — deleting something already gone just prints "not found" harmlessly:

```bash
cd ~/k8s-demo
kubectl -n demo-dev delete -f k8s/bluegreen/bluegreen-deployment.yaml 2>/dev/null
kubectl -n demo-dev delete -f k8s/canary/canary-deployment.yaml 2>/dev/null
kubectl -n demo-dev delete -f k8s/06-pdb.yaml 2>/dev/null
kubectl -n demo-dev delete secret demo-tls 2>/dev/null
```

## 4. Delete the whole namespace (fastest way to guarantee nothing's left)

```bash
kubectl delete namespace demo-dev
```
**Expect:** `namespace "demo-dev" deleted` — this takes everything in it down with it: Pods, Services, ConfigMaps, Secrets, PDBs, HPAs, everything, in one shot.

## 5. Confirm it's actually gone

```bash
kubectl get namespaces
kubectl get all -A | grep demo
```
**Expect:** `demo-dev` no longer listed; second command returns nothing.

## 6. The cleanest possible reset — delete the entire cluster

Since everything here runs inside Docker via `kind`, this is the real "back to zero" button — wipes the cluster, every add-on (metrics-server, ingress-nginx), every namespace, everything:

```bash
kind delete cluster --name demo
```
**Expect:** `Deleting cluster "demo" ...` then it finishes silently — no more `kind-demo` context.

```bash
kind get clusters
```
**Expect:** `No kind clusters found.`

```bash
kubectl config get-contexts
```
**Expect:** `kind-demo` no longer listed (your `kubectl` context reset too).

## 7. Optional — also clean up local Docker images

If you want disk space back too:
```bash
docker rmi demo-backend:local demo-frontend:local 2>/dev/null
docker image prune -f
```

---

**Once you run step 6, you're at a genuinely clean slate** — no cluster, no leftover state, nothing to conflict with a fresh start. When you're ready to rebuild, just start again from Part 2 of the guide (`kind create cluster --name demo`) and everything downstream will behave identically to a first-time run, no stale state to trip over this time.

Want me to also remove the `/etc/hosts` entry for `demo.local` from earlier, or leave that in place for next time?