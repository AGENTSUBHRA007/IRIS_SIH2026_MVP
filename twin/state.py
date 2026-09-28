"""
Digital Twin State — data model for the complete twin state.
"""

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, Optional


@dataclass
class DamageEvent:
    """A detected damage event flowing through the twin pipeline."""
    id: str = ""
    type: str = "UNKNOWN"
    confidence: float = 0.0
    severity: str = "NONE"
    position_m: List[float] = field(default_factory=lambda: [0.0, 0.0, 1.0])
    length_cm: float = 0.0
    rul_impact_hours: float = 0.0
    detected_at: str = ""
    source: str = "simulated"  # "live" | "video_upload" | "simulated"

    def __post_init__(self):
        if not self.id:
            self.id = f"DMG-{uuid.uuid4().hex[:12]}"
        if not self.detected_at:
            self.detected_at = datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> dict:
        return {
            'id': self.id,
            'type': self.type,
            'confidence': self.confidence,
            'severity': self.severity,
            'position_m': self.position_m,
            'length_cm': self.length_cm,
            'rul_impact_hours': self.rul_impact_hours,
            'detected_at': self.detected_at,
            'source': self.source,
        }


@dataclass
class DigitalTwinState:
    """Complete state of the Digital Twin at a point in time."""
    timestamp: str = ""
    tick: int = 0
    
    # Health & AI
    health_score: float = 100.0
    failure_probability: float = 0.0
    anomaly_score: float = 0.0
    dominant_severity: str = "NONE"
    
    # RUL
    rul_hours: float = 500.0
    rul_source: str = "damage_budget"
    rul_ci_lower: float = 400.0
    rul_ci_upper: float = 600.0
    
    # Belt advisory
    belt_advisory: str = "NORMAL"
    belt_advisory_message: str = ""
    
    # Physics
    belt_speed_mps: float = 3.15
    belt_position_m: float = 0.0
    tension_tight_N: float = 0.0
    tension_slack_N: float = 0.0
    safety_factor: float = 10.0
    sag_ratio_pct: float = 1.0
    temperature_c: float = 35.0
    vibration_mms: float = 3.0
    
    # Load
    load_fraction: float = 1.0
    motor_power_kW: float = 0.0
    
    # Kalman
    kalman_tension: float = 0.0
    kalman_vibration: float = 0.0
    kalman_temperature: float = 0.0
    
    # Compliance
    is_compliant: bool = True
    
    # Damage events
    n_damage_events: int = 0
    active_damage_events: List[dict] = field(default_factory=list)
    
    # SHAP
    shap_contributions: List[dict] = field(default_factory=list)
    
    # Sensor lifetimes
    sensor_lifetimes: List[dict] = field(default_factory=list)
    
    # Simulation mode
    simulation_mode: bool = True

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> dict:
        return {
            'timestamp': self.timestamp,
            'tick': self.tick,
            'health_score': self.health_score,
            'failure_probability': self.failure_probability,
            'anomaly_score': self.anomaly_score,
            'dominant_severity': self.dominant_severity,
            'rul_hours': self.rul_hours,
            'rul_source': self.rul_source,
            'rul_ci_lower': self.rul_ci_lower,
            'rul_ci_upper': self.rul_ci_upper,
            'belt_advisory': self.belt_advisory,
            'belt_advisory_message': self.belt_advisory_message,
            'belt_speed_mps': self.belt_speed_mps,
            'belt_position_m': self.belt_position_m,
            'tension_tight_N': self.tension_tight_N,
            'tension_slack_N': self.tension_slack_N,
            'safety_factor': self.safety_factor,
            'sag_ratio_pct': self.sag_ratio_pct,
            'temperature_c': self.temperature_c,
            'vibration_mms': self.vibration_mms,
            'load_fraction': self.load_fraction,
            'motor_power_kW': self.motor_power_kW,
            'kalman_tension': self.kalman_tension,
            'kalman_vibration': self.kalman_vibration,
            'kalman_temperature': self.kalman_temperature,
            'is_compliant': self.is_compliant,
            'n_damage_events': self.n_damage_events,
            'active_damage_events': self.active_damage_events,
            'shap_contributions': self.shap_contributions,
            'sensor_lifetimes': self.sensor_lifetimes,
            'simulation_mode': self.simulation_mode,
        }
