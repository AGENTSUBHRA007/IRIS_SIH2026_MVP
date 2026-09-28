"""
Multi-channel state estimator using Kalman filters.
Fuses sensor measurements with physics predictions per channel.
"""

from typing import Dict
from estimation.kalman import ScalarKalmanFilter


class StateEstimator:
    """
    Manages Kalman filters for tension, vibration, and temperature channels.
    """

    def __init__(self, process_noise=0.01, measurement_noise=0.1):
        self.filters: Dict[str, ScalarKalmanFilter] = {
            'tension': ScalarKalmanFilter(process_noise, measurement_noise, 50000, 1.0),
            'vibration': ScalarKalmanFilter(process_noise, measurement_noise * 0.5, 3.0, 1.0),
            'temperature': ScalarKalmanFilter(process_noise * 0.5, measurement_noise, 45.0, 1.0),
        }

    def update(self, measurements: Dict[str, float], 
               predictions: Dict[str, float] = None) -> Dict:
        """
        Update all channels with measurements and optional physics predictions.
        
        Returns:
            Dict of {channel: {estimated, residual}} 
        """
        results = {}
        residuals = {}
        
        for channel, kf in self.filters.items():
            measurement = measurements.get(channel, kf.estimate)
            prediction = predictions.get(channel) if predictions else None
            
            result = kf.step(measurement, prediction)
            results[channel] = result
            residuals[channel] = result['residual']
        
        return {
            'channels': results,
            'residuals': residuals,
        }

    def get_residuals(self) -> Dict[str, float]:
        """Get current residuals for all channels."""
        return {ch: kf.residual for ch, kf in self.filters.items()}
