# make sure nothing stale is left running first
pkill -f "port-forward svc/backend-live" 2>/dev/null
lsof -i :8095 || echo "port free"

# start fresh
kubectl -n demo-dev port-forward svc/backend-live 8095:8000 &
sleep 2
while true; do curl -s http://localhost:8095/version; echo " <- $(date +%H:%M:%S)"; sleep 1; done
