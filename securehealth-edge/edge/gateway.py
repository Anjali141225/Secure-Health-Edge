"""
SecureHealth-Edge — Edge Gateway (V1)
=======================================
Stands in for "Sensors/Wearable -> Edge Gateway (anomaly detection)" from
the architecture slide. Simulates several patients' vitals, runs threshold-
based anomaly detection locally (the "fast, edge-side" detection promised
in the Objectives slide), then syncs every reading to the cloud service.

Usage:
    python gateway.py                      # default settings
    python gateway.py --cloud-url http://localhost:8000 --interval 2

Anomaly thresholds are intentionally simple (rule-based, not ML) for V1 —
see README.md "Roadmap" for where a real edge-AI model would slot in.
"""

import argparse
import random
import time
from dataclasses import dataclass, field
from typing import Optional

import requests

# --- Patients this gateway is responsible for -----------------------------
PATIENTS = ["patient-101", "patient-102", "patient-103"]

# --- Anomaly thresholds -----------------------------------------------------
HR_LOW, HR_HIGH = 45, 140
SPO2_LOW = 90
RESP_LOW, RESP_HIGH = 8, 30
FALL_PROBABILITY = 0.01           # chance per reading, per patient
ANOMALY_INJECT_PROBABILITY = 0.06  # chance to nudge a reading toward anomaly


@dataclass
class PatientState:
    heart_rate: float = field(default_factory=lambda: random.uniform(65, 85))
    spo2: float = field(default_factory=lambda: random.uniform(96, 99))
    resp_rate: float = field(default_factory=lambda: random.uniform(14, 18))

    def step(self) -> "PatientState":
        """Random-walk the vitals, occasionally nudging toward an anomaly
        so the demo actually produces alerts to look at."""
        inject = random.random() < ANOMALY_INJECT_PROBABILITY

        self.heart_rate += random.uniform(-3, 3) if not inject else random.choice([-1, 1]) * random.uniform(20, 45)
        self.spo2 += random.uniform(-0.4, 0.4) if not inject else -random.uniform(5, 10)
        self.resp_rate += random.uniform(-1, 1) if not inject else random.choice([-1, 1]) * random.uniform(8, 15)

        # keep values physically plausible
        self.heart_rate = max(30, min(200, self.heart_rate))
        self.spo2 = max(70, min(100, self.spo2))
        self.resp_rate = max(4, min(45, self.resp_rate))
        return self


def detect_anomaly(state: PatientState, fall: bool) -> Optional[str]:
    """Edge-side rule-based anomaly detection. Returns a reason string,
    or None if the reading looks normal."""
    reasons = []
    if fall:
        reasons.append("fall detected")
    if state.heart_rate < HR_LOW or state.heart_rate > HR_HIGH:
        reasons.append(f"heart rate {state.heart_rate:.0f} bpm out of range")
    if state.spo2 < SPO2_LOW:
        reasons.append(f"SpO2 {state.spo2:.0f}% below safe threshold")
    if state.resp_rate < RESP_LOW or state.resp_rate > RESP_HIGH:
        reasons.append(f"respiration rate {state.resp_rate:.0f}/min out of range")
    return "; ".join(reasons) if reasons else None


def run(cloud_url: str, interval: float, edge_node: str):
    states = {pid: PatientState() for pid in PATIENTS}
    print(f"[edge] {edge_node} online — {len(PATIENTS)} patients, "
          f"reporting to {cloud_url} every {interval}s")

    while True:
        for pid in PATIENTS:
            state = states[pid].step()
            fall = random.random() < FALL_PROBABILITY
            reason = detect_anomaly(state, fall)

            payload = {
                "patient_id": pid,
                "heart_rate": round(state.heart_rate, 1),
                "spo2": round(state.spo2, 1),
                "resp_rate": round(state.resp_rate, 1),
                "fall_detected": fall,
                "anomaly": reason is not None,
                "anomaly_reason": reason,
                "edge_node": edge_node,
            }

            try:
                resp = requests.post(f"{cloud_url}/ingest", json=payload, timeout=3)
                resp.raise_for_status()
                flag = "ALERT" if payload["anomaly"] else "ok"
                print(f"[edge] {pid}: HR={payload['heart_rate']} SpO2={payload['spo2']} "
                      f"RR={payload['resp_rate']} -> {flag}"
                      + (f" ({reason})" if reason else ""))
            except requests.RequestException as exc:
                print(f"[edge] failed to sync {pid} to cloud: {exc}")

        time.sleep(interval)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="SecureHealth-Edge gateway simulator")
    parser.add_argument("--cloud-url", default= "https://secure-health-edge.onrender.com")
    parser.add_argument("--interval", type=float, default=2.0, help="seconds between reading batches")
    parser.add_argument("--edge-node", default="edge-gateway-1")
    args = parser.parse_args()
    run(args.cloud_url, args.interval, args.edge_node)
