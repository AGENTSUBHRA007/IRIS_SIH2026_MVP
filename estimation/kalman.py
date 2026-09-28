"""
Scalar Kalman Filter — custom implementation (no external dependency).
Used for fusing noisy sensor measurements with physics-predicted values.
"""

import numpy as np


class ScalarKalmanFilter:
    """
    1D Kalman filter for single-channel state estimation.
    
    State model: x_k = x_{k-1} + w_k  (random walk)
    Measurement: z_k = x_k + v_k
    """

    def __init__(self, 
                 process_noise: float = 0.01,
                 measurement_noise: float = 0.1,
                 initial_estimate: float = 0.0,
                 initial_error: float = 1.0):
        self.Q = process_noise      # Process noise variance
        self.R = measurement_noise  # Measurement noise variance
        self.x = initial_estimate   # State estimate
        self.P = initial_error      # Estimate error variance
        self._residual = 0.0

    def predict(self, control_input: float = 0.0):
        """Prediction step."""
        self.x = self.x + control_input
        self.P = self.P + self.Q

    def update(self, measurement: float) -> float:
        """
        Update step with measurement.
        
        Returns:
            Kalman filtered estimate
        """
        # Kalman gain
        K = self.P / (self.P + self.R)
        
        # Residual (innovation)
        self._residual = measurement - self.x
        
        # Update estimate
        self.x = self.x + K * self._residual
        
        # Update error covariance
        self.P = (1 - K) * self.P
        
        return self.x

    def step(self, measurement: float, prediction: float = None) -> dict:
        """
        Combined predict + update step.
        
        Args:
            measurement: Actual sensor reading
            prediction: Physics-model predicted value (optional control input)
            
        Returns:
            Dict with estimated, residual, gain
        """
        if prediction is not None:
            control = prediction - self.x
            self.predict(control_input=control * 0.1)
        else:
            self.predict()
        
        estimated = self.update(measurement)
        
        return {
            'estimated': round(estimated, 4),
            'residual': round(self._residual, 4),
            'gain': round(self.P / (self.P + self.R), 4),
        }

    @property
    def residual(self) -> float:
        return self._residual

    @property
    def estimate(self) -> float:
        return self.x
