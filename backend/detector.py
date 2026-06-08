import os
import json
from datetime import datetime, timedelta, timezone
from sqlalchemy import desc
from sqlalchemy.orm import Session
from backend.models import MetricRollup, LogEntry, Alert
from backend.notifier import dispatch_alert

# Statistical configuration
WINDOW_SIZE = 15 # minutes of history to check
Z_SCORE_THRESHOLD = 3.0
MIN_DATA_POINTS = 5 # Minimum rollups needed to calculate Z-score

def get_heuristic_analysis(service: str, logs: list) -> dict:
    """
    Analyzes error log messages and generates a realistic, detailed incident analysis
    when no LLM API key is present.
    """
    error_snippet = " ".join([l.message for l in logs]).lower()
    
    analysis = {
        "root_cause": "Detected a sudden statistical spike in application error rate.",
        "impact": "Users might experience service degradation, slow loading times, or API request failures.",
        "remediation": "Check service system metrics, inspect active database connections, and review recent deployment revisions."
    }

    if "database" in error_snippet or "db" in error_snippet or "connection pool" in error_snippet:
        analysis["root_cause"] = "Database connection pool exhaustion. Elevated latency and connection timeouts prevent backend handlers from processing transactions."
        analysis["impact"] = "All endpoints dependent on persistent storage are throwing HTTP 500 errors. Transaction drop-offs are imminent."
        analysis["remediation"] = "1. Scale connection pool size in backend configuration.\n2. Verify database server CPU utilization and active connections.\n3. Kill long-running or locked SQL transactions."
    elif "payment" in service or "charge" in error_snippet or "refund" in error_snippet:
        analysis["root_cause"] = "Gateway timeout during external payment processor handshake. Retries are failing due to rate limits or API outage at the provider."
        analysis["impact"] = "Checkout transactions are failing. Customers are unable to complete purchases, leading to direct revenue loss."
        analysis["remediation"] = "1. Check the official status page of the third-party payment gateway.\n2. Temporarily cache failed payments for background retry if idempotent.\n3. Route new requests to a secondary backup payment gateway."
    elif "gateway" in service or "timeout" in error_snippet or "499" in error_snippet:
        analysis["root_cause"] = "Frontend gateway failed to receive a timely response from upstream microservices, leading to HTTP 504 Gateway Timeouts."
        analysis["impact"] = "High latency or total blockage on incoming web traffic. Users are seeing blank loading states or connection failure alerts."
        analysis["remediation"] = "1. Restart upstream instances experiencing high memory pressure.\n2. Increase read timeouts in Nginx/Gateway configuration.\n3. Review memory usage and garbage collection frequency."

    return analysis

def analyze_with_openai(service: str, stats_context: str, log_snippet: str, model: str) -> dict:
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise ValueError("OpenAI API key is not configured.")
        
    from openai import OpenAI
    client = OpenAI(api_key=api_key)
    
    prompt = f"""
An anomaly has been detected on the service: '{service}'.
Statistical Context:
{stats_context}

Recent error logs from the service:
{log_snippet}

Perform an instant root-cause analysis. You MUST return your response as a valid JSON object with EXACTLY three keys:
1. "root_cause": (1-2 sentences explaining what specifically went wrong based on the logs)
2. "impact": (What is the impact on users/operations)
3. "remediation": (Numbered step-by-step instructions to mitigate/resolve this incident)

Do not wrap in any markdown format, return ONLY the raw JSON string.
"""
    response = client.chat.completions.create(
        model=model or "gpt-4o-mini",
        messages=[
            {"role": "system", "content": "You are a helpful SRE assistant that outputs structured JSON analysis."},
            {"role": "user", "content": prompt}
        ],
        temperature=0.2,
        response_format={"type": "json_object"}
    )
    return json.loads(response.choices[0].message.content)

def analyze_with_anthropic(service: str, stats_context: str, log_snippet: str, model: str) -> dict:
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        raise ValueError("Anthropic API key is not configured.")
        
    from anthropic import Anthropic
    client = Anthropic(api_key=api_key)
    
    prompt = f"""
An anomaly has been detected on the service: '{service}'.
Statistical Context:
{stats_context}

Recent error logs from the service:
{log_snippet}

Perform an instant root-cause analysis. You MUST return your response as a valid JSON object with EXACTLY three keys:
1. "root_cause": (1-2 sentences explaining what specifically went wrong based on the logs)
2. "impact": (What is the impact on users/operations)
3. "remediation": (Numbered step-by-step instructions to mitigate/resolve this incident)

Do not wrap in any markdown format, return ONLY the raw JSON string.
"""
    response = client.messages.create(
        model=model or "claude-3-5-sonnet-20240620",
        max_tokens=1000,
        temperature=0.2,
        system="You are an expert SRE Observability Agent that outputs structured JSON analysis.",
        messages=[
            {"role": "user", "content": prompt}
        ]
    )
    return json.loads(response.content[0].text)

def analyze_with_llm(service: str, stats_context: str, logs: list) -> dict:
    """
    Performs root-cause analysis based on stats context and log snippets
    using the configured AI provider. Falls back to mock heuristics on key missing or failure.
    """
    provider = os.getenv("LLM_PROVIDER")
    openai_key = os.getenv("OPENAI_API_KEY")
    anthropic_key = os.getenv("ANTHROPIC_API_KEY")
    
    # Auto-detect provider if not explicitly configured
    if not provider:
        if openai_key:
            provider = "openai"
        elif anthropic_key:
            provider = "anthropic"
        else:
            provider = "mock"
            
    provider = provider.lower()
    if provider == "mock":
        return get_heuristic_analysis(service, logs)
        
    # Prepare logs snippet
    log_lines = []
    for l in logs:
        log_lines.append(f"[{l.level}] {l.timestamp.isoformat()} - {l.message} (details: {l.details})")
    log_snippet = "\n".join(log_lines[-20:])
    
    model = os.getenv("AI_MODEL")
    
    try:
        if provider == "openai":
            return analyze_with_openai(service, stats_context, log_snippet, model)
        elif provider == "anthropic":
            return analyze_with_anthropic(service, stats_context, log_snippet, model)
        else:
            print(f"Unknown provider '{provider}', falling back to mock.")
    except Exception as e:
        print(f"AI Analysis using provider '{provider}' failed: {e}. Falling back to mock.")
        
    return get_heuristic_analysis(service, logs)

def check_anomaly(db: Session, service: str, current_timestamp: datetime):
    """
    Computes rolling error-rate statistical metrics. If a Z-score threshold
    is breached, it triggers an AI root-cause analysis and registers a new Alert.
    """
    # 1. Fetch current minute's rollup
    current_rollup = db.query(MetricRollup).filter(
        MetricRollup.service == service,
        MetricRollup.timestamp == current_timestamp
    ).first()
    
    if not current_rollup or current_rollup.request_count == 0:
        return
        
    current_error_rate = current_rollup.error_count / current_rollup.request_count
    
    # 2. Fetch history of rollups for calculating baseline (excluding current timestamp)
    history = db.query(MetricRollup).filter(
        MetricRollup.service == service,
        MetricRollup.timestamp < current_timestamp
    ).order_by(desc(MetricRollup.timestamp)).limit(WINDOW_SIZE).all()
    
    # If not enough history points, fallback to absolute spike threshold checks
    if len(history) < MIN_DATA_POINTS:
        # absolute check: error rate > 25% and at least 3 errors
        if current_error_rate > 0.25 and current_rollup.error_count >= 3:
            trigger_alert(db, service, current_rollup, "Baseline establishing: Simple threshold breach", current_error_rate)
        return
        
    # 3. Calculate mean and standard deviation of historical error rates
    rates = []
    for r in history:
        if r.request_count > 0:
            rates.append(r.error_count / r.request_count)
        else:
            rates.append(0.0)
            
    mean_rate = sum(rates) / len(rates)
    variance = sum((x - mean_rate) ** 2 for x in rates) / len(rates)
    std_dev = variance ** 0.5
    
    # Calculate Z-score
    if std_dev > 0:
        z_score = (current_error_rate - mean_rate) / std_dev
    else:
        z_score = 0.0 if current_error_rate == 0 else 3.5
        
    # 4. Check if Z-score threshold is breached
    if z_score >= Z_SCORE_THRESHOLD:
        # Prevent spam: check if there's an active alert created in the last 5 minutes for this service
        now_utc = datetime.now(timezone.utc).replace(tzinfo=None)
        recent_alert = db.query(Alert).filter(
            Alert.service == service,
            Alert.status == "Active",
            Alert.timestamp >= now_utc - timedelta(minutes=5)
        ).first()
        
        if not recent_alert:
            stats_context = f"Current error rate: {current_error_rate:.2%} (Mean baseline: {mean_rate:.2%}, StdDev: {std_dev:.4f}, Z-score: {z_score:.2f})"
            trigger_alert(db, service, current_rollup, stats_context, z_score)

def trigger_alert(db: Session, service: str, rollup: MetricRollup, stats_context: str, score: float):
    """
    Creates an alert record, triggers the AI root cause analysis, and dispatches webhook.
    """
    # Fetch recent logs (especially errors) to feed into the analyzer
    recent_errors = db.query(LogEntry).filter(
        LogEntry.service == service,
        LogEntry.level.in_(["ERROR", "CRITICAL"])
    ).order_by(desc(LogEntry.timestamp)).limit(10).all()
    
    # Fallback to general logs if no error logs found
    if not recent_errors:
        recent_errors = db.query(LogEntry).filter(
            LogEntry.service == service
        ).order_by(desc(LogEntry.timestamp)).limit(10).all()
        
    # Reverse to restore chronological order
    recent_errors.reverse()
    
    # Run analysis
    analysis = analyze_with_llm(service, stats_context, recent_errors)
    
    title = f"Error spike detected in {service}"
    description = f"Statistical anomaly breach! {stats_context}."
    
    alert = Alert(
        service=service,
        title=title,
        description=description,
        severity="CRITICAL" if score >= 4.0 else "WARNING",
        status="Active",
        ai_analysis=analysis
    )
    
    db.add(alert)
    db.commit()
    db.refresh(alert)
    
    print(f"[ALERT TRIGGERED] {title} - severity={alert.severity}")
    
    # Dispatch webhooks asynchronously
    try:
        dispatch_alert(alert.id)
    except Exception as e:
        print(f"Webhook dispatch failed: {e}")
