// Watchtower AI Dashboard Interactivity Logic

// Global Chart References
let throughputChart = null;
let errorsChart = null;

// Global Alert State
let selectedAlertId = null;
let alertsList = [];

// Initialize Dashboard
document.addEventListener("DOMContentLoaded", () => {
    initCharts();
    setupEventListeners();
    
    // Initial Polls
    pollData();
    pollWebhookConfigs();
    
    // Auto-register local webhook receiver for easy testing
    autoRegisterLocalWebhook();

    // Start Polling Loops
    setInterval(pollData, 3000);
});

// Auto-register local mock endpoint
function autoRegisterLocalWebhook() {
    fetch("/api/v1/webhooks", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
            name: "Local Webhook Receiver (Sandbox)",
            url: "http://127.0.0.1:8000/api/v1/test-webhook-receiver",
            is_active: true
        })
    })
    .then(r => r.json())
    .then(() => pollWebhookConfigs())
    .catch(err => console.log("Auto-registration deferred:", err));
}

// Chart Initializations
function initCharts() {
    const chartConfig = {
        chart: {
            height: 320,
            type: 'area',
            background: 'transparent',
            toolbar: { show: false },
            foreColor: '#94a3b8'
        },
        colors: ['#8B5CF6', '#06B6D4', '#F59E0B'],
        dataLabels: { enabled: false },
        stroke: { curve: 'smooth', width: 2 },
        grid: {
            borderColor: '#1e293b',
            strokeDashArray: 4,
            xaxis: { lines: { show: false } },
            yaxis: { lines: { show: true } }
        },
        xaxis: {
            type: 'datetime',
            labels: {
                datetimeUTC: false,
                style: { colors: '#94a3b8' }
            }
        },
        yaxis: {
            labels: {
                style: { colors: '#94a3b8' }
            }
        },
        tooltip: {
            theme: 'dark',
            x: { format: 'HH:mm:ss' }
        },
        legend: {
            position: 'top',
            horizontalAlign: 'right',
            labels: { colors: '#94a3b8' }
        },
        series: []
    };

    // 1. Throughput Chart Config
    const throughputOptions = JSON.parse(JSON.stringify(chartConfig));
    throughputOptions.chart.type = 'area';
    throughputOptions.yaxis.title = { text: 'Requests/min', style: { color: '#94a3b8' } };
    throughputChart = new ApexCharts(document.querySelector("#throughput-chart"), throughputOptions);
    throughputChart.render();

    // 2. Errors Chart Config
    const errorsOptions = JSON.parse(JSON.stringify(chartConfig));
    errorsOptions.chart.type = 'bar';
    errorsOptions.yaxis.title = { text: 'Error Count', style: { color: '#94a3b8' } };
    errorsOptions.plotOptions = {
        bar: {
            columnWidth: '50%',
            borderRadius: 4
        }
    };
    errorsChart = new ApexCharts(document.querySelector("#errors-chart"), errorsOptions);
    errorsChart.render();
}

// Setup Event Listeners
function setupEventListeners() {
    // Resolve Alert button action
    document.getElementById("resolve-alert-btn").addEventListener("click", () => {
        if (!selectedAlertId) return;
        fetch(`/api/v1/alerts/${selectedAlertId}/resolve`, {
            method: "POST"
        })
        .then(res => {
            if (!res.ok) throw new Error("Could not resolve alert");
            return res.json();
        })
        .then(() => {
            selectedAlertId = null;
            resetDetailPanel();
            pollData();
        })
        .catch(err => alert(err.message));
    });

    // Webhook settings creation
    document.getElementById("webhook-form").addEventListener("submit", (e) => {
        e.preventDefault();
        const name = document.getElementById("webhook-name").value;
        const url = document.getElementById("webhook-url").value;

        fetch("/api/v1/webhooks", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ name, url, is_active: true })
        })
        .then(res => {
            if (!res.ok) throw new Error("Registration failed");
            return res.json();
        })
        .then(() => {
            document.getElementById("webhook-name").value = "";
            document.getElementById("webhook-url").value = "";
            pollWebhookConfigs();
        })
        .catch(err => alert(err.message));
    });
}

// Master Polling Loop
function pollData() {
    updateSummary();
    updateCharts();
    updateAlerts();
    updateLogs();
    updateSimulatedWebhooks();
}

// Stats Cards Update
function updateSummary() {
    fetch("/api/v1/metrics/summary")
        .then(res => res.json())
        .then(data => {
            document.getElementById("stat-active-alerts").innerText = data.active_alerts_count;
            document.getElementById("stat-total-logs").innerText = data.total_logs_processed;
            document.getElementById("stat-active-services").innerText = data.services.length;

            // System Average Latency Calculation
            let totalLatency = 0;
            data.services.forEach(s => totalLatency += s.avg_latency_ms);
            const avgLatency = data.services.length > 0 ? (totalLatency / data.services.length).toFixed(1) : 0;
            document.getElementById("stat-avg-latency").innerHTML = `${avgLatency}<span class="text-xs text-slate-500 font-normal"> ms</span>`;

            // System badge color and pulse
            const badge = document.getElementById("system-health-badge");
            if (data.active_alerts_count > 0) {
                badge.className = "flex items-center gap-2 px-3.5 py-1.5 rounded-full bg-neon-red/10 border border-neon-red/20 text-neon-red text-xs font-semibold tracking-wide";
                badge.innerHTML = `
                    <span class="relative flex h-2 w-2">
                        <span class="animate-ping absolute inline-flex h-full w-full rounded-full bg-neon-red opacity-75"></span>
                        <span class="relative inline-flex rounded-full h-2 w-2 bg-neon-red"></span>
                    </span>
                    CRITICAL ALERTS ACTIVE
                `;
            } else {
                badge.className = "flex items-center gap-2 px-3.5 py-1.5 rounded-full bg-neon-green/10 border border-neon-green/20 text-neon-green text-xs font-semibold tracking-wide";
                badge.innerHTML = `
                    <span class="relative flex h-2 w-2">
                        <span class="animate-ping absolute inline-flex h-full w-full rounded-full bg-neon-green opacity-75"></span>
                        <span class="relative inline-flex rounded-full h-2 w-2 bg-neon-green"></span>
                    </span>
                    SYSTEM HEALTHY
                `;
            }
        })
        .catch(err => console.error("Summary fetch failed:", err));
}

// Chart Series Update
function updateCharts() {
    fetch("/api/v1/metrics/series")
        .then(res => res.json())
        .then(seriesData => {
            const reqSeries = [];
            const errSeries = [];

            seriesData.forEach(srv => {
                const reqPoints = srv.points.map(pt => ({
                    x: new Date(pt.timestamp).getTime(),
                    y: pt.request_count
                }));
                const errPoints = srv.points.map(pt => ({
                    x: new Date(pt.timestamp).getTime(),
                    y: pt.error_count
                }));

                reqSeries.push({ name: srv.service, data: reqPoints });
                errSeries.push({ name: srv.service, data: errPoints });
            });

            throughputChart.updateSeries(reqSeries);
            errorsChart.updateSeries(errSeries);
        })
        .catch(err => console.error("Charts fetch failed:", err));
}

// Alerts / Anomalies list update
function updateAlerts() {
    fetch("/api/v1/alerts")
        .then(res => res.json())
        .then(data => {
            alertsList = data;
            
            const badge = document.getElementById("alerts-count-badge");
            badge.innerText = data.filter(a => a.status === 'Active').length;

            const container = document.getElementById("alerts-list-container");
            if (data.length === 0) {
                container.innerHTML = `<div class="text-slate-500 text-xs text-center py-12">No anomalies detected. System is running cleanly.</div>`;
                return;
            }

            container.innerHTML = "";
            data.forEach(alert => {
                const isActive = alert.status === "Active";
                const borderClass = isActive ? "border-neon-red/35" : "border-slate-800/80";
                const bgClass = isActive ? "bg-neon-red/5" : "bg-slate-900/20";
                const badgeClass = isActive ? "bg-neon-red/10 text-neon-red border-neon-red/20" : "bg-slate-800 text-slate-400 border-slate-700/60";
                
                const alertCard = document.createElement("div");
                alertCard.className = `p-4 border ${borderClass} ${bgClass} rounded-xl cursor-pointer hover:bg-slate-900/40 transition duration-150`;
                alertCard.onclick = () => selectAlert(alert.id);
                alertCard.innerHTML = `
                    <div class="flex items-center justify-between">
                        <span class="text-[10px] font-bold uppercase px-2 py-0.5 rounded border ${badgeClass}">
                            ${alert.severity}
                        </span>
                        <span class="text-[10px] text-slate-500">
                            ${new Date(alert.timestamp).toLocaleTimeString()}
                        </span>
                    </div>
                    <h5 class="text-xs font-bold text-slate-200 mt-2">${alert.title}</h5>
                    <p class="text-[10px] text-slate-500 truncate mt-1">${alert.description}</p>
                `;
                container.appendChild(alertCard);
            });

            // If we have an active selection, refresh the detail panel view
            if (selectedAlertId) {
                const refreshedSelected = data.find(a => a.id === selectedAlertId);
                if (refreshedSelected) {
                    renderDetailPanel(refreshedSelected);
                }
            }
        })
        .catch(err => console.error("Alerts fetch failed:", err));
}

// Select specific alert for detail pane
function selectAlert(id) {
    selectedAlertId = id;
    const alert = alertsList.find(a => a.id === id);
    if (alert) {
        renderDetailPanel(alert);
    }
}

// Render detail pane
function renderDetailPanel(alert) {
    const isResolved = alert.status === "Resolved";
    
    // Show severity badge
    const severityBadge = document.getElementById("detail-alert-severity");
    severityBadge.classList.remove("hidden");
    severityBadge.innerText = alert.status.toUpperCase();
    severityBadge.className = isResolved 
        ? "text-[10px] font-bold tracking-wider px-2 py-0.5 rounded-full border border-neon-green/30 bg-neon-green/10 text-neon-green"
        : "text-[10px] font-bold tracking-wider px-2 py-0.5 rounded-full border border-neon-red/30 bg-neon-red/10 text-neon-red animate-pulse";

    // Update Title & Description
    document.getElementById("detail-alert-title").innerText = alert.title;
    document.getElementById("detail-alert-desc").innerText = `${alert.description} | Service: ${alert.service} | Timestamp: ${new Date(alert.timestamp).toLocaleString()}`;

    // Show Resolve button only if it's active
    const btn = document.getElementById("resolve-alert-btn");
    if (!isResolved) {
        btn.classList.remove("hidden");
    } else {
        btn.classList.add("hidden");
    }

    // AI details mapping
    const aiPanels = document.getElementById("ai-detail-panels");
    aiPanels.classList.remove("hidden");
    
    const analysis = alert.ai_analysis || {
        root_cause: "Statistical baseline threshold exceeded.",
        impact: "Undetermined. Heuristic matching not available.",
        remediation: "No remediation steps suggested."
    };

    document.getElementById("detail-root-cause").innerText = analysis.root_cause;
    document.getElementById("detail-impact").innerText = analysis.impact;
    document.getElementById("detail-remediation").innerText = analysis.remediation;
}

// Reset detail pane
function resetDetailPanel() {
    document.getElementById("detail-alert-severity").classList.add("hidden");
    document.getElementById("detail-alert-title").innerText = "Select an Incident";
    document.getElementById("detail-alert-desc").innerText = "Select an incident from the logs list to inspect AI-assisted analysis and root-cause remediation details.";
    document.getElementById("resolve-alert-btn").classList.add("hidden");
    document.getElementById("ai-detail-panels").classList.add("hidden");
}

// Live Logs Viewer update
function updateLogs() {
    const query = document.getElementById("log-search").value;
    const level = document.getElementById("log-level-filter").value;

    let url = `/api/v1/logs?limit=30`;
    if (level) url += `&level=${level}`;

    fetch(url)
        .then(res => res.json())
        .then(logs => {
            const container = document.getElementById("live-logs-container");
            if (logs.length === 0) {
                container.innerHTML = `<div class="text-slate-600 text-center py-12">No matching telemetry logs.</div>`;
                return;
            }

            // Filter in-memory if free-text search is input
            let filteredLogs = logs;
            if (query) {
                const searchLower = query.toLowerCase();
                filteredLogs = logs.filter(l => 
                    l.message.toLowerCase().includes(searchLower) || 
                    l.service.toLowerCase().includes(searchLower)
                );
            }

            container.innerHTML = "";
            filteredLogs.forEach(log => {
                let colorClass = "text-slate-400";
                if (log.level === "ERROR") colorClass = "text-neon-orange";
                if (log.level === "CRITICAL") colorClass = "text-neon-red font-bold";
                if (log.level === "WARNING") colorClass = "text-yellow-400";

                const logLine = document.createElement("div");
                logLine.className = `py-1 border-b border-slate-900/50 flex items-start gap-2 ${colorClass}`;
                
                const timeStr = new Date(log.timestamp).toLocaleTimeString();
                logLine.innerHTML = `
                    <span class="text-slate-600 select-none">${timeStr}</span>
                    <span class="text-slate-500 select-none font-semibold">[${log.service}]</span>
                    <span class="select-none font-bold">${log.level}:</span>
                    <span>${log.message}</span>
                `;
                container.appendChild(logLine);
            });
        })
        .catch(err => console.error("Logs fetch failed:", err));
}

// Trigger simulation spike
function triggerSimulationSpike(service) {
    const statusBadge = document.getElementById("system-health-badge");
    statusBadge.innerHTML = `
        <span class="relative flex h-2 w-2">
            <span class="animate-ping absolute inline-flex h-full w-full rounded-full bg-neon-orange opacity-75"></span>
            <span class="relative inline-flex rounded-full h-2 w-2 bg-neon-orange"></span>
        </span>
        INJECTING SPIKE ERROR TELEMETRY...
    `;
    statusBadge.className = "flex items-center gap-2 px-3.5 py-1.5 rounded-full bg-neon-orange/10 border border-neon-orange/20 text-neon-orange text-xs font-semibold tracking-wide";

    fetch(`/api/v1/simulation/spike?service=${service}`, {
        method: "POST"
    })
    .then(res => res.json())
    .then(data => {
        console.log("Spike response:", data);
        setTimeout(pollData, 1000); // refresh panel data
    })
    .catch(err => alert("Spike injection error: " + err.message));
}

// Fetch webhook list inside configuration modal
function pollWebhookConfigs() {
    fetch("/api/v1/webhooks")
        .then(res => res.json())
        .then(configs => {
            const container = document.getElementById("configured-webhooks-container");
            if (configs.length === 0) {
                container.innerHTML = `<div class="text-slate-600 text-xs py-4 text-center">No webhook configs registered. Add one above.</div>`;
                return;
            }

            container.innerHTML = "";
            configs.forEach(config => {
                const configRow = document.createElement("div");
                configRow.className = "flex justify-between items-center bg-slate-900/60 border border-slate-800 rounded-xl px-4 py-2 text-xs";
                configRow.innerHTML = `
                    <div class="truncate pr-4">
                        <span class="font-bold text-slate-300 block">${config.name}</span>
                        <span class="text-[10px] text-slate-500 font-mono block truncate max-w-[320px]">${config.url}</span>
                    </div>
                    <button onclick="deleteWebhook(${config.id})" class="px-2.5 py-1 bg-neon-red/10 border border-neon-red/20 text-neon-red rounded-lg hover:bg-neon-red/20 text-[10px] font-semibold transition">
                        Delete
                    </button>
                `;
                container.appendChild(configRow);
            });
        })
        .catch(err => console.error("Configs fetch failed:", err));
}

// Delete webhook config
function deleteWebhook(id) {
    if (!confirm("Are you sure you want to delete this webhook target?")) return;
    fetch(`/api/v1/webhooks/${id}`, {
        method: "DELETE"
    })
    .then(() => pollWebhookConfigs())
    .catch(err => alert(err.message));
}

// Update local webhook deliveries test pane
function updateSimulatedWebhooks() {
    fetch("/api/v1/test-webhook-receiver")
        .then(res => res.json())
        .then(deliveries => {
            const container = document.getElementById("webhook-receiver-container");
            if (deliveries.length === 0) {
                container.innerHTML = `<div class="text-slate-600 text-xs text-center py-12">Waiting for webhook payloads...</div>`;
                return;
            }

            // Show logs in reverse order (newest first)
            const reversedDeliveries = [...deliveries].reverse();

            container.innerHTML = "";
            reversedDeliveries.forEach(del => {
                const item = document.createElement("div");
                item.className = "p-3 bg-slate-900 border border-slate-850 rounded-xl space-y-2 text-[10px]";
                
                const timeStr = new Date(del.received_at).toLocaleTimeString();
                const alertInfo = del.payload.alert;
                
                item.innerHTML = `
                    <div class="flex justify-between items-center border-b border-slate-800 pb-1.5">
                        <span class="text-neon-cyan font-bold">POST Receiver Endpoint</span>
                        <span class="text-slate-500 font-medium">${timeStr}</span>
                    </div>
                    <div class="space-y-1 font-mono text-[9px] text-slate-400">
                        <div><span class="text-slate-500">Service:</span> ${alertInfo.service}</div>
                        <div><span class="text-slate-500">Alert:</span> ${alertInfo.title}</div>
                        <div><span class="text-slate-500">Severity:</span> <span class="text-neon-red font-bold">${alertInfo.severity}</span></div>
                        <div class="bg-slate-950 p-1.5 border border-slate-900 rounded select-all max-h-[100px] overflow-y-auto mt-1 leading-relaxed">
                            ${JSON.stringify(del.payload, null, 2)}
                        </div>
                    </div>
                `;
                container.appendChild(item);
            });
        })
        .catch(err => console.error("Mock receiver fetch failed:", err));
}
