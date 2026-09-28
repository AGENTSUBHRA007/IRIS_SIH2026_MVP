"""
AI Explainability — SHAP-style feature attribution.
Computed from live Kalman-filter residuals, not hardcoded strings.
"""

from typing import Dict, List, Optional
import numpy as np


class ExplainabilityEngine:
    """
    Computes SHAP-like feature contributions from live system state.
    All features normalized to 100% total; sorted by |contribution| descending.
    """

    def compute_shap(self,
                     vib_residual: float = 0.0,
                     tension_residual: float = 0.0,
                     temp_residual: float = 0.0,
                     anomaly_score: float = 0.0,
                     load_fraction: float = 1.0,
                     n_damage_events: int = 0,
                     expected_vibration: float = 5.0,
                     expected_tension: float = 50000.0,
                     expected_temperature: float = 50.0) -> List[Dict]:
        """
        Compute feature contributions to risk.
        
        Returns:
            List of {feature, contribution, direction} sorted by |contribution| desc.
        """
        raw = {
            'Vibration RMS trend': min(1.0, abs(vib_residual) / max(expected_vibration, 1e-9)),
            'Belt tension deviation': min(1.0, abs(tension_residual) / max(expected_tension, 1e-9)),
            'Thermal residual': min(1.0, abs(temp_residual) / max(expected_temperature, 1e-9)),
            'Sensor anomaly score': min(1.0, anomaly_score),
            'Material overload': max(0.0, load_fraction - 1.0),
            'AI-detected damage events': min(1.0, n_damage_events / 10.0),
        }

        # Normalize to 100%
        total = sum(raw.values())
        if total < 1e-9:
            # No contributions — equal split
            n = len(raw)
            return [
                {'feature': k, 'contribution': round(1.0 / n, 3), 'direction': 'neutral'}
                for k in raw
            ]

        features = []
        for name, val in raw.items():
            normalized = val / total
            direction = 'risk' if val > 0.1 else 'protective' if val < 0.05 else 'neutral'
            features.append({
                'feature': name,
                'contribution': round(normalized, 3),
                'raw_value': round(val, 4),
                'direction': direction,
            })

        features.sort(key=lambda x: abs(x['contribution']), reverse=True)
        return features
