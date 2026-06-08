from datetime import datetime
from backend.db import SessionLocal
from backend.models import LogEntry, MetricRollup

def parse_and_rollup_log(log_id: int):
    """
    Background worker task to process an ingested log entry and update the
    MetricRollup table for time-series charts. Creates its own DB session
    to prevent context issues in async environments.
    """
    db = SessionLocal()
    try:
        log = db.query(LogEntry).filter(LogEntry.id == log_id).first()
        if not log:
            return

        # Truncate timestamp to the minute for rollup bucketing
        ts = log.timestamp
        minute_bucket = ts.replace(second=0, microsecond=0)

        # Check if a rollup already exists for this service and minute bucket
        rollup = db.query(MetricRollup).filter(
            MetricRollup.service == log.service,
            MetricRollup.timestamp == minute_bucket
        ).first()

        # Extract latency if available in details
        latency = 0.0
        if log.details and isinstance(log.details, dict):
            latency = float(log.details.get("latency_ms", 0.0))

        is_error = log.level in ("ERROR", "CRITICAL")
        # Also check if status_code indicates server error
        if log.details and isinstance(log.details, dict):
            status_code = log.details.get("status_code")
            if status_code and isinstance(status_code, int) and status_code >= 500:
                is_error = True

        if rollup:
            # Update existing rollup
            old_count = rollup.request_count
            new_count = old_count + 1
            rollup.request_count = new_count
            
            if is_error:
                rollup.error_count += 1
                
            # Update moving average latency
            if latency > 0.0:
                rollup.avg_latency_ms = (
                    (rollup.avg_latency_ms * old_count) + latency
                ) / new_count
        else:
            # Create new rollup bucket
            rollup = MetricRollup(
                timestamp=minute_bucket,
                service=log.service,
                request_count=1,
                error_count=1 if is_error else 0,
                avg_latency_ms=latency
            )
            db.add(rollup)

        db.commit()

        # Trigger anomaly detection (Phase 3 integration hook)
        try:
            from backend.detector import check_anomaly
            check_anomaly(db, log.service, minute_bucket)
        except ImportError:
            # Detector not implemented yet in Phase 2
            pass
        except Exception as e:
            # Log failure but don't break the rollup commit
            print(f"Error executing anomaly detector: {e}")
            
    finally:
        db.close()
