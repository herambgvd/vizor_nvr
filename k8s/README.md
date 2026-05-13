# GVD NVR — Kubernetes Deployment

## Quick Start

```bash
# 1. Build and push images
export REGISTRY=your-registry.com/gvd-nvr
docker build -t $REGISTRY/backend:latest backend/
docker build -t $REGISTRY/frontend:latest frontend/
docker push $REGISTRY/backend:latest
docker push $REGISTRY/frontend:latest

# 2. Update image names in manifests (or use kustomize)
sed -i "s|gvd-nvr-backend:latest|$REGISTRY/backend:latest|g" k8s/backend-deployment.yaml
sed -i "s|gvd-nvr-frontend:latest|$REGISTRY/frontend:latest|g" k8s/frontend-deployment.yaml

# 3. Update secrets
vim k8s/secret.yaml  # set JWT_SECRET_KEY, DB_PASSWORD

# 4. Apply manifests
kubectl apply -f k8s/namespace.yaml
kubectl apply -f k8s/secret.yaml
kubectl apply -f k8s/configmap.yaml
kubectl apply -f k8s/storage-pvc.yaml
kubectl apply -f k8s/postgres-deployment.yaml
kubectl apply -f k8s/go2rtc-daemonset.yaml
kubectl apply -f k8s/backend-deployment.yaml
kubectl apply -f k8s/frontend-deployment.yaml
kubectl apply -f k8s/ingress.yaml

# 5. Wait for rollout
kubectl rollout status deployment/gvd-backend -n gvd-nvr
kubectl rollout status deployment/gvd-frontend -n gvd-nvr
```

## Architecture Notes

- **go2rtc** runs as a `DaemonSet` with `hostNetwork: true` so it can do RTSP multicast and WS-Discovery on the LAN.
- **Backend** runs as a single-replica `Deployment` (stateful — manages FFmpeg processes). Do not scale beyond 1 unless you redesign FFmpeg management.
- **Frontend** can scale to multiple replicas (stateless SPA).
- **Ingress** routes `/api` and `/onvif` to backend, everything else to frontend.
- **Storage** uses PVCs. In production use a StorageClass backed by fast SSD/NVMe.

## Scaling for Camera Count

| Cameras | Backend Memory | Backend CPU | Storage Class |
|---------|---------------|-------------|---------------|
| 16      | 2 Gi          | 1 core      | standard      |
| 32      | 4 Gi          | 2 cores     | fast SSD      |
| 64      | 8 Gi          | 4 cores     | NVMe          |
| 128     | 16 Gi         | 8 cores     | NVMe + tiered |

## go2rtc in Kubernetes

Because go2rtc uses `hostNetwork`, the backend must reach it via the node IP:
```
GO2RTC_URL=http://<node-ip>:1984
```

If running in cloud K8s where hostNetwork is problematic, consider:
1. Running go2rtc on a dedicated VM outside K8s
2. Using a LoadBalancer Service for go2rtc with `externalTrafficPolicy: Local`
