"""
Sensor health monitoring and belt replacement advisory.
"""

from enum import Enum
from dataclasses import dataclass, field
from typing import Dict, List, Optional
from datetime import datetime, timedelta


class AdvisoryLevel(str, Enum):
    NORMAL = "NORMAL"
    PLAN_INSPECTION = "PLAN_INSPECTION"
    SCHEDULE_REPLACEMENT = "SCHEDULE_REPLACEMENT"
    IMMEDIATE_REPLACEMENT = "IMMEDIATE_REPLACEMENT"


class SensorStatus(str, Enum):
    GOOD = "GOOD"
    REPLACE_SOON = "REPLACE_SOON"
    REPLACE_NOW = "REPLACE_NOW"


@dataclass
class SensorLifetime:
    """Lifetime tracking for a single sensor."""
    sensor_id: str
    sensor_type: str
    location: str
    rated_life_hours: float
    elapsed_hours: float = 0.0
    status: SensorStatus = SensorStatus.GOOD
    estimated_eol: Optional[str] = None

    @property
    def remaining_pct(self) -> float:
        if self.rated_life_hours <= 0:
            return 0.0
        return max(0, (1.0 - self.elapsed_hours / self.rated_life_hours)) * 100

    def update(self, dt_hours: float):
        """Update elapsed hours and recalculate status."""
        self.elapsed_hours += dt_hours
        remaining = self.remaining_pct

        if remaining > 30:
            self.status = SensorStatus.GOOD
        elif remaining > 10:
            self.status = SensorStatus.REPLACE_SOON
        else:
            self.status = SensorStatus.REPLACE_NOW

        # Project EOL date
        if self.rated_life_hours > self.elapsed_hours:
            hours_left = self.rated_life_hours - self.elapsed_hours
            eol = datetime.utcnow() + timedelta(hours=hours_left)
            self.estimated_eol = eol.isoformat()

    def to_dict(self) -> dict:
        return {
            'sensor_id': self.sensor_id,
            'sensor_type': self.sensor_type,
            'location': self.location,
            'rated_life_hours': self.rated_life_hours,
            'elapsed_hours': round(self.elapsed_hours, 1),
            'remaining_pct': round(self.remaining_pct, 1),
            'status': self.status.value,
            'estimated_eol': self.estimated_eol,
        }


class SensorLifetimeTracker:
    """Tracks lifetime for all registered sensors."""

    def __init__(self, sensor_config: Dict):
        self.sensors: Dict[str, SensorLifetime] = {}
        for sid, cfg in sensor_config.items():
            self.sensors[sid] = SensorLifetime(
                sensor_id=sid,
                sensor_type=cfg.get('type', 'unknown'),
                location=cfg.get('location', 'unknown'),
                rated_life_hours=cfg.get('rated_life_hours', 10000),
            )

    def update(self, dt_hours: float):
        """Update all sensor lifetimes."""
        for sensor in self.sensors.values():
            sensor.update(dt_hours)

    def get_all(self) -> List[dict]:
        return [s.to_dict() for s in self.sensors.values()]


class BeltReplacementAdvisor:
    """
    Advisory system for belt replacement decisions.
    Considers health score, RUL, damage events, safety factor, and sag ratio.
    """

    def advise(self,
               health_score: float = 100.0,
               rul_hours: float = 500.0,
               n_damage_events: int = 0,
               safety_factor: float = 10.0,
               sag_ratio_pct: float = 1.0,
               load_fraction: float = 1.0) -> Dict:
        """
        Generate belt replacement advisory.
        
        Returns:
            Dict with level, message, urgency_color
        """
        level = AdvisoryLevel.NORMAL
        reasons = []

        # Check IMMEDIATE_REPLACEMENT conditions
        if (health_score < 30 or rul_hours < 24 or n_damage_events >= 3 
            or safety_factor < 7.0 or sag_ratio_pct > 3.0):
            level = AdvisoryLevel.IMMEDIATE_REPLACEMENT
            if health_score < 30:
                reasons.append(f"Health critically low ({health_score:.0f}%)")
            if rul_hours < 24:
                reasons.append(f"RUL < 24h ({rul_hours:.0f}h)")
            if n_damage_events >= 3:
                reasons.append(f"{n_damage_events} damage events detected")
            if safety_factor < 7.0:
                reasons.append(f"Safety factor below 7× ({safety_factor:.1f}×)")
            if sag_ratio_pct > 3.0:
                reasons.append(f"Sag exceeds 3% ({sag_ratio_pct:.1f}%)")

        # SCHEDULE_REPLACEMENT
        elif (health_score < 50 or rul_hours < 72 or n_damage_events >= 2
              or (7.0 <= safety_factor < 9.0)):
            level = AdvisoryLevel.SCHEDULE_REPLACEMENT
            if health_score < 50:
                reasons.append(f"Health declining ({health_score:.0f}%)")
            if rul_hours < 72:
                reasons.append(f"RUL approaching limit ({rul_hours:.0f}h)")
            if n_damage_events >= 2:
                reasons.append(f"{n_damage_events} damage events")

        # PLAN_INSPECTION
        elif (health_score < 70 or rul_hours < 240 or n_damage_events >= 1
              or load_fraction > 1.1):
            level = AdvisoryLevel.PLAN_INSPECTION
            if health_score < 70:
                reasons.append(f"Health below threshold ({health_score:.0f}%)")
            if n_damage_events >= 1:
                reasons.append(f"{n_damage_events} damage event(s)")
            if load_fraction > 1.1:
                reasons.append(f"Overload detected ({load_fraction:.1%})")

        else:
            reasons.append("All parameters within IS 11592 limits")

        urgency_colors = {
            AdvisoryLevel.NORMAL: "#34d399",
            AdvisoryLevel.PLAN_INSPECTION: "#60a5fa",
            AdvisoryLevel.SCHEDULE_REPLACEMENT: "#fbbf24",
            AdvisoryLevel.IMMEDIATE_REPLACEMENT: "#ef4444",
        }

        return {
            'level': level.value,
            'message': "; ".join(reasons),
            'urgency_color': urgency_colors[level],
            'reasons': reasons,
        }
