from datetime import datetime, timezone
from sqlalchemy import Column, Integer, String, DateTime, Boolean, JSON, ForeignKey, Float
from sqlalchemy.orm import relationship
from backend.db import Base

def utcnow_naive():
    return datetime.now(timezone.utc).replace(tzinfo=None)

class LogEntry(Base):
    __tablename__ = "log_entries"

    id = Column(Integer, primary_key=True, index=True)
    timestamp = Column(DateTime, default=utcnow_naive, index=True)
    service = Column(String, index=True)
    level = Column(String, index=True) # INFO, WARNING, ERROR, CRITICAL
    message = Column(String)
    details = Column(JSON, nullable=True) # Extra metadata/stack trace

class MetricRollup(Base):
    __tablename__ = "metric_rollups"

    id = Column(Integer, primary_key=True, index=True)
    timestamp = Column(DateTime, index=True) # Truncated to the minute
    service = Column(String, index=True)
    request_count = Column(Integer, default=0)
    error_count = Column(Integer, default=0)
    avg_latency_ms = Column(Float, default=0.0)

class Alert(Base):
    __tablename__ = "alerts"

    id = Column(Integer, primary_key=True, index=True)
    timestamp = Column(DateTime, default=utcnow_naive, index=True)
    service = Column(String, index=True)
    title = Column(String)
    description = Column(String)
    severity = Column(String, index=True) # INFO, WARNING, CRITICAL
    status = Column(String, default="Active", index=True) # Active, Resolved
    ai_analysis = Column(JSON, nullable=True) # root cause, impact, remediation

    deliveries = relationship("WebhookDelivery", back_populates="alert", cascade="all, delete-orphan")

class WebhookConfig(Base):
    __tablename__ = "webhook_configs"

    id = Column(Integer, primary_key=True, index=True)
    url = Column(String, unique=True, index=True)
    name = Column(String)
    is_active = Column(Boolean, default=True)

    deliveries = relationship("WebhookDelivery", back_populates="webhook_config", cascade="all, delete-orphan")

class WebhookDelivery(Base):
    __tablename__ = "webhook_deliveries"

    id = Column(Integer, primary_key=True, index=True)
    alert_id = Column(Integer, ForeignKey("alerts.id", ondelete="CASCADE"), index=True)
    webhook_config_id = Column(Integer, ForeignKey("webhook_configs.id", ondelete="CASCADE"), index=True)
    timestamp = Column(DateTime, default=utcnow_naive, index=True)
    status_code = Column(Integer, nullable=True)
    success = Column(Boolean, default=False)
    response_body = Column(String, nullable=True)

    alert = relationship("Alert", back_populates="deliveries")
    webhook_config = relationship("WebhookConfig", back_populates="deliveries")
