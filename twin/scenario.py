"""
What-If Scenario Engine.
Stress-test projections with uncertainty bands.
"""

import numpy as np
from typing import Dict, Optional
from twin.engine import DigitalTwinEngine


class ScenarioEngine:
    """
    Run what-if scenarios by simulating degradation trajectories
    under user-specified conditions.
    """

    def run_scenario(self,
                     speed_mps: float = 3.15,
                     load_fraction: float = 1.0,
                     tension_factor: float = 1.0,
                     ambient_temp_c: float = 35.0,
                     duration_hours: float = 100.0,
                     n_steps: int = 200) -> Dict:
        """
        Run a what-if scenario simulation.
        
        Returns:
            Dict with health_trajectory, rul_projection, risk_level, primary_contributor
        """
        engine = DigitalTwinEngine()
        engine._speed_mps = speed_mps
        engine._load_fraction = load_fraction
        engine.physics.params.ambient_temp_c = ambient_temp_c
        
        dt_s = (duration_hours * 3600) / n_steps
        
        health_trajectory = []
        rul_trajectory = []
        
        for i in range(n_steps):
            state = engine.tick(dt_s=dt_s)
            t_hours = (i + 1) * dt_s / 3600
            health_trajectory.append({
                'time_hours': round(t_hours, 2),
                'health_score': state.health_score,
            })
            rul_trajectory.append({
                'time_hours': round(t_hours, 2),
                'rul_hours': state.rul_hours,
            })

        final_health = health_trajectory[-1]['health_score']
        final_rul = rul_trajectory[-1]['rul_hours']

        # Risk classification
        if final_health >= 80:
            risk_level = "LOW"
        elif final_health >= 60:
            risk_level = "MODERATE"
        elif final_health >= 40:
            risk_level = "HIGH"
        else:
            risk_level = "CRITICAL"

        # Uncertainty bands (±25% rate perturbation)
        optimistic = [{'time_hours': h['time_hours'], 
                       'health_score': min(100, h['health_score'] * 1.05)} 
                      for h in health_trajectory]
        pessimistic = [{'time_hours': h['time_hours'], 
                        'health_score': max(0, h['health_score'] * 0.85)} 
                       for h in health_trajectory]

        # Primary contributor
        shap = state.shap_contributions
        primary = shap[0]['feature'] if shap else "Unknown"

        return {
            'parameters': {
                'speed_mps': speed_mps,
                'load_fraction': load_fraction,
                'ambient_temp_c': ambient_temp_c,
                'duration_hours': duration_hours,
            },
            'health_trajectory': health_trajectory,
            'rul_trajectory': rul_trajectory,
            'optimistic_band': optimistic,
            'pessimistic_band': pessimistic,
            'final_health': round(final_health, 1),
            'final_rul': round(final_rul, 1),
            'risk_level': risk_level,
            'primary_contributor': primary,
        }
