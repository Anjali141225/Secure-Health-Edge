# SecureHealth-Edge — V1 Prototype

A working prototype of the architecture from the Review 1 deck: **Sensors/Wearable →
Edge Gateway (anomaly detection) → Cloud (Docker + Kubernetes) → Database
(multi-cloud storage) → Dashboard → Caregiver/Admin**.

This is **Version 1**: a fully runnable local stand-in for the multi-cloud design,
built so it works without AWS/Firebase credentials. It proves the data flow and
alerting logic end-to-end; Section [Roadmap](#roadmap-v1--v2) below maps each
piece to what a "real" cloud deployment (as pitched in the slides) would swap in.

## Architecture

```
edge/gateway.py  --(HTTP POST /ingest)-->  cloud/main.py (FastAPI)  --served to-->  dashboard/index.html
   simulates 3 patients'                     stores readings + alerts                caregiver-facing
   vitals, flags anomalies                   in SQLite, exposes REST API             live view, polls
   at the edge before sending                + a /metrics endpoint                    every 2s
```

| Slide concept | V1 implementation |
|---|---|
| Sensors / Wearable | Simulated vitals (heart rate, SpO2, respiration, fall) in `edge/gateway.py` |
| Edge Gateway (anomaly detection) | Rule-based thresholds run locally before syncing — see `detect_anomaly()` |
| Cloud (Docker + Kubernetes) | FastAPI service in `cloud/`, containerized via `docker/`, orchestrated via `k8s/` |
| Database (multi-cloud storage) | SQLite (`cloud/securehealth.db`) — stand-in for AWS S3 / Firebase |
| Dashboard | `dashboard/index.html`, polls the cloud API every 2s |
| AWS Lambda (event-driven alerts) | `/ingest` raises an alert row the moment `anomaly=true` |
| Grafana + Prometheus | `/metrics` endpoint in Prometheus text format |

## Running it locally (no Docker needed)

```bash
pip install -r requirements.txt

# terminal 1 — cloud service
uvicorn cloud.main:app --reload --port 8000

# terminal 2 — edge gateway (simulates 3 patients)
python edge/gateway.py --cloud-url http://localhost:8000 --interval 2

# terminal 3 — dashboard
cd dashboard && python -m http.server 8080
# open http://localhost:8080 in a browser
```

Watch the terminal running `gateway.py` — every so often it injects a bad reading
so you'll see an `ALERT` line and a red card appear on the dashboard.

## Running it with Docker Compose

```bash
cd docker
docker compose up --build
# cloud API:  http://localhost:8000
# dashboard:  http://localhost:8080
```

## Kubernetes (illustrative)

`k8s/cloud-deployment.yaml` defines a Deployment (2 replicas), a ClusterIP Service,
and a HorizontalPodAutoscaler for the cloud layer — this is what "auto-scaling
analytics using Kubernetes" from the Motivation slide looks like as actual config.
Build and push the `cloud` image first, then:

```bash
kubectl apply -f k8s/cloud-deployment.yaml
```

## API reference (cloud service)

| Endpoint | Method | Purpose |
|---|---|---|
| `/ingest` | POST | Edge gateway pushes a vitals reading |
| `/patients` | GET | Latest status of every patient |
| `/patients/{id}` | GET | Latest reading for one patient |
| `/history/{id}` | GET | Reading history for one patient |
| `/alerts` | GET | All triggered alerts, most recent first |
| `/metrics` | GET | Prometheus-style counters |
| `/health` | GET | Liveness check (used by the k8s readiness probe) |

## Roadmap (V1 → V2)

This V1 focuses on proving the pipeline works. For the next review, the natural
upgrades — matching the "Cloud Services Used" slide — are:

- Swap SQLite for real multi-cloud storage: AWS S3 for cold history, Firebase
  Realtime Database for live state.
- Deploy the cloud service to AWS EC2 behind an actual Kubernetes cluster
  (Minikube/K3s locally, EKS in production) instead of the illustrative manifest.
- Replace rule-based edge detection with a lightweight trained model (e.g. an
  Isolation Forest or small neural net) for the "AI-Driven" part of the title.
- Wire `/metrics` into real Prometheus + Grafana instances instead of a raw
  text endpoint.
- Add end-to-end encryption (TLS + at-rest encryption) for the "secure" claim
  in the Research Gap slide.
- Replace HTTP polling on the dashboard with WebSockets/Firebase listeners for
  true real-time push instead of a 2-second poll.
