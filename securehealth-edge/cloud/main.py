"""
SecureHealth-Edge — Cloud Service (V1)
========================================
Stands in for the "Cloud (Docker + Kubernetes)" + "Database (multi-cloud
storage)" layers from the architecture slide. In production this would be
split across AWS (EC2/S3/Lambda) and Firebase; here it's a single FastAPI
service backed by SQLite so the whole system runs without cloud credentials.

Endpoints:
    POST /ingest          — receive a vitals reading from an edge gateway
    GET  /patients         — latest known status of every patient
    GET  /patients/{id}    — latest reading for one patient
    GET  /history/{id}     — reading history for one patient
    GET  /alerts            — all triggered alerts, most recent first
    GET  /metrics           — Prometheus-style counters (stand-in for
                              the Grafana + Prometheus monitoring slide)
"""

import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

DB_PATH = Path(__file__).parent / "securehealth.db"

app = FastAPI(title="SecureHealth-Edge Cloud Service", version="1.0.0")

# Dashboard runs from file:// or a plain http.server on another port.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

_counters = {"ingested": 0, "alerts_triggered": 0}


@contextmanager
def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db():
    with get_db() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS readings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                patient_id TEXT NOT NULL,
                heart_rate REAL NOT NULL,
                spo2 REAL NOT NULL,
                resp_rate REAL NOT NULL,
                fall_detected INTEGER NOT NULL,
                anomaly INTEGER NOT NULL,
                anomaly_reason TEXT,
                edge_node TEXT,
                timestamp REAL NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS alerts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                patient_id TEXT NOT NULL,
                reason TEXT NOT NULL,
                reading_id INTEGER NOT NULL,
                timestamp REAL NOT NULL,
                acknowledged INTEGER DEFAULT 0
            )
            """
        )


@app.on_event("startup")
def on_startup():
    init_db()


class Reading(BaseModel):
    patient_id: str
    heart_rate: float
    spo2: float
    resp_rate: float
    fall_detected: bool = False
    anomaly: bool = False
    anomaly_reason: Optional[str] = None
    edge_node: Optional[str] = "edge-gateway-1"


@app.post("/ingest")
def ingest(reading: Reading):
    """Receive a (already edge-screened) vitals reading and store it.

    If the edge gateway flagged it as anomalous, raise an alert — this is
    the stand-in for the AWS Lambda event-driven alert function.
    """
    ts = time.time()
    with get_db() as conn:
        cur = conn.execute(
            """INSERT INTO readings
               (patient_id, heart_rate, spo2, resp_rate, fall_detected,
                anomaly, anomaly_reason, edge_node, timestamp)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                reading.patient_id,
                reading.heart_rate,
                reading.spo2,
                reading.resp_rate,
                int(reading.fall_detected),
                int(reading.anomaly),
                reading.anomaly_reason,
                reading.edge_node,
                ts,
            ),
        )
        reading_id = cur.lastrowid
        _counters["ingested"] += 1

        if reading.anomaly:
            conn.execute(
                """INSERT INTO alerts (patient_id, reason, reading_id, timestamp)
                   VALUES (?, ?, ?, ?)""",
                (reading.patient_id, reading.anomaly_reason or "anomaly", reading_id, ts),
            )
            _counters["alerts_triggered"] += 1

    return {"status": "stored", "reading_id": reading_id, "alert_raised": reading.anomaly}


@app.get("/patients")
def list_patients():
    with get_db() as conn:
        rows = conn.execute(
            """
            SELECT r.* FROM readings r
            INNER JOIN (
                SELECT patient_id, MAX(timestamp) AS max_ts
                FROM readings GROUP BY patient_id
            ) latest
            ON r.patient_id = latest.patient_id AND r.timestamp = latest.max_ts
            ORDER BY r.patient_id
            """
        ).fetchall()
        return [dict(row) for row in rows]


@app.get("/patients/{patient_id}")
def get_patient(patient_id: str):
    with get_db() as conn:
        row = conn.execute(
            "SELECT * FROM readings WHERE patient_id = ? ORDER BY timestamp DESC LIMIT 1",
            (patient_id,),
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="No readings for this patient")
        return dict(row)


@app.get("/history/{patient_id}")
def get_history(patient_id: str, limit: int = 50):
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM readings WHERE patient_id = ? ORDER BY timestamp DESC LIMIT ?",
            (patient_id, limit),
        ).fetchall()
        return [dict(row) for row in rows]


@app.get("/alerts")
def list_alerts(limit: int = 50):
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM alerts ORDER BY timestamp DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(row) for row in rows]


@app.get("/metrics")
def metrics():
    """Plain-text counters in a Prometheus-friendly shape."""
    lines = [
        "# HELP securehealth_readings_ingested_total Total vitals readings ingested",
        "# TYPE securehealth_readings_ingested_total counter",
        f"securehealth_readings_ingested_total {_counters['ingested']}",
        "# HELP securehealth_alerts_triggered_total Total alerts raised",
        "# TYPE securehealth_alerts_triggered_total counter",
        f"securehealth_alerts_triggered_total {_counters['alerts_triggered']}",
    ]
    return "\n".join(lines)


@app.get("/health")
def health():
    return {"status": "ok"}
