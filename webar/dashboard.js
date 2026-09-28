/**
 * IRIS — Digital Twin Dashboard Controller
 * Core logic for WebSocket connection, data binding, and interactive controls.
 */

// ══════════════════════════════════════════════════
// GLOBALS
// ══════════════════════════════════════════════════

let ws = null;
let wsRetryDelay = 1000;
let currentState = {};
let detectionEvents = [];
let detectionStats = {
    CRACK: 0,
    TEAR: 0,
    SURFACE_DAMAGE: 0,
    SURFACE_WEAR: 0,
    SPLICE_GAP: 0,
    EDGE_DAMAGE: 0,
    FOREIGN_OBJECT: 0,
};
let cameraStream = null;
let cameraInterval = null;
// Live detection drawing & storage variables
let detectionOverlay = null;
let detectionCtx = null;
// Live detection recording variables
let liveRecording = false;
let liveSnapshots = [];


// ══════════════════════════════════════════════════
// TAB NAVIGATION
// ══════════════════════════════════════════════════

document.querySelectorAll('.nav-item[data-tab]').forEach(item => {
    item.addEventListener('click', () => {
        // Update nav
        document.querySelectorAll('.nav-item').forEach(n => n.classList.remove('active'));
        item.classList.add('active');

        // Update content
        const tabId = item.dataset.tab;
        document.querySelectorAll('.tab-content').forEach(t => t.classList.remove('active'));
        const target = document.getElementById('tab-' + tabId);
        if (target) target.classList.add('active');

        // Update breadcrumb
        document.getElementById('tabTitle').textContent = item.querySelector('span:nth-child(2)').textContent;

        // Auto-refresh reports archive if clicking Reports tab
        if (tabId === 'reports') {
            loadSavedReportsList();
            refreshReportPreview();
        }
    });
});

// ══════════════════════════════════════════════════
// WEBSOCKET CONNECTION
// ══════════════════════════════════════════════════

function connectWebSocket() {
    const protocol = location.protocol === 'https:' ? 'wss:' : 'ws:';
    const wsUrl = `${protocol}//${location.host}/ws/live`;

    ws = new WebSocket(wsUrl);

    ws.onopen = () => {
        console.log('🟢 WebSocket connected');
        wsRetryDelay = 1000;
        updateConnectionStatus(true);
    };

    ws.onmessage = (event) => {
        try {
            const data = JSON.parse(event.data);
            currentState = data;
            updateDashboard(data);
        } catch (e) {
            console.error('Parse error:', e);
        }
    };

    ws.onclose = () => {
        console.log('🔴 WebSocket disconnected, retrying...');
        updateConnectionStatus(false);
        setTimeout(connectWebSocket, wsRetryDelay);
        wsRetryDelay = Math.min(wsRetryDelay * 2, 10000);
    };

    ws.onerror = (err) => {
        console.error('WebSocket error:', err);
        ws.close();
    };
}

function updateConnectionStatus(connected) {
    const dot = document.getElementById('connectionDot');
    const label = document.getElementById('connectionStatus');
    const badge = document.getElementById('streamBadge');
    if (connected) {
        dot.style.background = 'var(--green)';
        label.textContent = 'Connected';
        badge.style.display = 'flex';
    } else {
        dot.style.background = 'var(--red)';
        label.textContent = 'Reconnecting...';
        badge.style.display = 'none';
    }
}

// ══════════════════════════════════════════════════
// DASHBOARD UPDATE
// ══════════════════════════════════════════════════

function updateDashboard(s) {
    // ── KPIs ──
    updateKPI('kpiHealth', s.health_score, '%', getHealthColor(s.health_score));
    updateKPI('kpiRUL', s.rul_hours, 'h');
    setText('kpiRULSource', `Source: ${s.rul_source}`);
    
    const advisoryEl = document.getElementById('kpiAdvisory');
    if (advisoryEl) {
        advisoryEl.textContent = (s.belt_advisory || 'NORMAL').replace(/_/g, ' ');
        advisoryEl.className = 'kpi-value';
        advisoryEl.style.fontSize = '16px';
        advisoryEl.style.color = getAdvisoryColor(s.belt_advisory);
    }
    setText('kpiAdvisoryMsg', s.belt_advisory_message || '');
    setText('kpiEvents', s.n_damage_events);
    setText('kpiSeverity', s.dominant_severity !== 'NONE' ? `Worst: ${s.dominant_severity}` : 'No active events');

    // ── Simulation badge ──
    const simBadge = document.getElementById('simBadge');
    if (simBadge) simBadge.style.display = s.simulation_mode ? 'flex' : 'none';

    // ── Live Monitor ──
    updateKPI('monHealth', s.health_score, '%', getHealthColor(s.health_score));
    setText('monFailProb', `Failure prob: ${(s.failure_probability * 100).toFixed(1)}%`);
    updateKPI('monRUL', s.rul_hours, 'h');
    setText('monRULCI', `CI: ${s.rul_ci_lower} – ${s.rul_ci_upper}h`);
    setText('monAnomaly', s.anomaly_score?.toFixed(3) || '0.000');
    setText('monSpeed', s.belt_speed_mps?.toFixed(2) || '3.15');

    // ── Gauges ──
    updateGauge('tempGauge', s.temperature_c || 35, 0, 100, 'tempValue', '°');
    updateGauge('vibGauge', s.vibration_mms || 3, 0, 30, 'vibValue', '');
    updateGauge('tensGauge', (s.tension_tight_N || 50000) / 1000, 0, 200, 'tensValue', 'kN');

    // Belt canvas
    updateBeltCanvas(s);
    setText('beltPosLabel', `Position: ${s.belt_position_m?.toFixed(1) || 0}m`);

    // ── Belt Health ──
    updateAdvisory(s);
    updateTensionSag(s);

    // ── Sensor Lifetime ──
    if (s.sensor_lifetimes) updateSensors(s.sensor_lifetimes);

    // ── AI Explainability ──
    if (s.shap_contributions) updateSHAP(s.shap_contributions);
    updateRULPanel(s);

    // ── Damage Log ──
    if (s.active_damage_events) updateDamageLog(s.active_damage_events);

    // ── Physics ──
    updatePhysics(s);

    // ── Detection feed from twin state ──
    if (s.active_damage_events && s.active_damage_events.length > 0) {
        const newEvents = s.active_damage_events.filter(e => 
            !detectionEvents.find(d => d.id === e.id)
        );
        newEvents.forEach(e => {
            detectionEvents.unshift(e);
            addDetectionToFeed(e);
            const type = e.type || e.class_name;
            if (type && detectionStats[type] !== undefined) {
                detectionStats[type]++;
            }
        });
        updateDetectionStats();
    }

    // ── Reports JSON ──
    const stateJson = document.getElementById('stateJson');
    if (stateJson && document.getElementById('tab-reports')?.classList.contains('active')) {
        stateJson.textContent = JSON.stringify(s, null, 2);
    }
}

// ══════════════════════════════════════════════════
// HELPERS
// ══════════════════════════════════════════════════

function setText(id, text) {
    const el = document.getElementById(id);
    if (el) el.textContent = text;
}

function updateKPI(id, value, suffix = '', color = null) {
    const el = document.getElementById(id);
    if (!el) return;
    
    const num = typeof value === 'number' ? value : parseFloat(value);
    if (isNaN(num)) {
        el.textContent = value + suffix;
    } else {
        el.textContent = (num >= 100 ? Math.round(num) : num.toFixed(1)) + suffix;
    }
    if (color) el.style.color = color;
}

function getHealthColor(h) {
    if (h >= 80) return 'var(--green)';
    if (h >= 60) return 'var(--amber)';
    if (h >= 40) return 'hsl(15, 80%, 55%)';
    return 'var(--red)';
}

function getAdvisoryColor(level) {
    const map = {
        'NORMAL': 'var(--green)',
        'PLAN_INSPECTION': 'var(--blue)',
        'SCHEDULE_REPLACEMENT': 'var(--amber)',
        'IMMEDIATE_REPLACEMENT': 'var(--red)',
    };
    return map[level] || 'var(--text-secondary)';
}

function getSeverityColor(sev) {
    const map = {
        'NONE': 'var(--text-muted)',
        'MINOR': 'var(--green)',
        'MODERATE': 'var(--amber)',
        'SEVERE': 'var(--red)',
        'CRITICAL': '#fecaca',
    };
    return map[sev] || 'var(--text-secondary)';
}

// ══════════════════════════════════════════════════
// GAUGES
// ══════════════════════════════════════════════════

function updateGauge(gaugeId, value, min, max, valueId, suffix) {
    const gauge = document.getElementById(gaugeId);
    const valEl = document.getElementById(valueId);
    if (!gauge || !valEl) return;

    const circumference = 314.16;
    const pct = Math.max(0, Math.min(1, (value - min) / (max - min)));
    const offset = circumference * (1 - pct);
    gauge.setAttribute('stroke-dashoffset', offset);

    // Color based on percentage
    let color = 'var(--green)';
    if (pct > 0.7) color = 'var(--amber)';
    if (pct > 0.85) color = 'var(--red)';
    gauge.setAttribute('stroke', color);

    valEl.textContent = (typeof value === 'number' ? value.toFixed(1) : value) + suffix;
}

// ══════════════════════════════════════════════════
// BELT CANVAS
// ══════════════════════════════════════════════════

function updateBeltCanvas(s) {
    const canvas = document.getElementById('beltCanvas');
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    
    // Set canvas size
    canvas.width = canvas.offsetWidth * 2;
    canvas.height = canvas.offsetHeight * 2;
    ctx.scale(2, 2);
    const w = canvas.offsetWidth;
    const h = canvas.offsetHeight;
    
    // Clear
    ctx.fillStyle = 'hsl(222, 20%, 8%)';
    ctx.fillRect(0, 0, w, h);
    
    // Draw belt
    const beltY = h / 2;
    const beltH = 20;
    const margin = 40;
    
    // Belt body
    ctx.fillStyle = 'hsl(222, 16%, 18%)';
    ctx.fillRect(margin, beltY - beltH / 2, w - margin * 2, beltH);
    
    // Belt border
    ctx.strokeStyle = 'hsl(222, 12%, 28%)';
    ctx.lineWidth = 1;
    ctx.strokeRect(margin, beltY - beltH / 2, w - margin * 2, beltH);
    
    // Belt position marker
    const beltLen = w - margin * 2;
    const pos = ((s.belt_position_m || 0) % 500) / 500;
    const markerX = margin + pos * beltLen;
    
    ctx.fillStyle = 'var(--blue)';
    ctx.beginPath();
    ctx.arc(markerX, beltY, 5, 0, Math.PI * 2);
    ctx.fill();
    
    // Draw damage markers
    if (s.active_damage_events) {
        s.active_damage_events.forEach((evt, i) => {
            const dmgPos = margin + (((i * 73 + 50) % beltLen));
            const sevColor = {
                'NONE': '#6b7280', 'MINOR': '#34d399', 
                'MODERATE': '#fbbf24', 'SEVERE': '#f87171', 'CRITICAL': '#ef4444'
            }[evt.severity] || '#6b7280';
            
            ctx.fillStyle = sevColor;
            ctx.beginPath();
            ctx.arc(dmgPos, beltY, 4, 0, Math.PI * 2);
            ctx.fill();
            
            // Label
            ctx.fillStyle = sevColor;
            ctx.font = '8px Inter';
            ctx.fillText(evt.type || '', dmgPos - 10, beltY - 14);
        });
    }
    
    // Pulleys
    ctx.fillStyle = 'hsl(222, 14%, 30%)';
    ctx.beginPath();
    ctx.arc(margin, beltY, 12, 0, Math.PI * 2);
    ctx.fill();
    ctx.beginPath();
    ctx.arc(w - margin, beltY, 12, 0, Math.PI * 2);
    ctx.fill();
    
    // Labels
    ctx.fillStyle = 'hsl(220, 10%, 55%)';
    ctx.font = '9px Inter';
    ctx.fillText('TAIL', margin - 8, beltY + 24);
    ctx.fillText('DRIVE', w - margin - 12, beltY + 24);
}

// ══════════════════════════════════════════════════
// DETECTION FEED
// ══════════════════════════════════════════════════

function addDetectionToFeed(event) {
    const feed = document.getElementById('detectionFeed');
    if (!feed) return;
    
    // Remove empty state
    const empty = feed.querySelector('.empty-state');
    if (empty) empty.remove();
    
    const time = new Date(event.detected_at || Date.now()).toLocaleTimeString();
    const type = event.type || event.class_name || 'UNKNOWN';
    const severity = event.severity || 'NONE';
    
    const item = document.createElement('div');
    item.className = 'detection-item';
    item.innerHTML = `
        <div class="detection-time">${time}</div>
        <div class="detection-info">
            <div class="detection-type">
                ${type} 
                <span class="severity-badge severity-${severity}">${severity}</span>
            </div>
            <div class="detection-details">
                Conf: ${(event.confidence || 0).toFixed(2)} · 
                ${(event.length_cm || 0).toFixed(1)} cm · 
                RUL: ${event.rul_impact_hours || 0}h
            </div>
        </div>
    `;
    
    feed.insertBefore(item, feed.firstChild);
    
    // Keep only last 50
    while (feed.children.length > 50) {
        feed.removeChild(feed.lastChild);
    }
    
    // Capture snapshot of the current frame for this detection
    captureDetectionSnapshot(event);
    // Update count
    setText('detectionCount', `${detectionEvents.length} events`);}

function updateDetectionStats() {
    const total = Object.values(detectionStats).reduce((a, b) => a + b, 0) || 1;
    
    const mapping = {
        CRACK: { bar: 'statCrack', val: 'statCrackVal' },
        TEAR: { bar: 'statTear', val: 'statTearVal' },
        SURFACE_DAMAGE: { bar: 'statDamage', val: 'statDamageVal' },
        SURFACE_WEAR: { bar: 'statWear', val: 'statWearVal' },
        SPLICE_GAP: { bar: 'statSplice', val: 'statSpliceVal' },
        EDGE_DAMAGE: { bar: 'statEdge', val: 'statEdgeVal' },
        FOREIGN_OBJECT: { bar: 'statForeign', val: 'statForeignVal' },
    };
    
    for (const [type, ids] of Object.entries(mapping)) {
        const count = detectionStats[type] || 0;
        const bar = document.getElementById(ids.bar);
        const val = document.getElementById(ids.val);
        if (bar) bar.style.width = `${(count / total) * 100}%`;
        if (val) val.textContent = count;
    }
}

// ══════════════════════════════════════════════════
// ADVISORY & COMPLIANCE
// ══════════════════════════════════════════════════

function updateAdvisory(s) {
    const badge = document.getElementById('advisoryBadge');
    const msg = document.getElementById('advisoryMessage');
    if (!badge) return;
    
    const level = s.belt_advisory || 'NORMAL';
    badge.textContent = level.replace(/_/g, ' ');
    badge.className = `advisory-badge advisory-${level}`;
    if (msg) msg.textContent = s.belt_advisory_message || '';
}

function updateTensionSag(s) {
    setText('tensionTight', `${(s.tension_tight_N || 0).toLocaleString()} N`);
    setText('tensionSlack', `${(s.tension_slack_N || 0).toLocaleString()} N`);
    setText('tensionSF', `${s.safety_factor || 0}×`);
    setText('sagRatio', `${s.sag_ratio_pct || 0}%`);
    
    const sagStatus = document.getElementById('sagStatus');
    if (sagStatus) {
        const ok = (s.sag_ratio_pct || 0) <= 2.0;
        sagStatus.innerHTML = `<span class="compliance-chip ${ok ? 'compliance-pass' : 'compliance-fail'}">${ok ? '✓ PASS' : '✗ FAIL'}</span>`;
    }
}

// ══════════════════════════════════════════════════
// SENSOR LIFETIME
// ══════════════════════════════════════════════════

function updateSensors(sensors) {
    // Grid
    const grid = document.getElementById('sensorGrid');
    if (grid && sensors.length > 0) {
        grid.innerHTML = sensors.map(s => {
            const pct = s.remaining_pct || 0;
            let color = 'var(--green)';
            if (pct < 30) color = 'var(--amber)';
            if (pct < 10) color = 'var(--red)';
            
            return `
                <div class="sensor-card">
                    <div class="sensor-id">${s.sensor_id}</div>
                    <div style="font-size:var(--text-xs);color:var(--text-muted)">${s.sensor_type} · ${s.location}</div>
                    <div class="sensor-bar">
                        <div class="sensor-fill" style="width:${pct}%;background:${color}"></div>
                    </div>
                    <div class="sensor-meta">
                        <span>${pct.toFixed(1)}% remaining</span>
                        <span class="severity-badge severity-${s.status === 'GOOD' ? 'MINOR' : s.status === 'REPLACE_SOON' ? 'MODERATE' : 'CRITICAL'}">${s.status}</span>
                    </div>
                </div>
            `;
        }).join('');
    }
    
    // Table
    const tbody = document.getElementById('sensorTableBody');
    if (tbody && sensors.length > 0) {
        tbody.innerHTML = sensors.map(s => `
            <tr>
                <td style="font-weight:600">${s.sensor_id}</td>
                <td>${s.sensor_type}</td>
                <td>${s.location}</td>
                <td>${s.rated_life_hours}</td>
                <td>${s.elapsed_hours}</td>
                <td>${s.remaining_pct?.toFixed(1)}%</td>
                <td><span class="severity-badge severity-${s.status === 'GOOD' ? 'MINOR' : s.status === 'REPLACE_SOON' ? 'MODERATE' : 'CRITICAL'}">${s.status}</span></td>
            </tr>
        `).join('');
    }
}

// ══════════════════════════════════════════════════
// SHAP EXPLAINABILITY
// ══════════════════════════════════════════════════

function updateSHAP(contributions) {
    const container = document.getElementById('shapChart');
    if (!container || !contributions.length) return;
    
    container.innerHTML = contributions.map(c => {
        const pct = (c.contribution * 100).toFixed(1);
        const direction = c.direction || 'neutral';
        return `
            <div class="shap-bar-container">
                <div class="shap-label">${c.feature}</div>
                <div class="shap-bar-wrap">
                    <div class="shap-bar ${direction}" style="width:${pct}%"></div>
                </div>
                <div class="shap-value">${pct}%</div>
            </div>
        `;
    }).join('');
}

function updateRULPanel(s) {
    setText('rulEstimate', `${s.rul_hours || 0} hours`);
    setText('rulSource', s.rul_source || '—');
    setText('rulCILow', `${s.rul_ci_lower || 0} hours`);
    setText('rulCIHigh', `${s.rul_ci_upper || 0} hours`);
}

function updateDamageLog(events) {
    const tbody = document.getElementById('damageLogBody');
    if (!tbody) return;
    
    tbody.innerHTML = events.map(e => `
        <tr>
            <td style="font-weight:600">${(e.id || '').substring(0, 12)}</td>
            <td>${e.type || ''}</td>
            <td><span class="severity-badge severity-${e.severity}">${e.severity}</span></td>
            <td>${(e.confidence || 0).toFixed(2)}</td>
            <td>${(e.length_cm || 0).toFixed(1)} cm</td>
            <td style="color:var(--red)">${e.rul_impact_hours || 0}h</td>
            <td>${new Date(e.detected_at || '').toLocaleTimeString()}</td>
        </tr>
    `).join('');
}

// ══════════════════════════════════════════════════
// PHYSICS
// ══════════════════════════════════════════════════

function updatePhysics(s) {
    setText('kfTension', `${s.kalman_tension || 0} N`);
    setText('kfVibration', `${s.kalman_vibration || 0} mm/s`);
    setText('kfTemperature', `${s.kalman_temperature || 0} °C`);
    
    setText('physSpeed', `${s.belt_speed_mps || 0} m/s`);
    setText('physPosition', `${s.belt_position_m || 0} m`);
    setText('physLoad', `${(s.load_fraction || 1).toFixed(2)}`);
    setText('physPower', `${s.motor_power_kW || 0} kW`);
    
    setText('physVibRMS', `${s.vibration_mms || 0} mm/s`);
    setText('physVibMeas', `${s.vibration_mms || 0} mm/s`);
    setText('physTempCurr', `${s.temperature_c || 0} °C`);
    setText('physTempMeas', `${s.temperature_c || 0} °C`);
}

// ══════════════════════════════════════════════════
// TAB SWITCH HELPER
// ══════════════════════════════════════════════════

function switchToTab(tabId) {
    document.querySelectorAll('.nav-item').forEach(n => {
        if (n.dataset.tab === tabId) {
            n.classList.add('active');
            const titleSpan = n.querySelector('span:nth-child(2)');
            if (titleSpan) document.getElementById('tabTitle').textContent = titleSpan.textContent;
        } else {
            n.classList.remove('active');
        }
    });
    document.querySelectorAll('.tab-content').forEach(t => t.classList.remove('active'));
    const target = document.getElementById('tab-' + tabId);
    if (target) target.classList.add('active');
}


// ══════════════════════════════════════════════════
// CAMERA FEED & STREAM
// ══════════════════════════════════════════════════

async function startCamera() {
    try {
        cameraStream = await navigator.mediaDevices.getUserMedia({ 
            video: { width: 640, height: 480 } 
        });
        
        const video = document.getElementById('liveVideo');
        const canvas = document.getElementById('liveCanvas');
        const placeholder = document.querySelector('#liveFeedContainer .video-placeholder');
        const overlay = document.getElementById('videoOverlay');
        
        video.srcObject = cameraStream;
        video.style.display = 'block';
        if (placeholder) placeholder.style.display = 'none';
        if (overlay) overlay.style.display = 'flex';
        
        detectionOverlay = canvas;
        detectionCtx = canvas.getContext('2d');
        
        document.getElementById('btnStartCam').style.display = 'none';
        document.getElementById('btnStopCam').style.display = 'inline-flex';
        
        // Start sending frames (every 200ms = ~5 FPS)
        cameraInterval = setInterval(() => sendFrame(video, canvas), 200);
        
    } catch (err) {
        console.error('Camera error:', err);
        alert('Camera access denied or not available. Please check permissions.');
    }
}

function stopCamera() {
    if (cameraInterval) clearInterval(cameraInterval);
    if (cameraStream) {
        cameraStream.getTracks().forEach(t => t.stop());
        cameraStream = null;
    }
    
    const video = document.getElementById('liveVideo');
    video.style.display = 'none';
    video.srcObject = null;
    
    const placeholder = document.querySelector('#liveFeedContainer .video-placeholder');
    if (placeholder) placeholder.style.display = 'block';
    
    document.getElementById('videoOverlay').style.display = 'none';
    document.getElementById('btnStartCam').style.display = 'inline-flex';
    document.getElementById('btnStopCam').style.display = 'none';
}

async function sendFrame(video, canvas) {
    if (!video.videoWidth) return;
    
    canvas.width = video.videoWidth;
    canvas.height = video.videoHeight;
    const ctx = canvas.getContext('2d');
    ctx.drawImage(video, 0, 0);
    
    canvas.toBlob(async (blob) => {
        if (!blob) return;
        
        const formData = new FormData();
        formData.append('frame', blob, 'frame.jpg');
        
        try {
            const start = performance.now();
            const resp = await fetch('/api/detect/frame', { method: 'POST', body: formData });
            const data = await resp.json();
            const latency = Math.round(performance.now() - start);
            
            setText('videoFPS', `FPS: ${Math.round(1000 / latency)}`);
            setText('videoLatency', `Latency: ${latency}ms`);
            setText('videoModel', `Detections: ${data.detections?.length || 0}`);
            
            if (data.detections && data.detections.length > 0) {
                data.detections.forEach(d => {
                    addDetectionEvent({
                        time: new Date().toLocaleTimeString(),
                        type: d.class_name,
                        severity: d.severity,
                        confidence: d.confidence,
                        size: `${d.length_cm} cm`,
                        rulImpact: `${d.rul_impact_hours}h`,
                    });
                });
            }
        } catch (e) {
            console.error('Frame send error:', e);
        }
    }, 'image/jpeg', 0.7);
}


// ══════════════════════════════════════════════════
// VIDEO UPLOAD & REAL-TIME PLAYBACK INSPECTION
// ══════════════════════════════════════════════════

let currentVideoJob = null;
let currentVideoEvents = [];
let syncedEventIds = new Set();
let playbackAnimFrameId = null;
let playbackVideo = null;
let playbackCanvas = null;
let playbackCtx = null;

// Initialize Video Player on DOM Load
function initVideoPlayerElements() {
    playbackVideo = document.getElementById('playbackVideo');
    playbackCanvas = document.getElementById('playbackCanvas');
    if (playbackCanvas) {
        playbackCtx = playbackCanvas.getContext('2d');
    }
    
    if (playbackVideo) {
        playbackVideo.addEventListener('play', () => {
            const btn = document.getElementById('btnPlayPause');
            if (btn) btn.textContent = '⏸ Pause';
            startPlaybackLoop();
        });
        
        playbackVideo.addEventListener('pause', () => {
            const btn = document.getElementById('btnPlayPause');
            if (btn) btn.textContent = '▶ Play';
            stopPlaybackLoop();
            renderVideoAnnotations();
        });
        
        playbackVideo.addEventListener('ended', () => {
            const btn = document.getElementById('btnPlayPause');
            if (btn) btn.textContent = '↺ Replay';
            stopPlaybackLoop();
        });
        
        playbackVideo.addEventListener('timeupdate', () => {
            if (playbackVideo.paused) {
                renderVideoAnnotations();
            }
        });
        
        playbackVideo.addEventListener('loadedmetadata', () => {
            syncCanvasDimensions();
            renderVideoAnnotations();
        });
    }
}

document.addEventListener('DOMContentLoaded', initVideoPlayerElements);
setTimeout(initVideoPlayerElements, 500);

const uploadZone = document.getElementById('uploadZone');
const fileInput = document.getElementById('videoFileInput');

if (uploadZone) {
    uploadZone.addEventListener('click', () => fileInput?.click());
    uploadZone.addEventListener('dragover', (e) => {
        e.preventDefault();
        uploadZone.classList.add('dragover');
    });
    uploadZone.addEventListener('dragleave', () => {
        uploadZone.classList.remove('dragover');
    });
    uploadZone.addEventListener('drop', (e) => {
        e.preventDefault();
        uploadZone.classList.remove('dragover');
        if (e.dataTransfer.files.length) handleVideoUpload(e.dataTransfer.files[0]);
    });
}

if (fileInput) {
    fileInput.addEventListener('change', () => {
        if (fileInput.files.length) handleVideoUpload(fileInput.files[0]);
    });
}

async function handleVideoUpload(file) {
    const frameSkip = document.getElementById('frameSkipSelect')?.value || '5';
    const confThreshold = document.getElementById('confThresholdSelect')?.value || '0.12';
    const formData = new FormData();
    formData.append('video', file);
    formData.append('frame_skip', frameSkip);
    formData.append('conf_threshold', confThreshold);
    
    document.getElementById('uploadProgress').style.display = 'block';
    uploadZone.style.display = 'none';
    setText('uploadLabel', `Uploading & processing: ${file.name}`);
    setText('uploadPct', '0%');
    document.getElementById('uploadBar').style.width = '0%';
    
    try {
        const resp = await fetch('/api/detect/video', { method: 'POST', body: formData });
        const data = await resp.json();
        pollVideoJob(data.job_id);
    } catch (e) {
        console.error('Upload error:', e);
        setText('uploadLabel', 'Upload failed: ' + e.message);
    }
}

async function loadSampleConveyorVideo() {
    setText('uploadLabel', 'Locating conveyor belt test video...');
    document.getElementById('uploadProgress').style.display = 'block';
    if (uploadZone) uploadZone.style.display = 'none';
    
    try {
        const listResp = await fetch('/api/detect/sample-videos');
        const listData = await listResp.json();
        
        let filename = '';
        if (listData.samples && listData.samples.length > 0) {
            filename = listData.samples[0].filename;
        }
        
        if (!filename) {
            alert('No sample video found in data/uploads. Please upload a video file.');
            resetVideoUpload();
            return;
        }
        
        setText('uploadLabel', `Analyzing sample conveyor footage: ${filename}`);
        const frameSkip = document.getElementById('frameSkipSelect')?.value || '5';
        const confThreshold = document.getElementById('confThresholdSelect')?.value || '0.12';
        
        const form = new FormData();
        form.append('filename', filename);
        form.append('frame_skip', frameSkip);
        form.append('conf_threshold', confThreshold);
        
        const resp = await fetch('/api/detect/load-sample', { method: 'POST', body: form });
        const data = await resp.json();
        pollVideoJob(data.job_id);
        
    } catch (e) {
        console.error('Load sample error:', e);
        setText('uploadLabel', 'Error loading sample: ' + e.message);
    }
}

async function pollVideoJob(jobId) {
    const interval = setInterval(async () => {
        try {
            const resp = await fetch(`/api/detect/video/${jobId}`);
            const data = await resp.json();
            
            const pct = data.progress_pct || 0;
            setText('uploadPct', `${pct}%`);
            const bar = document.getElementById('uploadBar');
            if (bar) bar.style.width = `${pct}%`;
            setText('uploadFrames', `${data.processed_frames || 0} / ${data.total_frames || 0} frames scanned`);
            setText('uploadDetectionsFound', `${data.total_detections || 0} defects found`);
            
            if (data.status === 'completed') {
                clearInterval(interval);
                showVideoResults(data);
            }
        } catch (e) {
            console.error('Poll error:', e);
        }
    }, 800);
}

function showVideoResults(data) {
    currentVideoJob = data;
    currentVideoEvents = (data.events || []).sort((a, b) => (a.time_s || 0) - (b.time_s || 0));
    syncedEventIds.clear();
    
    setText('uploadLabel', '✓ Inspection Complete — Ready for Live Playback');
    document.getElementById('videoResults').style.display = 'block';
    const btnReset = document.getElementById('btnResetUpload');
    if (btnReset) btnReset.style.display = 'inline-flex';
    
    // Setup Video Source for Playback
    if (!playbackVideo) initVideoPlayerElements();
    if (playbackVideo) {
        playbackVideo.src = `/api/detect/video/${data.job_id}/stream`;
        playbackVideo.load();
    }
    
    // Summary
    const summary = document.getElementById('videoSummary');
    if (summary && data.summary) {
        const s = data.summary;
        summary.innerHTML = `
            <div style="display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-bottom:14px">
                <div class="kpi-card events" style="padding:10px">
                    <div class="kpi-label">Total Detections</div>
                    <div style="font-size:24px;font-weight:800;color:var(--text-primary);font-family:var(--font-mono)">${s.total_detections || 0}</div>
                    <div class="kpi-sub">${data.total_frames || 0} frames analyzed</div>
                </div>
                <div class="kpi-card alert" style="padding:10px">
                    <div class="kpi-label">Worst Severity</div>
                    <div style="margin-top:4px"><span class="severity-badge severity-${s.worst_severity}" style="font-size:14px">${s.worst_severity}</span></div>
                    <div class="kpi-sub">ISO 15236 standard</div>
                </div>
            </div>
            
            <div style="margin-bottom:12px">
                <div class="kpi-label" style="margin-bottom:6px">Defects Discovered by Category</div>
                <div style="display:grid;grid-template-columns:1fr 1fr;gap:6px">
                    ${Object.entries(s.type_counts || {}).map(([k, v]) => `
                        <div style="font-size:var(--text-xs);background:var(--surface-2);padding:6px 10px;border-radius:4px;display:flex;justify-content:space-between">
                            <span style="font-weight:600">${k}:</span>
                            <span style="color:var(--blue);font-family:var(--font-mono)">${v}</span>
                        </div>
                    `).join('')}
                </div>
            </div>
            
            <div style="background:hsla(0, 80%, 50%, 0.08);border-left:3px solid var(--red);padding:10px;border-radius:4px;margin-top:10px">
                <div class="kpi-label" style="color:var(--red)">Total Projected RUL Degradation</div>
                <div style="font-size:20px;font-weight:800;color:var(--red);font-family:var(--font-mono)">-${s.total_rul_impact_hours || 0} hours</div>
                <div style="font-size:11px;color:var(--text-secondary);margin-top:2px">Instantaneous fatigue impact applied during live playback</div>
            </div>
        `;
    }
    
    // Render timeline markers along the seekbar
    renderTimelineMarkers(currentVideoEvents, data.duration_s || 60);
    
    // Event Table
    const tbody = document.getElementById('videoEventBody');
    setText('videoEventCount', `${currentVideoEvents.length} events logged`);
    if (tbody) {
        tbody.innerHTML = currentVideoEvents.map((e, idx) => `
            <tr style="cursor:pointer" onclick="seekToVideoTime(${e.time_s || 0})" title="Click to seek to ${(e.time_s || 0).toFixed(1)}s">
                <td style="font-family:var(--font-mono);font-weight:600;color:var(--blue)">${(e.time_s || 0).toFixed(1)}s</td>
                <td style="font-family:var(--font-mono);color:var(--text-muted)">#${e.frame || 0}</td>
                <td style="font-weight:600">${e.class_name}</td>
                <td><span class="severity-badge severity-${e.severity}">${e.severity}</span></td>
                <td style="font-family:var(--font-mono)">${((e.confidence || 0) * 100).toFixed(1)}%</td>
                <td style="font-family:var(--font-mono)">${(e.length_cm || 0).toFixed(1)} cm</td>
                <td style="color:var(--red);font-family:var(--font-mono);font-weight:700">-${e.rul_impact_hours || 0}h</td>
                <td><button class="btn btn-outline btn-sm" style="padding:2px 8px;font-size:11px" onclick="event.stopPropagation();seekToVideoTime(${e.time_s || 0})">🎯 Jump</button></td>
            </tr>
        `).join('');
    }
}

function resetVideoUpload() {
    if (playbackVideo) {
        playbackVideo.pause();
        playbackVideo.src = '';
    }
    stopPlaybackLoop();
    document.getElementById('videoResults').style.display = 'none';
    document.getElementById('uploadProgress').style.display = 'none';
    if (uploadZone) uploadZone.style.display = 'block';
    const btnReset = document.getElementById('btnResetUpload');
    if (btnReset) btnReset.style.display = 'none';
    if (fileInput) fileInput.value = '';
}

// ── Playback Controls ──

function toggleVideoPlayback() {
    if (!playbackVideo) initVideoPlayerElements();
    if (!playbackVideo) return;
    
    if (playbackVideo.paused || playbackVideo.ended) {
        playbackVideo.play().catch(e => console.error("Playback error:", e));
    } else {
        playbackVideo.pause();
    }
}

function restartVideoPlayback() {
    if (!playbackVideo) return;
    playbackVideo.currentTime = 0;
    syncedEventIds.clear();
    playbackVideo.play().catch(e => console.error(e));
}

function setPlaybackSpeed(speed, btn) {
    if (playbackVideo) playbackVideo.playbackRate = speed;
    document.querySelectorAll('.speed-chip').forEach(b => b.classList.remove('active'));
    if (btn) btn.classList.add('active');
}

function onVideoSeek(val) {
    if (!playbackVideo || !playbackVideo.duration) return;
    playbackVideo.currentTime = (val / 100) * playbackVideo.duration;
    renderVideoAnnotations();
}

function seekToVideoTime(time_s) {
    if (!playbackVideo) return;
    playbackVideo.currentTime = Math.max(0, time_s);
    renderVideoAnnotations();
    if (playbackVideo.paused) {
        playbackVideo.play().catch(e => console.error(e));
    }
}

function renderTimelineMarkers(events, duration) {
    const container = document.getElementById('timelineMarkers');
    if (!container || !duration) return;
    container.innerHTML = '';
    
    events.forEach(e => {
        const pct = Math.min(100, Math.max(0, ((e.time_s || 0) / duration) * 100));
        const marker = document.createElement('div');
        marker.className = 'timeline-defect-marker';
        marker.style.left = `${pct}%`;
        
        let color = '#06b6d4'; // MINOR
        if (e.severity === 'CRITICAL') color = '#ef4444';
        else if (e.severity === 'SEVERE') color = '#f97316';
        else if (e.severity === 'MODERATE') color = '#f59e0b';
        marker.style.background = color;
        
        marker.title = `${e.class_name} at ${(e.time_s || 0).toFixed(1)}s (${e.severity})`;
        marker.addEventListener('click', (ev) => {
            ev.stopPropagation();
            seekToVideoTime(e.time_s || 0);
        });
        container.appendChild(marker);
    });
}

function startPlaybackLoop() {
    if (playbackAnimFrameId) cancelAnimationFrame(playbackAnimFrameId);
    
    function loop() {
        if (!playbackVideo || playbackVideo.paused || playbackVideo.ended) return;
        renderVideoAnnotations();
        playbackAnimFrameId = requestAnimationFrame(loop);
    }
    playbackAnimFrameId = requestAnimationFrame(loop);
}

function stopPlaybackLoop() {
    if (playbackAnimFrameId) {
        cancelAnimationFrame(playbackAnimFrameId);
        playbackAnimFrameId = null;
    }
}

function syncCanvasDimensions() {
    if (!playbackVideo || !playbackCanvas) return;
    const w = playbackVideo.videoWidth || playbackVideo.clientWidth || 1280;
    const h = playbackVideo.videoHeight || playbackVideo.clientHeight || 720;
    if (playbackCanvas.width !== w || playbackCanvas.height !== h) {
        playbackCanvas.width = w;
        playbackCanvas.height = h;
    }
}

// Draw real-time bounding boxes and trigger live Digital Twin sync
function renderVideoAnnotations() {
    if (!playbackVideo || !playbackCanvas || !playbackCtx) return;
    syncCanvasDimensions();
    
    const currTime = playbackVideo.currentTime;
    const duration = playbackVideo.duration || 1;
    
    // Update seek range & time displays
    const seekRange = document.getElementById('videoSeekRange');
    if (seekRange && !playbackVideo.seeking) {
        seekRange.value = (currTime / duration) * 100;
    }
    
    setText('playbackTimeDisplay', `${formatSecs(currTime)} / ${formatSecs(duration)}`);
    const fps = currentVideoJob?.fps || 30;
    setText('playbackFrameDisplay', `Frame: ${Math.floor(currTime * fps)}`);
    
    // Clear canvas
    playbackCtx.clearRect(0, 0, playbackCanvas.width, playbackCanvas.height);
    
    const showBoxes = document.getElementById('chkBoxes')?.checked ?? true;
    const syncTwin = document.getElementById('chkSyncTwin')?.checked ?? true;
    const audioAlert = document.getElementById('chkAudioAlert')?.checked ?? true;
    
    // Adaptive active defects window: matches frame sampling and playback pace
    const window_s = Math.max(0.40, ((currentVideoJob?.frame_skip || 5) / (currentVideoJob?.fps || 25)) * 1.6);
    const activeDefects = currentVideoEvents.filter(e => {
        return Math.abs((e.time_s || 0) - currTime) <= window_s;
    });
    
    setText('playbackDetectionsCount', `Active: ${activeDefects.length} defect${activeDefects.length === 1 ? '' : 's'}`);
    
    const hudBadge = document.getElementById('defectHudBadge');
    
    if (activeDefects.length > 0) {
        const topDefect = activeDefects[0];
        
        // Show HUD Badge
        if (hudBadge) {
            hudBadge.style.display = 'block';
            setText('hudDefectClass', topDefect.class_name);
            const sevEl = document.getElementById('hudDefectSeverity');
            if (sevEl) {
                sevEl.textContent = topDefect.severity;
                sevEl.className = `severity-badge severity-${topDefect.severity}`;
            }
            setText('hudDefectDetails', `Conf: ${((topDefect.confidence || 0) * 100).toFixed(1)}% | Length: ${(topDefect.length_cm || 0).toFixed(1)}cm | RUL -${topDefect.rul_impact_hours || 0}h`);
        }
        
        // Draw bounding boxes and segmentation masks on canvas
        if (showBoxes) {
            activeDefects.forEach(det => {
                drawBoundingBoxHUD(det, playbackCtx, playbackCanvas.width, playbackCanvas.height);
            });
        }
        
        // Real-time synchronization with Digital Twin
        if (syncTwin && !syncedEventIds.has(topDefect.id)) {
            syncedEventIds.add(topDefect.id);
            syncLiveDefectToTwin(topDefect);
            
            if (audioAlert) {
                playDefectAudioBeep();
            }
            
            // Add event card to Live Detection Feed tab
            addDetectionEvent({
                time: `${formatSecs(currTime)} (Playback)`,
                type: topDefect.class_name,
                severity: topDefect.severity,
                confidence: topDefect.confidence,
                size: `${topDefect.length_cm} cm`,
                rulImpact: `${topDefect.rul_impact_hours}h`,
            });
            
            // Update live statistics bar
            incrementDetectionStat(topDefect.class_name);
        }
        
    } else {
        if (hudBadge) hudBadge.style.display = 'none';
    }
}

function drawBoundingBoxHUD(det, ctx, canvasW, canvasH) {
    const bbox = det.bbox_xyxy || [0, 0, 0, 0];
    let [x1, y1, x2, y2] = bbox;
    
    // In case coordinates are normalized 0-1
    if (x2 <= 1.0 && y2 <= 1.0) {
        x1 *= canvasW;
        x2 *= canvasW;
        y1 *= canvasH;
        y2 *= canvasH;
    }
    
    const w = Math.max(20, x2 - x1);
    const h = Math.max(20, y2 - y1);
    
    let strokeColor = '#38bdf8'; // MINOR cyan
    let fillColor = 'rgba(56, 189, 248, 0.15)';
    if (det.severity === 'CRITICAL') {
        strokeColor = '#ef4444'; // Red
        fillColor = 'rgba(239, 68, 68, 0.22)';
    } else if (det.severity === 'SEVERE') {
        strokeColor = '#f97316'; // Orange
        fillColor = 'rgba(249, 115, 22, 0.18)';
    } else if (det.severity === 'MODERATE') {
        strokeColor = '#f59e0b'; // Amber
        fillColor = 'rgba(245, 158, 11, 0.16)';
    }
    
    ctx.save();
    
    // Render Segmentation Mask Polygon if present
    if (det.mask_polygon && det.mask_polygon.length >= 3) {
        ctx.beginPath();
        det.mask_polygon.forEach((pt, pIdx) => {
            let px = pt[0];
            let py = pt[1];
            if (px <= 1.0 && py <= 1.0) {
                px *= canvasW;
                py *= canvasH;
            }
            if (pIdx === 0) ctx.moveTo(px, py);
            else ctx.lineTo(px, py);
        });
        ctx.closePath();
        ctx.fillStyle = fillColor;
        ctx.fill();
        ctx.strokeStyle = strokeColor;
        ctx.lineWidth = 2;
        ctx.stroke();
    }
    
    // Fill bounding box
    ctx.fillStyle = fillColor;
    ctx.fillRect(x1, y1, w, h);
    
    // Draw glowing border
    ctx.strokeStyle = strokeColor;
    ctx.lineWidth = 2.5;
    ctx.shadowColor = strokeColor;
    ctx.shadowBlur = 10;
    ctx.strokeRect(x1, y1, w, h);
    
    // Corner brackets HUD style
    const cLen = Math.min(18, w / 3, h / 3);
    ctx.lineWidth = 4;
    
    // Top-Left
    ctx.beginPath();
    ctx.moveTo(x1, y1 + cLen);
    ctx.lineTo(x1, y1);
    ctx.lineTo(x1 + cLen, y1);
    ctx.stroke();
    
    // Top-Right
    ctx.beginPath();
    ctx.moveTo(x2 - cLen, y1);
    ctx.lineTo(x2, y1);
    ctx.lineTo(x2, y1 + cLen);
    ctx.stroke();
    
    // Bottom-Left
    ctx.beginPath();
    ctx.moveTo(x1, y2 - cLen);
    ctx.lineTo(x1, y2);
    ctx.lineTo(x1 + cLen, y2);
    ctx.stroke();
    
    // Bottom-Right
    ctx.beginPath();
    ctx.moveTo(x2 - cLen, y2);
    ctx.lineTo(x2, y2);
    ctx.lineTo(x2, y2 - cLen);
    ctx.stroke();
    
    // Label Banner
    ctx.shadowBlur = 0;
    const label = `${det.class_name} ${((det.confidence || 0) * 100).toFixed(0)}% [${det.severity}]`;
    ctx.font = 'bold 13px Inter, sans-serif';
    const textMetrics = ctx.measureText(label);
    const textW = textMetrics.width + 12;
    const textH = 22;
    
    const labelY = Math.max(textH, y1);
    ctx.fillStyle = strokeColor;
    ctx.fillRect(x1, labelY - textH, textW, textH);
    
    ctx.fillStyle = '#ffffff';
    ctx.fillText(label, x1 + 6, labelY - 6);
    
    ctx.restore();
}

async function syncLiveDefectToTwin(det) {
    try {
        const liveBadge = document.getElementById('playbackLiveBadge');
        if (liveBadge) liveBadge.style.display = 'inline-flex';
        
        await fetch('/api/detect/sync-twin', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                class_name: det.class_name,
                confidence: det.confidence || 0.9,
                severity: det.severity || 'MODERATE',
                length_cm: det.length_cm || 15.0,
                rul_impact_hours: det.rul_impact_hours || 10.0,
                source: 'video_playback',
            }),
        });
    } catch (e) {
        console.error('Twin sync error:', e);
    }
}

function incrementDetectionStat(className) {
    if (detectionStats.hasOwnProperty(className)) {
        detectionStats[className]++;
    } else {
        detectionStats[className] = 1;
    }
    updateStatsDisplay();
}

function playDefectAudioBeep() {
    try {
        const AudioCtx = window.AudioContext || window.webkitAudioContext;
        if (!AudioCtx) return;
        const ctx = new AudioCtx();
        const osc = ctx.createOscillator();
        const gain = ctx.createGain();
        osc.connect(gain);
        gain.connect(ctx.destination);
        osc.type = 'sawtooth';
        osc.frequency.setValueAtTime(880, ctx.currentTime);
        osc.frequency.exponentialRampToValueAtTime(440, ctx.currentTime + 0.12);
        gain.gain.setValueAtTime(0.12, ctx.currentTime);
        gain.gain.exponentialRampToValueAtTime(0.01, ctx.currentTime + 0.12);
        osc.start();
        osc.stop(ctx.currentTime + 0.13);
    } catch (e) {}
}

function exportDetectionReport(format = 'csv') {
    if (!currentVideoEvents || currentVideoEvents.length === 0) {
        alert('No detections available to export.');
        return;
    }
    
    if (format === 'csv') {
        const headers = ['Time_s', 'Frame', 'Class_Name', 'Severity', 'Confidence', 'Length_cm', 'RUL_Impact_Hours'];
        const rows = currentVideoEvents.map(e => [
            (e.time_s || 0).toFixed(2),
            e.frame || 0,
            e.class_name,
            e.severity,
            (e.confidence || 0).toFixed(3),
            (e.length_cm || 0).toFixed(1),
            e.rul_impact_hours || 0,
        ]);
        
        let csvContent = 'data:text/csv;charset=utf-8,' + [headers.join(','), ...rows.map(r => r.join(','))].join('\n');
        const encodedUri = encodeURI(csvContent);
        const link = document.createElement('a');
        link.setAttribute('href', encodedUri);
        link.setAttribute('download', `IRIS_Defect_Inspection_${currentVideoJob?.job_id || 'export'}.csv`);
        document.body.appendChild(link);
        link.click();
        document.body.removeChild(link);
    }
}

function formatSecs(s) {
    s = Math.max(0, Math.floor(s || 0));
    const mins = Math.floor(s / 60);
    const secs = s % 60;
    return `${String(mins).padStart(2, '0')}:${String(secs).padStart(2, '0')}`;
}

// ══════════════════════════════════════════════════
// FAULT INJECTION
// ══════════════════════════════════════════════════

async function injectFault(type) {
    try {
        await fetch(`/api/faults/${type}`, { method: 'POST' });
    } catch (e) {
        console.error('Fault injection error:', e);
    }
}

// ══════════════════════════════════════════════════
// MAINTENANCE
// ══════════════════════════════════════════════════

async function logMaintenance() {
    const type = document.getElementById('maintType')?.value;
    const desc = document.getElementById('maintDesc')?.value;
    const by = document.getElementById('maintBy')?.value;
    
    if (!desc) {
        alert('Please enter a description');
        return;
    }
    
    try {
        const resp = await fetch('/api/maintenance-events', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                event_type: type,
                description: desc,
                performed_by: by || '',
            }),
        });
        const data = await resp.json();
        setText('maintResult', `✓ Event logged (ID: ${data.id})`);
        document.getElementById('maintDesc').value = '';
        document.getElementById('maintBy').value = '';
    } catch (e) {
        setText('maintResult', '✗ Failed to log event');
    }
}

// ══════════════════════════════════════════════════
// REPORT HUB CONTROLLERS
// ══════════════════════════════════════════════════

function previewLiveHtmlReport() {
    const previewPanel = document.getElementById('reportPreviewPanel');
    if (previewPanel) {
        previewPanel.scrollIntoView({ behavior: 'smooth' });
    }
    refreshReportPreview();
}

function refreshReportPreview() {
    const iframe = document.getElementById('reportIframe');
    if (iframe) {
        iframe.src = `/api/report/html?t=${Date.now()}`;
    }
}

function toggleReportFullscreen() {
    const iframe = document.getElementById('reportIframe');
    if (!iframe) return;
    if (iframe.style.height === '900px') {
        iframe.style.height = '650px';
    } else {
        iframe.style.height = '900px';
    }
}

function printReportIframe() {
    const iframe = document.getElementById('reportIframe');
    if (iframe && iframe.contentWindow) {
        iframe.contentWindow.focus();
        iframe.contentWindow.print();
    } else {
        window.open('/api/report/html', '_blank');
    }
}

async function generateAndSaveReportSnapshot() {
    const statusEl = document.getElementById('reportSaveStatus');
    if (statusEl) {
        statusEl.style.display = 'block';
        statusEl.textContent = '⏳ Generating HTML, PDF, and JPEG snapshot...';
        statusEl.style.color = 'var(--blue)';
    }

    try {
        const resp = await fetch('/api/report/generate', { method: 'POST' });
        const data = await resp.json();
        if (statusEl) {
            statusEl.textContent = `✓ Report Snapshot Generated: ${data.report_id} (HTML, PDF, JPEG saved)`;
            statusEl.style.color = 'var(--green)';
        }
        refreshReportPreview();
        loadSavedReportsList();
    } catch (e) {
        if (statusEl) {
            statusEl.textContent = `✗ Failed to generate report snapshot: ${e}`;
            statusEl.style.color = 'var(--red)';
        }
    }
}

async function loadSavedReportsList() {
    const tbody = document.getElementById('savedReportsTbody');
    if (!tbody) return;

    try {
        const resp = await fetch('/api/report/list');
        const data = await resp.json();
        const reports = data.reports || [];

        if (reports.length === 0) {
            tbody.innerHTML = `<tr><td colspan="6" style="text-align:center;color:var(--text-muted);padding:16px">No saved reports found. Click "Generate & Save Snapshot" above.</td></tr>`;
            return;
        }

        tbody.innerHTML = reports.map(r => `
            <tr>
                <td style="font-weight:600;font-family:var(--font-mono)">${r.report_id}</td>
                <td style="color:var(--text-secondary)">${r.created_at}</td>
                <td>${r.size_kb} KB</td>
                <td>
                    <a href="/api/report/download/${r.html_filename}" target="_blank" class="btn btn-outline btn-sm" style="padding:2px 8px;font-size:11px">
                        🌐 View HTML
                    </a>
                </td>
                <td>
                    ${r.pdf_filename ? `
                    <a href="/api/report/download/${r.pdf_filename}" class="btn btn-outline btn-sm" download style="padding:2px 8px;font-size:11px">
                        📄 PDF
                    </a>` : `<span style="color:var(--text-muted)">-</span>`}
                </td>
                <td>
                    ${r.jpeg_filename ? `
                    <a href="/api/report/download/${r.jpeg_filename}" class="btn btn-outline btn-sm" download style="padding:2px 8px;font-size:11px">
                        🖼️ JPEG
                    </a>` : `<span style="color:var(--text-muted)">-</span>`}
                </td>
            </tr>
        `).join('');

    } catch (e) {
        tbody.innerHTML = `<tr><td colspan="6" style="text-align:center;color:var(--red);padding:16px">Error loading saved reports list.</td></tr>`;
    }
}

// ══════════════════════════════════════════════════
// THEME
// ══════════════════════════════════════════════════

function toggleTheme() {
    // Minimal toggle — could expand to full light theme
    document.body.classList.toggle('light-theme');
    // Ensure overlay canvas resizes with theme changes if needed
    if (detectionOverlay) {
        detectionOverlay.width = detectionOverlay.width; // trigger resize
    }
}


// ══════════════════════════════════════════════════
// CLOCK
// ══════════════════════════════════════════════════

function updateClock() {
    const now = new Date();
    setText('currentTime', now.toLocaleTimeString('en-US', { hour12: false }));
}

setInterval(updateClock, 1000);
updateClock();

// ══════════════════════════════════════════════════
// IMMERSIVE LOADING SCREEN CONTROLLER
// ══════════════════════════════════════════════════

let loadingProgress = 0;
let loadingDismissed = false;

function initLoadingScreen() {
    const fill = document.getElementById('loadingProgressFill');
    const pct = document.getElementById('loadingPercentage');
    const statusText = document.getElementById('loadingStatusText');
    const log = document.getElementById('loadingTerminalLog');
    const btnEnter = document.getElementById('btnEnterNow');

    const steps = [
        { pct: 25, status: 'Physics Engine & IS 11592 Dynamics Active', log: '[SYS_INIT] Physics Engine loaded: catenary sag, belt tension model ready.', stepId: 'step1' },
        { pct: 55, status: 'Multi-Sensor Telemetry & Kalman Filter Calibrated', log: '[KALMAN_EST] State Estimator covariance matrices initialized (P, R, Q).', stepId: 'step2' },
        { pct: 85, status: 'Vision AI & Neural RUL Predictor Online', log: '[AI_MODEL] YOLOv8 defect classifier and RUL degradation engine online.', stepId: 'step3' },
        { pct: 100, status: 'Digital Twin Synchronized • System Ready', log: '[NET_WS] WebSocket live state link established at 10Hz stream.', stepId: 'step4' }
    ];

    let stepIdx = 0;
    const interval = setInterval(() => {
        if (loadingDismissed) {
            clearInterval(interval);
            return;
        }

        loadingProgress += Math.floor(Math.random() * 8) + 4;
        
        if (stepIdx < steps.length && loadingProgress >= steps[stepIdx].pct) {
            const currentStepObj = steps[stepIdx];
            
            // Mark current step done
            const stepEl = document.getElementById(currentStepObj.stepId);
            if (stepEl) {
                stepEl.classList.remove('active');
                stepEl.classList.add('done');
                const statusSpan = stepEl.querySelector('.step-status');
                if (statusSpan) statusSpan.textContent = 'LOADED';
            }

            stepIdx++;
            if (stepIdx < steps.length) {
                const nextStepEl = document.getElementById(steps[stepIdx].stepId);
                if (nextStepEl) {
                    nextStepEl.classList.add('active');
                    const statusSpan = nextStepEl.querySelector('.step-status');
                    if (statusSpan) statusSpan.textContent = 'RUNNING...';
                }
            }

            if (currentStepObj) {
                if (statusText) statusText.textContent = currentStepObj.status;
                if (log) log.textContent = currentStepObj.log;
            }
        }

        if (loadingProgress >= 100) {
            loadingProgress = 100;
            clearInterval(interval);
            if (fill) fill.style.width = '100%';
            if (pct) pct.textContent = '100%';
            if (statusText) statusText.textContent = 'IRIS Digital Twin Operational';
            if (btnEnter) btnEnter.style.display = 'flex';

            // Auto dismiss loading screen after 900ms
            setTimeout(() => {
                dismissLoadingScreen();
            }, 900);
        } else {
            if (fill) fill.style.width = loadingProgress + '%';
            if (pct) pct.textContent = loadingProgress + '%';
        }
    }, 120);
}

function dismissLoadingScreen() {
    if (loadingDismissed) return;
    loadingDismissed = true;
    const overlay = document.getElementById('loadingOverlay');
    if (overlay) {
        overlay.classList.add('fade-out');
        setTimeout(() => {
            overlay.style.display = 'none';
        }, 600);
    }
}

// ══════════════════════════════════════════════════
// INIT
// ══════════════════════════════════════════════════

initLoadingScreen();
connectWebSocket();
loadSavedReportsList();

