import httpx
from datetime import datetime, timezone
from backend.db import SessionLocal
from backend.models import Alert, WebhookConfig, WebhookDelivery

def dispatch_alert(alert_id: int):
    """
    Dispatches a JSON alert payload to all active webhooks, and records
    each delivery outcome in the WebhookDelivery table.
    """
    db = SessionLocal()
    try:
        alert = db.query(Alert).filter(Alert.id == alert_id).first()
        if not alert:
            return

        configs = db.query(WebhookConfig).filter(WebhookConfig.is_active == True).all()
        if not configs:
            print(f"[NOTIFIER] No active webhooks registered to receive alert {alert_id}")
            return

        # Prepare JSON payload
        payload = {
            "event": "alert.triggered",
            "alert": {
                "id": alert.id,
                "timestamp": alert.timestamp.isoformat(),
                "service": alert.service,
                "title": alert.title,
                "description": alert.description,
                "severity": alert.severity,
                "status": alert.status,
                "ai_analysis": alert.ai_analysis
            }
        }

        # Dispatch using a synchronous httpx Client
        with httpx.Client(timeout=5.0) as client:
            for config in configs:
                status_code = None
                success = False
                response_text = ""
                
                try:
                    print(f"[NOTIFIER] Sending alert {alert_id} webhook to {config.url}...")
                    response = client.post(config.url, json=payload)
                    status_code = response.status_code
                    response_text = response.text[:1000] # Cap output size
                    success = (200 <= status_code < 300)
                except Exception as e:
                    response_text = f"Network Error: {str(e)}"
                    print(f"[NOTIFIER] Webhook delivery failed for {config.url}: {e}")
                
                # Record delivery log
                delivery = WebhookDelivery(
                    alert_id=alert.id,
                    webhook_config_id=config.id,
                    timestamp=datetime.now(timezone.utc).replace(tzinfo=None),
                    status_code=status_code,
                    success=success,
                    response_body=response_text
                )
                db.add(delivery)
                
        db.commit()
    finally:
        db.close()
