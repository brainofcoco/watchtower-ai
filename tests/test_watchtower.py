import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from backend.db import Base, get_db
from backend.main import app
# Import all models to ensure they register on Base.metadata
from backend.models import LogEntry, MetricRollup, Alert, WebhookConfig, WebhookDelivery

# Create in-memory database with StaticPool to keep connection open across sessions
TEST_DATABASE_URL = "sqlite:///:memory:"
engine = create_engine(
    TEST_DATABASE_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Re-create schemas on test run
Base.metadata.create_all(bind=engine)

def override_get_db():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()

app.dependency_overrides[get_db] = override_get_db

client = TestClient(app)

@pytest.fixture(autouse=True)
def clean_db():
    """Truncate tables before each test to ensure a clean slate."""
    db = TestingSessionLocal()
    db.query(LogEntry).delete()
    db.query(MetricRollup).delete()
    db.query(Alert).delete()
    db.query(WebhookConfig).delete()
    db.query(WebhookDelivery).delete()
    db.commit()
    db.close()

def test_health_check():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "healthy", "service": "watchtower-ai"}

def test_ingest_log():
    payload = {
        "service": "test-service",
        "level": "INFO",
        "message": "User login completed successfully",
        "details": {"user_id": 42, "latency_ms": 45.5}
    }
    response = client.post("/api/v1/ingest", json=payload)
    assert response.status_code == 201
    
    data = response.json()
    assert data["service"] == "test-service"
    assert data["level"] == "INFO"
    assert data["message"] == "User login completed successfully"
    assert data["details"]["user_id"] == 42
    assert "id" in data

def test_query_logs():
    # Ingest standard logs
    client.post("/api/v1/ingest", json={"service": "auth-service", "level": "INFO", "message": "auth log"})
    client.post("/api/v1/ingest", json={"service": "user-service", "level": "ERROR", "message": "user failure"})
    
    response = client.get("/api/v1/logs")
    assert response.status_code == 200
    logs = response.json()
    assert len(logs) == 2

    # Test filtering by service
    response = client.get("/api/v1/logs?service=auth-service")
    logs = response.json()
    assert len(logs) == 1
    assert logs[0]["service"] == "auth-service"

    # Test filtering by level
    response = client.get("/api/v1/logs?level=ERROR")
    logs = response.json()
    assert len(logs) == 1
    assert logs[0]["level"] == "ERROR"

def test_webhook_crud():
    payload = {
        "name": "Production Slack Alerts",
        "url": "http://127.0.0.1:8000/api/v1/test-webhook-receiver"
    }
    
    # Create Webhook Target
    response = client.post("/api/v1/webhooks", json=payload)
    assert response.status_code == 201
    data = response.json()
    assert data["name"] == "Production Slack Alerts"
    assert data["url"] == "http://127.0.0.1:8000/api/v1/test-webhook-receiver"
    webhook_id = data["id"]

    # Get Webhooks List
    response = client.get("/api/v1/webhooks")
    assert response.status_code == 200
    assert len(response.json()) == 1

    # Delete Webhook Config
    response = client.delete(f"/api/v1/webhooks/{webhook_id}")
    assert response.status_code == 204
    
    # Verify Deleted
    response = client.get("/api/v1/webhooks")
    assert len(response.json()) == 0

def test_alerts_resolution():
    # Insert a mock active alert
    db = TestingSessionLocal()
    alert = Alert(
        service="user-service",
        title="Error spike detected in user-service",
        description="Statistical threshold breach",
        severity="WARNING",
        status="Active",
        ai_analysis={"root_cause": "Timeout", "impact": "None", "remediation": "Check DB"}
    )
    db.add(alert)
    db.commit()
    db.refresh(alert)
    alert_id = alert.id
    db.close()

    # Verify active alert list
    response = client.get("/api/v1/alerts")
    assert len(response.json()) == 1
    assert response.json()[0]["status"] == "Active"

    # Resolve alert
    response = client.post(f"/api/v1/alerts/{alert_id}/resolve")
    assert response.status_code == 200
    assert response.json()["status"] == "Resolved"

    # Verify is resolved in database list
    response = client.get("/api/v1/alerts")
    assert response.json()[0]["status"] == "Resolved"
