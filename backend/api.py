"""
FastAPI Backend — API routes and WebSocket handlers.
Serves the Digital Twin dashboard and all API endpoints.
"""

import asyncio
import json
import logging
import os
import time
import base64
from datetime import datetime
from pathlib import Path
from typing import Optional

import numpy as np
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, UploadFile, File, Form, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, FileResponse, JSONResponse, Response
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from twin.engine import DigitalTwinEngine
from twin.state import DamageEvent
from twin.scenario import ScenarioEngine
from database.models import get_engine, create_tables, get_session
from reports.generator import (
    generate_html_report,
    generate_pdf_report,
    generate_jpeg_report,
    save_report_snapshot,
    list_saved_reports,
)

logger = logging.getLogger(__name__)

# ── Create app ──
app = FastAPI(
    title="IRIS — Digital Twin for Conveyor Belt Inspection",
    description="PS26008 Intelligent Real-time Inspection System",
    version="1.0.0-mvp",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Global state ──
twin_engine = DigitalTwinEngine()
scenario_engine = ScenarioEngine()

# Database setup
os.makedirs("data", exist_ok=True)
db_engine = get_engine()
create_tables(db_engine)

# WebSocket connection manager
class ConnectionManager:
    def __init__(self):
        self.active_connections: list[WebSocket] = []
        self.detection_connections: list[WebSocket] = []

    async def connect(self, websocket: WebSocket, channel: str = "live"):
        await websocket.accept()
        if channel == "live":
            self.active_connections.append(websocket)
        elif channel == "detections":
            self.detection_connections.append(websocket)

    def disconnect(self, websocket: WebSocket, channel: str = "live"):
        if channel == "live" and websocket in self.active_connections:
            self.active_connections.remove(websocket)
        elif channel == "detections" and websocket in self.detection_connections:
            self.detection_connections.remove(websocket)

    async def broadcast(self, data: dict, channel: str = "live"):
        connections = self.active_connections if channel == "live" else self.detection_connections
        dead = []
        for conn in connections:
            try:
                await conn.send_json(data)
            except:
                dead.append(conn)
        for conn in dead:
            self.disconnect(conn, channel)

manager = ConnectionManager()

# Simulation task
_sim_task: Optional[asyncio.Task] = None
_sim_running = False


async def simulation_loop():
    """Background simulation loop — ticks the twin engine at 1 Hz."""
    global _sim_running
    _sim_running = True
    while _sim_running:
        try:
            state = twin_engine.tick(dt_s=1.0)
            await manager.broadcast(state.to_dict(), "live")
            
            # Save snapshot every 30 ticks
            if state.tick % 30 == 0:
                try:
                    session = get_session(db_engine)
                    from database.repository import save_snapshot
                    save_snapshot(session, state)
                    session.close()
                except Exception as e:
                    logger.error(f"DB save error: {e}")
            
            await asyncio.sleep(1.0)
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error(f"Simulation error: {e}")
            await asyncio.sleep(1.0)


@app.on_event("startup")
async def startup():
    global _sim_task
    _sim_task = asyncio.create_task(simulation_loop())
    logger.info("IRIS Digital Twin simulation started")


@app.on_event("shutdown")
async def shutdown():
    global _sim_running, _sim_task
    _sim_running = False
    if _sim_task:
        _sim_task.cancel()


# ── Serve static files ──
webar_path = Path("webar")
if webar_path.exists():
    app.mount("/static", StaticFiles(directory="webar"), name="static")


# ── Routes ──

@app.get("/", response_class=HTMLResponse)
async def root():
    """Serve the dashboard."""
    index_path = Path("webar/index.html")
    if index_path.exists():
        return FileResponse(str(index_path))
    return HTMLResponse("<h1>IRIS Digital Twin</h1><p>Dashboard not found. Place index.html in webar/</p>")


@app.get("/api/health")
async def health_check():
    return {
        "status": "healthy",
        "service": "IRIS Digital Twin",
        "version": "1.0.0-mvp",
        "simulation_mode": twin_engine.damage_detector.is_simulation_mode,
        "tick": twin_engine.state.tick,
    }


@app.get("/api/state")
async def get_state():
    """Get current twin state."""
    return twin_engine.state.to_dict()


class StepRequest(BaseModel):
    dt_s: float = 1.0

@app.post("/api/step")
async def step(req: StepRequest):
    """Manually advance simulation."""
    state = twin_engine.tick(dt_s=req.dt_s)
    await manager.broadcast(state.to_dict(), "live")
    return state.to_dict()


@app.get("/api/history")
async def get_history(limit: int = 100):
    """Get historical snapshots."""
    try:
        session = get_session(db_engine)
        from database.repository import get_history as db_get_history
        history = db_get_history(session, limit=limit)
        session.close()
        return {"history": history}
    except Exception as e:
        return {"history": [], "error": str(e)}


@app.get("/api/sensors/lifetime")
async def sensor_lifetimes():
    """Get sensor lifetime KPIs."""
    return {"sensors": twin_engine.sensor_tracker.get_all()}


class ScenarioRequest(BaseModel):
    speed_mps: float = 3.15
    load_fraction: float = 1.0
    ambient_temp_c: float = 35.0
    duration_hours: float = 100.0

@app.post("/api/scenario")
async def run_scenario(req: ScenarioRequest):
    """Run a what-if scenario."""
    result = scenario_engine.run_scenario(
        speed_mps=req.speed_mps,
        load_fraction=req.load_fraction,
        ambient_temp_c=req.ambient_temp_c,
        duration_hours=req.duration_hours,
    )
    return result


class MaintenanceRequest(BaseModel):
    event_type: str
    description: str
    performed_by: str = ""

@app.post("/api/maintenance-events")
async def log_maintenance(req: MaintenanceRequest):
    """Log a maintenance event."""
    try:
        session = get_session(db_engine)
        from database.repository import log_maintenance_event
        result = log_maintenance_event(
            session, req.event_type, req.description, req.performed_by,
            twin_engine.state.health_score, twin_engine.state.health_score
        )
        session.close()
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── Fault injection ──

@app.post("/api/faults/overload")
async def fault_overload():
    return twin_engine.inject_fault('overload')

@app.post("/api/faults/tear")
async def fault_tear():
    return twin_engine.inject_fault('tear')

@app.post("/api/faults/crack")
async def fault_crack():
    return twin_engine.inject_fault('crack')

@app.post("/api/faults/surface")
async def fault_surface():
    return twin_engine.inject_fault('surface')

@app.post("/api/faults/splice")
async def fault_splice():
    return twin_engine.inject_fault('splice')

@app.post("/api/faults/edge")
async def fault_edge():
    return twin_engine.inject_fault('edge')

@app.post("/api/faults/bearing")
async def fault_bearing():
    return twin_engine.inject_fault('bearing')

@app.post("/api/faults/reset")
async def fault_reset():
    return twin_engine.reset_faults()

@app.post("/api/faults/{fault_type}")
async def fault_generic(fault_type: str):
    return twin_engine.inject_fault(fault_type)


# ── Diagnostic Report Endpoints ──

@app.get("/api/report/html", response_class=HTMLResponse)
async def get_report_html():
    """Return full standalone HTML diagnostic report."""
    state_dict = twin_engine.state.to_dict()
    html_content = generate_html_report(state_dict)
    return HTMLResponse(content=html_content)


@app.get("/api/report/pdf")
async def get_report_pdf():
    """Generate and download PDF diagnostic report."""
    state_dict = twin_engine.state.to_dict()
    pdf_bytes = generate_pdf_report(state_dict)
    filename = f"IRIS_Inspection_Report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )


@app.get("/api/report/jpeg")
async def get_report_jpeg():
    """Generate and download high-resolution JPEG diagnostic summary sheet."""
    state_dict = twin_engine.state.to_dict()
    jpeg_bytes = generate_jpeg_report(state_dict)
    filename = f"IRIS_Diagnostic_Sheet_{datetime.now().strftime('%Y%m%d_%H%M%S')}.jpeg"
    return Response(
        content=jpeg_bytes,
        media_type="image/jpeg",
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )


@app.post("/api/report/generate")
async def generate_and_save_report():
    """Generate and persist HTML, PDF, and JPEG report snapshot to disk."""
    state_dict = twin_engine.state.to_dict()
    result = save_report_snapshot(state_dict)
    return result


@app.get("/api/report/list")
async def list_reports():
    """List all saved historical diagnostic reports."""
    reports = list_saved_reports()
    return {"reports": reports}


@app.get("/api/report/download/{filename}")
async def download_saved_report(filename: str):
    """Download an archived report file by filename."""
    file_path = Path("data/reports") / filename
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="Report file not found")
    
    media_type = "application/octet-stream"
    if filename.endswith(".html"):
        media_type = "text/html"
    elif filename.endswith(".pdf"):
        media_type = "application/pdf"
    elif filename.endswith(".jpeg") or filename.endswith(".jpg"):
        media_type = "image/jpeg"
        
    return FileResponse(str(file_path), media_type=media_type, filename=filename)


# ── Detection endpoints ──

@app.post("/api/detect/frame")
async def detect_frame(frame: UploadFile = File(...)):
    """Single-frame detection."""
    import cv2
    
    contents = await frame.read()
    nparr = np.frombuffer(contents, np.uint8)
    img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
    
    if img is None:
        raise HTTPException(status_code=400, detail="Cannot decode image")
    
    detections, inference_ms, annotated = twin_engine.damage_detector.detect(img)
    
    # Feed detections into twin pipeline
    for det in detections:
        event = DamageEvent(
            type=det.class_name,
            confidence=det.confidence,
            severity=det.severity,
            length_cm=det.length_cm,
            rul_impact_hours=det.rul_impact_hours,
            source="live",
        )
        twin_engine.inject_damage_event(event)
    
    # Encode annotated frame
    annotated_b64 = None
    if annotated is not None:
        _, buffer = cv2.imencode('.jpg', annotated)
        annotated_b64 = base64.b64encode(buffer).decode('utf-8')
    
    return {
        "detections": [
            {
                "class_id": d.class_id,
                "class_name": d.class_name,
                "confidence": d.confidence,
                "bbox_xyxy": d.bbox_xyxy,
                "severity": d.severity,
                "length_cm": d.length_cm,
                "rul_impact_hours": d.rul_impact_hours,
            }
            for d in detections
        ],
        "inference_ms": inference_ms,
        "frame_annotated_b64": annotated_b64,
    }


# Video processing jobs
_video_jobs = {}

class SyncDamageRequest(BaseModel):
    class_name: str
    confidence: float = 0.9
    severity: str = "MODERATE"
    length_cm: float = 10.0
    rul_impact_hours: float = 12.0
    source: str = "video_playback"

@app.post("/api/detect/sync-twin")
async def sync_damage_to_twin(req: SyncDamageRequest):
    """Sync a live defect detected in video playback to the Digital Twin."""
    from twin.state import DamageEvent
    import uuid
    
    event_id = f"evt-{uuid.uuid4().hex[:6]}"
    dmg = DamageEvent(
        id=event_id,
        type=req.class_name,
        confidence=req.confidence,
        severity=req.severity,
        length_cm=req.length_cm,
        rul_impact_hours=req.rul_impact_hours,
        source=req.source,
    )
    twin_engine.inject_damage_event(dmg)
    
    # Save to database
    try:
        session = get_session(db_engine)
        from database.repository import save_detection_event
        save_detection_event(session, {
            'id': event_id,
            'type': req.class_name,
            'confidence': req.confidence,
            'severity': req.severity,
            'length_cm': req.length_cm,
            'rul_impact_hours': req.rul_impact_hours,
        }, source=req.source)
        session.close()
    except Exception as e:
        logger.error(f"Error saving synced detection to DB: {e}")
        
    state = twin_engine.state.to_dict()
    await manager.broadcast(state, "live")
    return {"status": "synced", "event_id": event_id, "state": state}


@app.get("/api/detect/sample-videos")
async def list_sample_videos():
    """List available sample videos from data/uploads."""
    samples = []
    uploads_dir = Path("data/uploads")
    if uploads_dir.exists():
        for f in uploads_dir.glob("*.mp4"):
            samples.append({
                "filename": f.name,
                "size_mb": round(f.stat().st_size / (1024 * 1024), 2),
                "path": str(f).replace("\\", "/"),
            })
    return {"samples": samples}


@app.post("/api/detect/load-sample")
async def load_sample_video(filename: str = Form(...), frame_skip: int = Form(5), conf_threshold: float = Form(0.12)):
    """Process an existing sample video in data/uploads without re-uploading."""
    import cv2
    import uuid
    
    video_path = f"data/uploads/{filename}"
    if not os.path.exists(video_path):
        raise HTTPException(status_code=404, detail="Sample video file not found")
        
    job_id = f"vid-{uuid.uuid4().hex[:8]}"
    cap = cv2.VideoCapture(video_path)
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    fps = float(cap.get(cv2.CAP_PROP_FPS) or 30.0)
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 1280)
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 720)
    cap.release()
    
    _video_jobs[job_id] = {
        'job_id': job_id,
        'status': 'processing',
        'total_frames': total_frames,
        'processed_frames': 0,
        'progress_pct': 0,
        'unique_events': 0,
        'total_detections': 0,
        'events': [],
        'summary': None,
        'video_path': video_path,
        'frame_skip': frame_skip,
        'conf_threshold': conf_threshold,
        'fps': fps,
        'width': width,
        'height': height,
        'duration_s': round(total_frames / max(fps, 1.0), 2),
    }
    
    asyncio.create_task(_process_video(job_id))
    return {
        "job_id": job_id,
        "status": "processing",
        "total_frames": total_frames,
        "fps": fps,
        "duration_s": round(total_frames / max(fps, 1.0), 2),
    }


@app.post("/api/detect/video")
async def detect_video(video: UploadFile = File(...), frame_skip: int = Form(5), conf_threshold: float = Form(0.12)):
    """Upload and process a video."""
    import cv2
    import uuid
    
    job_id = f"vid-{uuid.uuid4().hex[:8]}"
    
    # Save uploaded file
    os.makedirs("data/uploads", exist_ok=True)
    video_path = f"data/uploads/{job_id}_{video.filename}"
    
    contents = await video.read()
    with open(video_path, 'wb') as f:
        f.write(contents)
    
    # Get total frames and video properties
    cap = cv2.VideoCapture(video_path)
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    fps = float(cap.get(cv2.CAP_PROP_FPS) or 30.0)
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 1280)
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 720)
    cap.release()
    
    _video_jobs[job_id] = {
        'job_id': job_id,
        'status': 'processing',
        'total_frames': total_frames,
        'processed_frames': 0,
        'progress_pct': 0,
        'unique_events': 0,
        'total_detections': 0,
        'events': [],
        'summary': None,
        'video_path': video_path,
        'frame_skip': frame_skip,
        'conf_threshold': conf_threshold,
        'fps': fps,
        'width': width,
        'height': height,
        'duration_s': round(total_frames / max(fps, 1.0), 2),
    }
    
    # Start background processing
    asyncio.create_task(_process_video(job_id))
    
    return {
        "job_id": job_id,
        "status": "processing",
        "total_frames": total_frames,
        "fps": fps,
        "duration_s": round(total_frames / max(fps, 1.0), 2),
    }


async def _process_video(job_id: str):
    """Background video processing with database persistence."""
    import cv2
    import uuid
    from database.repository import save_detection_event
    
    job = _video_jobs[job_id]
    cap = cv2.VideoCapture(job['video_path'])
    frame_skip = max(1, job['frame_skip'])
    conf_threshold = float(job.get('conf_threshold', 0.12))
    fps = max(float(job.get('fps', 30.0)), 1.0)
    width = job.get('width', 1280)
    height = job.get('height', 720)
    
    frame_idx = 0
    all_detections = []
    type_counts = {}
    worst_severity = "NONE"
    total_rul_impact = 0.0
    severity_order = ["NONE", "MINOR", "MODERATE", "SEVERE", "CRITICAL"]
    
    db_session = None
    try:
        db_session = get_session(db_engine)
    except Exception as e:
        logger.error(f"Failed to open DB session for video job {job_id}: {e}")
        
    while cap.isOpened():
        ret, frame = cap.read()
        if not ret:
            break
        
        if frame_idx % frame_skip == 0:
            detections, _, _ = twin_engine.damage_detector.detect(frame, conf_threshold=conf_threshold)
            
            for det in detections:
                time_s = round(frame_idx / fps, 3)
                det_id = f"vid-{job_id[-4:]}-f{frame_idx}-{uuid.uuid4().hex[:4]}"
                
                det_record = {
                    'id': det_id,
                    'frame': frame_idx,
                    'time_s': time_s,
                    'class_name': det.class_name,
                    'confidence': round(det.confidence, 3),
                    'severity': det.severity,
                    'length_cm': round(det.length_cm, 1),
                    'rul_impact_hours': det.rul_impact_hours,
                    'bbox_xyxy': det.bbox_xyxy,
                    'mask_polygon': getattr(det, 'mask_polygon', None),
                }
                all_detections.append(det_record)
                
                type_counts[det.class_name] = type_counts.get(det.class_name, 0) + 1
                total_rul_impact += det.rul_impact_hours
                
                if severity_order.index(det.severity) > severity_order.index(worst_severity):
                    worst_severity = det.severity
                    
                # Save detection to database for permanent storage
                if db_session:
                    try:
                        save_detection_event(db_session, {
                            'id': det_id,
                            'type': det.class_name,
                            'confidence': det.confidence,
                            'severity': det.severity,
                            'bbox_xyxy': det.bbox_xyxy,
                            'length_cm': det.length_cm,
                            'rul_impact_hours': det.rul_impact_hours,
                        }, source='video_upload', job_id=job_id, frame_index=frame_idx)
                    except Exception as err:
                        logger.warning(f"Could not persist detection event: {err}")
        
        frame_idx += 1
        job['processed_frames'] = frame_idx
        job['progress_pct'] = round((frame_idx / max(job['total_frames'], 1)) * 100, 1)
        job['total_detections'] = len(all_detections)
        job['unique_events'] = sum(type_counts.values())
        
        # Yield control every 5 frames for responsiveness
        if frame_idx % 5 == 0:
            await asyncio.sleep(0.005)
    
    cap.release()
    if db_session:
        try:
            db_session.close()
        except:
            pass
    
    job['status'] = 'completed'
    job['total_detections'] = len(all_detections)
    job['unique_events'] = sum(type_counts.values())
    job['events'] = all_detections
    job['summary'] = {
        'worst_severity': worst_severity,
        'total_rul_impact_hours': round(total_rul_impact, 1),
        'type_counts': type_counts,
        'total_detections': len(all_detections),
    }


@app.get("/api/detect/video/{job_id}")
async def get_video_status(job_id: str):
    """Get video processing job status."""
    if job_id not in _video_jobs:
        raise HTTPException(status_code=404, detail="Job not found")
    return _video_jobs[job_id]


@app.get("/api/detect/video/{job_id}/stream")
async def stream_video(job_id: str):
    """Stream uploaded/processed video for HTML5 playback with bounding boxes."""
    if job_id not in _video_jobs:
        raise HTTPException(status_code=404, detail="Job not found")
    video_path = _video_jobs[job_id]['video_path']
    if not os.path.exists(video_path):
        raise HTTPException(status_code=404, detail="Video file not found")
    return FileResponse(video_path, media_type="video/mp4")


@app.get("/api/detect/events")
async def get_detection_events(limit: int = 100, job_id: Optional[str] = None):
    """Get stored detection events from the database."""
    try:
        session = get_session(db_engine)
        from database.models import DetectionEvent
        query = session.query(DetectionEvent)
        if job_id:
            query = query.filter(DetectionEvent.job_id == job_id)
        query = query.order_by(DetectionEvent.timestamp.desc()).limit(limit)
        events = [
            {
                "id": e.id,
                "job_id": e.job_id,
                "frame_index": e.frame_index,
                "timestamp": str(e.timestamp),
                "class_name": e.class_name,
                "confidence": e.confidence,
                "severity": e.severity,
                "bbox_xyxy": [e.bbox_x1, e.bbox_y1, e.bbox_x2, e.bbox_y2],
                "length_cm": e.length_cm,
                "rul_impact_hours": e.rul_impact_hours,
                "source": e.source,
            }
            for e in query.all()
        ]
        session.close()
        return {"events": events}
    except Exception as e:
        return {"events": [], "error": str(e)}


# ── WebSocket endpoints ──

@app.websocket("/ws/live")
async def ws_live(websocket: WebSocket):
    """WebSocket for live twin state updates."""
    await manager.connect(websocket, "live")
    try:
        # Send current state immediately
        await websocket.send_json(twin_engine.state.to_dict())
        # Keep connection alive
        while True:
            data = await websocket.receive_text()
            # Client can send ping/commands
    except WebSocketDisconnect:
        manager.disconnect(websocket, "live")


@app.websocket("/ws/detections")
async def ws_detections(websocket: WebSocket):
    """WebSocket for detection event stream."""
    await manager.connect(websocket, "detections")
    try:
        while True:
            data = await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket, "detections")
