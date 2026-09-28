"""
Anomaly detection using rolling z-score on Kalman filter residuals.
Deliberately NOT deep learning — auditable, transparent, replaceable.
"""

import numpy as np
from collections import deque
from typing import Dict, Tuple


class AnomalyDetector:
    """
    Rolling z-score anomaly detection across sensor channels.
    
    Fuses per-channel z-scores into a single anomaly score [0, 1]
    using weighted combination → sigmoid.
    """

    _WEIGHTS = {
        'tension': 0.4,
        'vibration': 0.4,
        'temperature': 0.2,
    }

    def __init__(self, window: int = 200):
        self.window = window
        self._histories: Dict[str, deque] = {
            ch: deque(maxlen=window) for ch in self._WEIGHTS
        }
        self._anomaly_score = 0.0

    def update(self, residuals: Dict[str, float]) -> float:
        """
        Update with new Kalman residuals and compute anomaly score.
        
        Args:
            residuals: Dict of {channel: residual_value}
            
        Returns:
            anomaly_score in [0, 1]
        """
        z_scores = {}

        for channel, weight in self._WEIGHTS.items():
            residual = residuals.get(channel, 0.0)
            history = self._histories[channel]
            history.append(residual)

            if len(history) >= 10:
                arr = np.array(history)
                mean = np.mean(arr)
                std = np.std(arr)
                if std > 1e-9:
                    z_scores[channel] = abs((residual - mean) / std)
                else:
                    z_scores[channel] = 0.0
            else:
                z_scores[channel] = 0.0

        # Weighted combination
        weighted_sum = sum(
            self._WEIGHTS[ch] * z_scores.get(ch, 0.0)
            for ch in self._WEIGHTS
        )

        # Sigmoid mapping to [0, 1]
        # Tuned so z=2 → ~0.5, z=4 → ~0.88
        self._anomaly_score = 1.0 / (1.0 + np.exp(-1.5 * (weighted_sum - 2.0)))

        return self._anomaly_score

    @property
    def score(self) -> float:
        return self._anomaly_score

    @property
    def channel_scores(self) -> Dict[str, float]:
        """Get per-channel z-scores for debugging."""
        result = {}
        for ch in self._WEIGHTS:
            history = self._histories[ch]
            if len(history) >= 10:
                arr = np.array(history)
                mean, std = np.mean(arr), np.std(arr)
                if std > 1e-9:
                    result[ch] = abs((arr[-1] - mean) / std)
                else:
                    result[ch] = 0.0
            else:
                result[ch] = 0.0
        return result
