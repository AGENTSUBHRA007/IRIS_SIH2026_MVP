"""
Health score fusion engine.
Combines anomaly score (transient) with damage events (persistent)
to produce a health score [0-100] and failure probability [0-1].
"""

from typing import Dict, List, Set, Optional
from ai.severity import Severity, health_penalty


class SensorFusion:
    """
    Fuses anomaly-based (transient) and damage-based (persistent) 
    signals into a unified health score.
    
    Key design: damage penalties are applied ONCE per unique event ID
    (prevents re-charging on every simulation tick).
    """

    _SEVERITY_HEALTH_PENALTY = {
        Severity.NONE: 0,
        Severity.MINOR: -3,
        Severity.MODERATE: -10,
        Severity.SEVERE: -25,
        Severity.CRITICAL: -45,
    }

    def __init__(self):
        self._health_score = 100.0
        self._anomaly_health = 100.0  # transient component
        self._damage_health = 100.0   # persistent component
        self._failure_probability = 0.0
        self._applied_event_ids: Set[str] = set()
        self._dominant_severity = Severity.NONE
        self._anomaly_target = 0.0

    def update(self, anomaly_score: float, damage_events: Optional[List] = None) -> Dict:
        """
        Update health score with current anomaly score and any new damage events.
        
        Args:
            anomaly_score: Current anomaly score [0, 1]
            damage_events: List of DamageEvent objects (or dicts with 'id' and 'severity')
            
        Returns:
            Dict with health_score, failure_probability, dominant_severity
        """
        # ── Anomaly component (transient, can recover) ──
        anomaly_penalty = anomaly_score * 30  # Max 30 pts from anomaly
        self._anomaly_target = 100.0 - anomaly_penalty
        # Exponential smoothing toward target
        alpha = 0.05
        self._anomaly_health += alpha * (self._anomaly_target - self._anomaly_health)

        # ── Damage component (persistent, one-time per event) ──
        if damage_events:
            for event in damage_events:
                event_id = event.id if hasattr(event, 'id') else event.get('id', '')
                if event_id and event_id not in self._applied_event_ids:
                    self._applied_event_ids.add(event_id)
                    severity_str = event.severity if hasattr(event, 'severity') else event.get('severity', 'NONE')
                    try:
                        sev = Severity(severity_str)
                    except ValueError:
                        sev = Severity.NONE
                    penalty = self._SEVERITY_HEALTH_PENALTY.get(sev, 0)
                    self._damage_health = max(0, self._damage_health + penalty)
                    
                    # Track dominant severity
                    severity_order = [Severity.NONE, Severity.MINOR, Severity.MODERATE, 
                                      Severity.SEVERE, Severity.CRITICAL]
                    if severity_order.index(sev) > severity_order.index(self._dominant_severity):
                        self._dominant_severity = sev

        # ── Final health = min of both components ──
        self._health_score = max(0.0, min(100.0,
            min(self._anomaly_health, self._damage_health)
        ))

        # ── Failure probability ──
        # Nonlinear: low health → high probability
        h = self._health_score / 100.0
        self._failure_probability = max(0.0, min(1.0, 
            1.0 - h ** 1.5
        ))

        return {
            'health_score': round(self._health_score, 1),
            'failure_probability': round(self._failure_probability, 3),
            'dominant_severity': self._dominant_severity.value,
            'anomaly_health': round(self._anomaly_health, 1),
            'damage_health': round(self._damage_health, 1),
            'n_damage_events': len(self._applied_event_ids),
        }

    @property
    def health_score(self) -> float:
        return self._health_score

    @property
    def failure_probability(self) -> float:
        return self._failure_probability

    @property
    def dominant_severity(self) -> str:
        return self._dominant_severity.value

    def reset(self):
        """Reset to pristine state."""
        self.__init__()
