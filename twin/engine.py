"""
Digital Twin Engine — the core orchestrator.
Connects physics, Kalman filters, anomaly detection, fusion, RUL, and multi-class damage detection
into a unified, physically consistent simulation loop.
"""

import logging
import numpy as np
import yaml
from datetime import datetime, timezone
from typing import Dict, List, Optional

from twin.state import DigitalTwinState, DamageEvent
from physics.engine import PhysicsEngine, ConveyorParams
from estimation.state_estimator import StateEstimator
from ai.anomaly import AnomalyDetector
from ai.fusion import SensorFusion
from ai.rul import RULEstimator
from ai.sensor_health import SensorLifetimeTracker, BeltReplacementAdvisor
from ai.explainability import ExplainabilityEngine
from ai.damage_detection import YOLODamageDetector

logger = logging.getLogger(__name__)


class DigitalTwinEngine:
    """
    Main Digital Twin engine orchestrating all subsystems.
    
    Each tick():
    1. Physics step → predicted sensor values & belt kinematics
    2. Simulated sensor readings with smooth autocorrelated physical noise
    3. Kalman filter fusion & state estimation
    4. Anomaly detection on residuals
    5. Multi-class damage detection (real or consistent spatial belt-loop tracking)
    6. Health score fusion
    7. RUL estimation
    8. Belt advisory & DIN 22101 / IS 11592 compliance check
    9. SHAP explainability
    10. State broadcast & database snapshot
    """

    def __init__(self):
        # Load configs
        self._load_configs()
        
        # Initialize subsystems
        self.physics = PhysicsEngine()
        self.state_estimator = StateEstimator()
        self.anomaly_detector = AnomalyDetector()
        self.sensor_fusion = SensorFusion()
        self.rul_estimator = RULEstimator()
        self.belt_advisor = BeltReplacementAdvisor()
        self.explainability = ExplainabilityEngine()
        self.damage_detector = YOLODamageDetector()
        
        # Sensor lifetime tracking
        self.sensor_tracker = self._init_sensor_tracker()
        
        # State
        self._state = DigitalTwinState()
        self._tick_count = 0
        self._active_damage_events: Dict[str, DamageEvent] = {}
        self._load_fraction = 1.0
        self._speed_mps = 3.15
        
        # Smooth continuous noise state (Ornstein-Uhlenbeck continuous process)
        self._sensor_noise = {
            'tension': 0.0,
            'vibration': 0.0,
            'temperature': 0.0,
        }
        
        # Fault injection dictionary supporting all defect classes
        self._faults: Dict[str, bool] = {
            'overload': False,
            'tear': False,
            'crack': False,
            'surface': False,
            'splice': False,
            'edge': False,
            'bearing': False,
        }
        self._bearing_fault_growth = 0.0

    def _load_configs(self):
        """Load YAML configuration files."""
        try:
            with open('config/sensors.yaml', 'r') as f:
                self._sensor_config = yaml.safe_load(f).get('sensors', {})
        except Exception:
            self._sensor_config = {}

    def _init_sensor_tracker(self) -> SensorLifetimeTracker:
        """Initialize sensor lifetime tracker from config."""
        return SensorLifetimeTracker(self._sensor_config)

    def tick(self, dt_s: float = 1.0, frame: np.ndarray = None) -> DigitalTwinState:
        """
        Advance the twin by one time step with continuous physics dynamics.
        
        Args:
            dt_s: Time step in seconds
            frame: Optional camera frame for YOLO detection
            
        Returns:
            Updated DigitalTwinState
        """
        self._tick_count += 1
        
        # ── Apply operational faults ──
        load = self._load_fraction
        if self._faults['overload']:
            load = 1.45
        
        speed = self._speed_mps
        
        # ── 1. Physics step ──
        physics_state = self.physics.get_full_state(dt_s, load, speed)
        belt_pos_m = physics_state['kinematics']['position_m']
        
        # ── 2. Simulated sensor readings with smooth noise (zero erratic jumps) ──
        rng = np.random.RandomState(self._tick_count)
        
        vib_base = physics_state['vibration']['velocity_mms']
        if self._faults['bearing']:
            self._bearing_fault_growth += 0.03
            vib_base += self._bearing_fault_growth
        
        # Continuous Ornstein-Uhlenbeck smooth noise evolution
        alpha = 0.30
        self._sensor_noise['tension'] = (1.0 - alpha) * self._sensor_noise['tension'] + alpha * float(rng.normal(0, 180.0))
        self._sensor_noise['vibration'] = (1.0 - alpha) * self._sensor_noise['vibration'] + alpha * float(rng.normal(0, 0.06))
        self._sensor_noise['temperature'] = (1.0 - alpha) * self._sensor_noise['temperature'] + alpha * float(rng.normal(0, 0.10))
        
        measurements = {
            'tension': physics_state['tension']['tight_side_N'] + self._sensor_noise['tension'],
            'vibration': vib_base + self._sensor_noise['vibration'],
            'temperature': physics_state['thermal']['current_temp_c'] + self._sensor_noise['temperature'],
        }
        
        predictions = {
            'tension': physics_state['tension']['tight_side_N'],
            'vibration': vib_base,
            'temperature': physics_state['thermal']['current_temp_c'],
        }

        # ── 3. Kalman filter ──
        kalman_result = self.state_estimator.update(measurements, predictions)
        residuals = kalman_result['residuals']

        # ── 4. Anomaly detection ──
        anomaly_score = self.anomaly_detector.update(residuals)

        # ── 5. Damage detection (anchored spatial tracking on belt loop) ──
        new_events = []
        detections, _, _ = self.damage_detector.detect(frame=frame, belt_position_m=belt_pos_m)
        for det in detections:
            event_id = det.track_id or f"evt-{det.class_name.lower()}-{self._tick_count}"
            event = DamageEvent(
                id=event_id,
                type=det.class_name,
                confidence=det.confidence,
                severity=det.severity,
                length_cm=det.length_cm,
                rul_impact_hours=det.rul_impact_hours,
                source="vision_ai" if not self.damage_detector.is_simulation_mode else "simulated_belt_loop",
            )
            self._active_damage_events[event.id] = event
            new_events.append(event)
        
        # Inject specific user-triggered faults
        if self._faults['tear'] and 'fault_tear' not in self._active_damage_events:
            tear_evt = DamageEvent(
                id='fault_tear',
                type='TEAR',
                confidence=0.96,
                severity='CRITICAL',
                length_cm=28.5,
                rul_impact_hours=-38.0,
                source='fault_injection',
            )
            self._active_damage_events[tear_evt.id] = tear_evt
            new_events.append(tear_evt)

        if self._faults['crack'] and 'fault_crack' not in self._active_damage_events:
            crack_evt = DamageEvent(
                id='fault_crack',
                type='CRACK',
                confidence=0.92,
                severity='SEVERE',
                length_cm=18.0,
                rul_impact_hours=-16.0,
                source='fault_injection',
            )
            self._active_damage_events[crack_evt.id] = crack_evt
            new_events.append(crack_evt)

        if self._faults['surface'] and 'fault_surface' not in self._active_damage_events:
            surf_evt = DamageEvent(
                id='fault_surface',
                type='SURFACE_DAMAGE',
                confidence=0.90,
                severity='MODERATE',
                length_cm=14.0,
                rul_impact_hours=-8.0,
                source='fault_injection',
            )
            self._active_damage_events[surf_evt.id] = surf_evt
            new_events.append(surf_evt)

        if self._faults['splice'] and 'fault_splice' not in self._active_damage_events:
            splice_evt = DamageEvent(
                id='fault_splice',
                type='SPLICE_GAP',
                confidence=0.94,
                severity='CRITICAL',
                length_cm=4.5,
                rul_impact_hours=-32.0,
                source='fault_injection',
            )
            self._active_damage_events[splice_evt.id] = splice_evt
            new_events.append(splice_evt)

        if self._faults['edge'] and 'fault_edge' not in self._active_damage_events:
            edge_evt = DamageEvent(
                id='fault_edge',
                type='EDGE_DAMAGE',
                confidence=0.89,
                severity='SEVERE',
                length_cm=22.0,
                rul_impact_hours=-18.0,
                source='fault_injection',
            )
            self._active_damage_events[edge_evt.id] = edge_evt
            new_events.append(edge_evt)

        all_events = list(self._active_damage_events.values())

        # ── 6. Health fusion ──
        fusion_result = self.sensor_fusion.update(anomaly_score, all_events)

        # ── 7. RUL ──
        rul_result = self.rul_estimator.update(fusion_result['health_score'], all_events)

        # ── 8. Belt advisory ──
        advisory = self.belt_advisor.advise(
            health_score=fusion_result['health_score'],
            rul_hours=rul_result['rul_hours'],
            n_damage_events=len(self._active_damage_events),
            safety_factor=physics_state['tension']['safety_factor'],
            sag_ratio_pct=physics_state['sag']['sag_ratio_pct'],
            load_fraction=load,
        )

        # ── 9. SHAP explainability ──
        shap = self.explainability.compute_shap(
            vib_residual=residuals.get('vibration', 0),
            tension_residual=residuals.get('tension', 0),
            temp_residual=residuals.get('temperature', 0),
            anomaly_score=anomaly_score,
            load_fraction=load,
            n_damage_events=len(self._active_damage_events),
        )

        # ── 10. Sensor lifetimes ──
        self.sensor_tracker.update(dt_s / 3600.0)

        # ── Build state ──
        self._state = DigitalTwinState(
            timestamp=datetime.now(timezone.utc).isoformat(),
            tick=self._tick_count,
            health_score=round(fusion_result['health_score'], 1),
            failure_probability=round(fusion_result['failure_probability'], 3),
            anomaly_score=round(anomaly_score, 3),
            dominant_severity=fusion_result['dominant_severity'],
            rul_hours=round(rul_result['rul_hours'], 1),
            rul_source=rul_result['rul_source'],
            rul_ci_lower=round(rul_result['ci_lower'], 1),
            rul_ci_upper=round(rul_result['ci_upper'], 1),
            belt_advisory=advisory['level'],
            belt_advisory_message=advisory['message'],
            belt_speed_mps=round(speed, 2),
            belt_position_m=round(belt_pos_m, 2),
            tension_tight_N=physics_state['tension']['tight_side_N'],
            tension_slack_N=physics_state['tension']['slack_side_N'],
            safety_factor=physics_state['tension']['safety_factor'],
            sag_ratio_pct=physics_state['sag']['sag_ratio_pct'],
            temperature_c=round(physics_state['thermal']['current_temp_c'], 1),
            vibration_mms=round(measurements['vibration'], 2),
            load_fraction=load,
            motor_power_kW=round(physics_state['load']['motor_power_kW'], 1),
            kalman_tension=round(kalman_result['channels']['tension']['estimated'], 1),
            kalman_vibration=round(kalman_result['channels']['vibration']['estimated'], 2),
            kalman_temperature=round(kalman_result['channels']['temperature']['estimated'], 1),
            is_compliant=physics_state['compliance']['overall_compliant'],
            n_damage_events=len(self._active_damage_events),
            active_damage_events=[e.to_dict() for e in all_events[-15:]],  # last 15
            shap_contributions=shap,
            sensor_lifetimes=self.sensor_tracker.get_all(),
            simulation_mode=self.damage_detector.is_simulation_mode,
        )

        return self._state

    @property
    def state(self) -> DigitalTwinState:
        return self._state

    def inject_fault(self, fault_type: str) -> dict:
        """Inject a fault for demo/testing across all supported classes."""
        norm = fault_type.lower().strip()
        if norm in self._faults:
            self._faults[norm] = True
            return {'status': 'injected', 'fault': norm}
        # Support synonyms
        if norm in ('crack', 'cracks'):
            self._faults['crack'] = True
            return {'status': 'injected', 'fault': 'crack'}
        if norm in ('surface_damage', 'surface_wear', 'damage'):
            self._faults['surface'] = True
            return {'status': 'injected', 'fault': 'surface'}
        if norm in ('splice_gap', 'splice'):
            self._faults['splice'] = True
            return {'status': 'injected', 'fault': 'splice'}
        if norm in ('edge_damage', 'edge'):
            self._faults['edge'] = True
            return {'status': 'injected', 'fault': 'edge'}
        return {'status': 'unknown_fault', 'fault': fault_type}

    def reset_faults(self) -> dict:
        """Clear all injected faults."""
        for k in self._faults:
            self._faults[k] = False
        self._bearing_fault_growth = 0.0
        
        # Remove fault-injected damage events
        self._active_damage_events = {
            k: v for k, v in self._active_damage_events.items()
            if v.source != 'fault_injection'
        }
        
        # Reset fusion & RUL
        self.sensor_fusion.reset()
        self.rul_estimator.reset()
        
        return {'status': 'all_faults_cleared'}

    def inject_damage_event(self, event: DamageEvent):
        """Directly inject a damage event into the twin pipeline."""
        self._active_damage_events[event.id] = event
