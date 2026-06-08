from datetime import datetime
from pydantic import BaseModel, HttpUrl, ConfigDict
from typing import Optional, Dict, Any, List

# Log schemas
class LogCreate(BaseModel):
    service: str
    level: str # INFO, WARNING, ERROR, CRITICAL
    message: str
    timestamp: Optional[datetime] = None
    details: Optional[Dict[str, Any]] = None

class LogResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    timestamp: datetime
    service: str
    level: str
    message: str
    details: Optional[Dict[str, Any]] = None

# AI Analysis schema embedded in Alert
class AIAnalysis(BaseModel):
    root_cause: str
    impact: str
    remediation: str

# Alert schemas
class AlertResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    timestamp: datetime
    service: str
    title: str
    description: str
    severity: str
    status: str
    ai_analysis: Optional[Dict[str, Any]] = None

class AlertResolve(BaseModel):
    status: str = "Resolved"

# Webhook schemas
class WebhookConfigCreate(BaseModel):
    name: str
    url: str
    is_active: Optional[bool] = True

class WebhookConfigResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    url: str
    is_active: bool

class WebhookDeliveryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    alert_id: int
    webhook_config_id: int
    timestamp: datetime
    status_code: Optional[int] = None
    success: bool
    response_body: Optional[str] = None

# Metrics summary schemas
class ServiceMetricSummary(BaseModel):
    service: str
    request_count: int
    error_count: int
    error_rate: float
    avg_latency_ms: float

class SystemSummary(BaseModel):
    active_alerts_count: int
    total_logs_processed: int
    services: List[ServiceMetricSummary]

# Series data schema for charts
class MetricSeriesPoint(BaseModel):
    timestamp: datetime
    request_count: int
    error_count: int
    avg_latency_ms: float

class ServiceSeries(BaseModel):
    service: str
    points: List[MetricSeriesPoint]
