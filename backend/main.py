import os
from datetime import datetime, timedelta, timezone
from fastapi import FastAPI, Depends, HTTPException, BackgroundTasks, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session
from sqlalchemy import func, desc
from typing import List, Optional

from backend.db import engine, Base, get_db
from backend.models import LogEntry, MetricRollup, Alert, WebhookConfig, WebhookDelivery
from backend.schemas import (
    LogCreate, LogResponse, SystemSummary, ServiceMetricSummary, ServiceSeries,
    MetricSeriesPoint, AlertResponse, WebhookConfigCreate, WebhookConfigResponse,
    WebhookDeliveryResponse
)
from backend.worker import parse_and_rollup_log

# Initialize Database tables
Base.metadata.create_all(bind=engine)

app = FastAPI(
    title="Watchtower AI Engine",
    description="Intelligent Observability & Event Watchdog API",
    version="1.0.0"
)

# Enable CORS for local development
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# In-memory store for simulated webhook receiver logs
SIMULATED_WEBHOOK_RECEIVER_LOGS = []

# Basic Health check
@app.get("/health")
def health_check():
    return {"status": "healthy", "service": "watchtower-ai"}

# Log Ingestion endpoint
@app.post("/api/v1/ingest", response_model=LogResponse, status_code=201)
def ingest_log(log_in: LogCreate, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    """
    Ingests a raw application log, persists it, and schedules the background
    worker to update metrics and run anomaly checks.
    """
    db_log = LogEntry(
        service=log_in.service,
        level=log_in.level.upper(),
        message=log_in.message,
        timestamp=log_in.timestamp or datetime.now(timezone.utc).replace(tzinfo=None),
        details=log_in.details
    )
    db.add(db_log)
    db.commit()
    db.refresh(db_log)

    # Schedule the background worker task to process the log
    background_tasks.add_task(parse_and_rollup_log, db_log.id)

    return db_log

# Retrieve Logs endpoint
@app.get("/api/v1/logs", response_model=List[LogResponse])
def get_logs(
    service: Optional[str] = None,
    level: Optional[str] = None,
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db)
):
    """
    Returns lists of ingested logs with filtering and pagination.
    """
    query = db.query(LogEntry)
    if service:
        query = query.filter(LogEntry.service == service)
    if level:
        query = query.filter(func.upper(LogEntry.level) == level.upper())
    
    return query.order_by(LogEntry.timestamp.desc()).offset(offset).limit(limit).all()

# Metrics Summary endpoint for dashboard stats cards
@app.get("/api/v1/metrics/summary", response_model=SystemSummary)
def get_metrics_summary(db: Session = Depends(get_db)):
    """
    Fetches aggregate statistics for the dashboard cards: active alerts,
    total logs, and a summary per service.
    """
    active_alerts = db.query(Alert).filter(Alert.status == "Active").count()
    total_logs = db.query(LogEntry).count()

    # Query aggregates from MetricRollup
    service_aggregates = db.query(
        MetricRollup.service,
        func.sum(MetricRollup.request_count).label("reqs"),
        func.sum(MetricRollup.error_count).label("errs"),
        func.avg(MetricRollup.avg_latency_ms).label("latency")
    ).group_by(MetricRollup.service).all()

    services = []
    for service, reqs, errs, latency in service_aggregates:
        req_val = reqs or 0
        err_val = errs or 0
        lat_val = latency or 0.0
        error_rate = (err_val / req_val) * 100.0 if req_val > 0 else 0.0
        
        services.append(
            ServiceMetricSummary(
                service=service,
                request_count=req_val,
                error_count=err_val,
                error_rate=error_rate,
                avg_latency_ms=lat_val
            )
        )

    return SystemSummary(
        active_alerts_count=active_alerts,
        total_logs_processed=total_logs,
        services=services
    )

# Time Series Metrics endpoint for charts
@app.get("/api/v1/metrics/series", response_model=List[ServiceSeries])
def get_metrics_series(db: Session = Depends(get_db)):
    """
    Retrieves rolled-up time series data points for plotting line/bar charts on the dashboard.
    """
    # Fetch rollups from the database
    rollups = db.query(MetricRollup).order_by(MetricRollup.timestamp.asc()).all()

    # Group points by service name
    service_data = {}
    for r in rollups:
        if r.service not in service_data:
            service_data[r.service] = []
        service_data[r.service].append(
            MetricSeriesPoint(
                timestamp=r.timestamp,
                request_count=r.request_count,
                error_count=r.error_count,
                avg_latency_ms=r.avg_latency_ms
            )
        )

    return [
        ServiceSeries(service=name, points=pts)
        for name, pts in service_data.items()
    ]

# --- Alert Endpoints ---

@app.get("/api/v1/alerts", response_model=List[AlertResponse])
def get_alerts(status: Optional[str] = None, db: Session = Depends(get_db)):
    """
    Retrieves active and resolved anomalies.
    """
    query = db.query(Alert)
    if status:
        query = query.filter(Alert.status == status)
    return query.order_by(desc(Alert.timestamp)).all()

@app.post("/api/v1/alerts/{id}/resolve", response_model=AlertResponse)
def resolve_alert(id: int, db: Session = Depends(get_db)):
    """
    Acknowledge and mark an alert as resolved.
    """
    alert = db.query(Alert).filter(Alert.id == id).first()
    if not alert:
        raise HTTPException(status_code=404, detail="Alert not found")
    alert.status = "Resolved"
    db.commit()
    db.refresh(alert)
    return alert

# --- Webhook Configurations Endpoints ---

@app.post("/api/v1/webhooks", response_model=WebhookConfigResponse, status_code=201)
def create_webhook(config_in: WebhookConfigCreate, db: Session = Depends(get_db)):
    """
    Registers a new alert target webhook.
    """
    # Check if URL already registered
    existing = db.query(WebhookConfig).filter(WebhookConfig.url == config_in.url).first()
    if existing:
        existing.name = config_in.name
        existing.is_active = config_in.is_active
        db.commit()
        db.refresh(existing)
        return existing
        
    config = WebhookConfig(
        url=config_in.url,
        name=config_in.name,
        is_active=config_in.is_active
    )
    db.add(config)
    db.commit()
    db.refresh(config)
    return config

@app.get("/api/v1/webhooks", response_model=List[WebhookConfigResponse])
def get_webhooks(db: Session = Depends(get_db)):
    """
    Lists registered webhook targets.
    """
    return db.query(WebhookConfig).all()

@app.delete("/api/v1/webhooks/{id}", status_code=204)
def delete_webhook(id: int, db: Session = Depends(get_db)):
    """
    Removes a registered webhook target.
    """
    config = db.query(WebhookConfig).filter(WebhookConfig.id == id).first()
    if not config:
        raise HTTPException(status_code=404, detail="Webhook config not found")
    db.delete(config)
    db.commit()
    return

@app.get("/api/v1/webhooks/deliveries", response_model=List[WebhookDeliveryResponse])
def get_webhook_deliveries(limit: int = 50, db: Session = Depends(get_db)):
    """
    Lists webhook attempt histories.
    """
    return db.query(WebhookDelivery).order_by(desc(WebhookDelivery.timestamp)).limit(limit).all()

# --- Simulation Spike Endpoint ---

@app.post("/api/v1/simulation/spike")
def trigger_spike_endpoint(service: str, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    """
    Endpoint called by the dashboard to simulate an error spike directly.
    Generates a burst of CRITICAL error logs for a service in the database,
    which will immediately trigger rollups and anomaly alerts.
    """
    valid_services = ["frontend-gateway", "user-service", "payment-service"]
    if service not in valid_services:
        raise HTTPException(status_code=400, detail="Invalid service name")

    # Generate logs directly in the DB to feed the engine
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    # Create 5 minutes of low-traffic normal rollups as baseline if none exists
    for i in range(5, 0, -1):
        ts = now - timedelta(minutes=i)
        minute_bucket = ts.replace(second=0, microsecond=0)
        existing = db.query(MetricRollup).filter(
            MetricRollup.service == service,
            MetricRollup.timestamp == minute_bucket
        ).first()
        if not existing:
            db.add(MetricRollup(
                timestamp=minute_bucket,
                service=service,
                request_count=10,
                error_count=0,
                avg_latency_ms=50.0
            ))
    db.commit()

    # Now create the spike of raw error logs (30 error logs)
    for i in range(30):
        db_log = LogEntry(
            service=service,
            level="CRITICAL",
            # Add database-related or payment-related messages to test heuristics
            message=f"CRITICAL - Connection pool exhausted: database cluster lockup on /api/v1/transaction #{i}" if service == "payment-service" else f"CRITICAL - Out of memory in application memory heap on /api/v1/login #{i}",
            timestamp=now,
            details={"status_code": 500, "latency_ms": 3200.0 + (i * 10)}
        )
        db.add(db_log)
        db.commit()
        db.refresh(db_log)
        
        # Schedule worker to process the log
        background_tasks.add_task(parse_and_rollup_log, db_log.id)

    return {"status": "triggered", "service": service, "message": "30 critical error logs generated."}

# --- Simulated Webhook Receiver Endpoints ---

@app.post("/api/v1/test-webhook-receiver")
def receive_test_webhook(payload: dict):
    """
    Simulated webhook receiver endpoint. Receives incoming JSON payloads from the watchdog
    and saves them in memory to display on the dashboard verification pane.
    """
    SIMULATED_WEBHOOK_RECEIVER_LOGS.append({
        "received_at": datetime.now(timezone.utc).isoformat(),
        "payload": payload
    })
    # Keep logs bounded to 50 entries
    if len(SIMULATED_WEBHOOK_RECEIVER_LOGS) > 50:
        SIMULATED_WEBHOOK_RECEIVER_LOGS.pop(0)
    return {"status": "success", "message": "Alert received and logged"}

@app.get("/api/v1/test-webhook-receiver")
def get_received_webhooks():
    """
    Returns the list of alerts received by the simulated receiver.
    """
    return SIMULATED_WEBHOOK_RECEIVER_LOGS

# Ensure static directory exists
os.makedirs("static", exist_ok=True)

# Mount frontend static files
app.mount("/static", StaticFiles(directory="static"), name="static")
