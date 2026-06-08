#!/usr/bin/env python3
import time
import random
import httpx
import sys
import argparse
from datetime import datetime, timezone

API_URL = "http://127.0.0.1:8000/api/v1/ingest"

SERVICES = {
    "frontend-gateway": {
        "paths": ["/index.html", "/api/v1/dashboard", "/assets/app.js", "/health"],
        "latencies": (10, 80),
        "error_rate": 0.02
    },
    "user-service": {
        "paths": ["/api/v1/login", "/api/v1/profile", "/api/v1/register"],
        "latencies": (30, 200),
        "error_rate": 0.05
    },
    "payment-service": {
        "paths": ["/api/v1/charge", "/api/v1/refund", "/api/v1/methods"],
        "latencies": (150, 800),
        "error_rate": 0.08
    }
}

def send_log(service: str, level: str, message: str, status_code: int, latency_ms: float):
    payload = {
        "service": service,
        "level": level,
        "message": message,
        "details": {
            "status_code": status_code,
            "latency_ms": latency_ms,
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
    }
    try:
        response = httpx.post(API_URL, json=payload, timeout=2.0)
        if response.status_code == 201:
            print(f"[{level}] {service} - {message} ({status_code} | {latency_ms:.1f}ms) - Ingested")
        else:
            print(f"Failed to ingest: {response.status_code} - {response.text}")
    except Exception as e:
        print(f"Connection error: {e}. Is the Watchtower API running?")

def simulate_normal():
    print("Starting Watchtower AI Log Simulator (Normal Mode). Press Ctrl+C to stop.")
    while True:
        # Choose a random service
        service = random.choice(list(SERVICES.keys()))
        config = SERVICES[service]
        
        path = random.choice(config["paths"])
        method = "GET" if path not in ["/api/v1/login", "/api/v1/register", "/api/v1/charge"] else "POST"
        
        # Decide if this is an error request based on error rate
        is_error = random.random() < config["error_rate"]
        
        if is_error:
            # We can have a client error or a server error
            status_code = random.choice([400, 401, 403, 500, 503])
            level = "ERROR" if status_code >= 500 else "WARNING"
            message = f"{method} {path} failed - {status_code} Internal Server Error" if status_code >= 500 else f"{method} {path} - Unauthorized client request"
            latency = random.uniform(config["latencies"][0] * 1.5, config["latencies"][1] * 2.0)
        else:
            status_code = 200 if random.random() < 0.9 else 201
            level = "INFO"
            message = f"{method} {path} - {status_code} OK"
            latency = random.uniform(*config["latencies"])

        send_log(service, level, message, status_code, latency)
        time.sleep(random.uniform(0.2, 1.5))

def simulate_spike(service: str, count: int = 50):
    print(f"Simulating a CRITICAL error spike on '{service}' ({count} requests)...")
    config = SERVICES.get(service, {"paths": ["/api/v1/critical"], "latencies": (500, 2000)})
    
    for i in range(count):
        path = random.choice(config["paths"])
        method = "POST"
        status_code = 500
        level = "CRITICAL"
        message = f"CRITICAL - Connection pool exhausted: database cluster lockup on {path}"
        latency = random.uniform(2000, 5000) # High latency during DB lockup
        
        send_log(service, level, message, status_code, latency)
        # Fast burst of errors
        time.sleep(0.05)
    print("Spike simulation complete!")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Watchtower AI Log Simulator")
    parser.add_argument("--spike", type=str, choices=list(SERVICES.keys()), help="Simulate a major error spike on the specified service and exit.")
    parser.add_argument("--count", type=int, default=50, help="Number of error requests in spike mode.")
    args = parser.parse_args()

    if args.spike:
        simulate_spike(args.spike, args.count)
    else:
        simulate_normal()
