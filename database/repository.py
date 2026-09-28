"""
Database repository — CRUD operations for twin state persistence.
"""

import json
from datetime import datetime
from typing import List, Optional
from sqlalchemy.orm import Session

from database.models import TwinSnapshot, DetectionEvent, MaintenanceEvent
from twin.state import DigitalTwinState


def save_snapshot(session: Session, state: DigitalTwinState):
    """Save a twin state snapshot to the database."""
    snapshot = TwinSnapshot(
        timestamp=datetime.utcnow(),
        tick=state.tick,
        health_score=state.health_score,
        failure_probability=state.failure_probability,
        anomaly_score=state.anomaly_score,
        rul_hours=state.rul_hours,
        rul_source=state.rul_source,
        belt_advisory=state.belt_advisory,
        temperature_c=state.temperature_c,
        vibration_mms=state.vibration_mms,
        tension_tight_N=state.tension_tight_N,
        safety_factor=state.safety_factor,
        sag_ratio_pct=state.sag_ratio_pct,
        load_fraction=state.load_fraction,
        n_damage_events=state.n_damage_events,
        is_compliant=state.is_compliant,
        state_json=json.dumps(state.to_dict()),
    )
    session.add(snapshot)
    session.commit()


def get_latest_snapshot(session: Session) -> Optional[dict]:
    """Get the most recent snapshot."""
    snap = session.query(TwinSnapshot).order_by(
        TwinSnapshot.timestamp.desc()
    ).first()
    if snap and snap.state_json:
        return json.loads(snap.state_json)
    return None


def get_history(session: Session, 
                start: datetime = None, 
                end: datetime = None,
                limit: int = 1000) -> List[dict]:
    """Get historical snapshots within a time range."""
    query = session.query(TwinSnapshot)
    if start:
        query = query.filter(TwinSnapshot.timestamp >= start)
    if end:
        query = query.filter(TwinSnapshot.timestamp <= end)
    query = query.order_by(TwinSnapshot.timestamp.desc()).limit(limit)
    
    return [
        {
            'timestamp': str(s.timestamp),
            'health_score': s.health_score,
            'rul_hours': s.rul_hours,
            'anomaly_score': s.anomaly_score,
            'temperature_c': s.temperature_c,
            'vibration_mms': s.vibration_mms,
        }
        for s in query.all()
    ]


def save_detection_event(session: Session, event: dict, source: str = 'live',
                          job_id: str = None, frame_index: int = None):
    """Save a detection event."""
    bbox = event.get('bbox_xyxy', [0, 0, 0, 0])
    det = DetectionEvent(
        id=event.get('id', ''),
        job_id=job_id,
        frame_index=frame_index,
        class_name=event.get('type', event.get('class_name', 'UNKNOWN')),
        confidence=event.get('confidence', 0),
        severity=event.get('severity', 'NONE'),
        bbox_x1=bbox[0] if len(bbox) > 0 else 0,
        bbox_y1=bbox[1] if len(bbox) > 1 else 0,
        bbox_x2=bbox[2] if len(bbox) > 2 else 0,
        bbox_y2=bbox[3] if len(bbox) > 3 else 0,
        length_cm=event.get('length_cm', 0),
        rul_impact_hours=event.get('rul_impact_hours', 0),
        source=source,
    )
    session.add(det)
    session.commit()


def log_maintenance_event(session: Session, event_type: str, 
                           description: str, performed_by: str = "",
                           health_before: float = 0, health_after: float = 0):
    """Log a maintenance event."""
    evt = MaintenanceEvent(
        event_type=event_type,
        description=description,
        performed_by=performed_by,
        health_before=health_before,
        health_after=health_after,
    )
    session.add(evt)
    session.commit()
    return {'id': evt.id, 'status': 'logged'}
