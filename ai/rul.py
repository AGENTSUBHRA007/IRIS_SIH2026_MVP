"""
RUL (Remaining Useful Life) estimation with uncertainty.

Dual-source RUL:
  1. Trend-based: Linear polyfit on rolling health history → project to threshold
  2. Damage-budget: Starting budget minus cumulative rul_impact_hours
  
Reported RUL = min(trend, budget) with source attribution.
Uncertainty via residual-bootstrap confidence interval.
"""

import numpy as np
from collections import deque
from typing import Dict, Optional, Tuple
from ai.severity import Severity, rul_impact_hours


class RULEstimator:
    """
    Dual-source RUL estimation with bootstrap confidence intervals.
    """

    def __init__(self, 
                 budget_hours: float = 500.0,
                 degradation_threshold: float = 40.0,
                 history_window: int = 500,
                 tick_interval_s: float = 1.0):
        self._budget_hours = budget_hours
        self._initial_budget = budget_hours
        self._degradation_threshold = degradation_threshold
        self._tick_interval_s = tick_interval_s
        self._health_history = deque(maxlen=history_window)
        self._time_history = deque(maxlen=history_window)
        self._elapsed_hours = 0.0
        self._rul_hours = budget_hours
        self._rul_source = "damage_budget"
        self._ci_lower = budget_hours * 0.8
        self._ci_upper = budget_hours * 1.2
        self._applied_events: set = set()

    def update(self, health_score: float, damage_events: Optional[list] = None) -> Dict:
        """
        Update RUL estimate with current health score and new damage events.
        
        Returns:
            Dict with rul_hours, rul_source, ci_lower, ci_upper
        """
        self._elapsed_hours += self._tick_interval_s / 3600.0
        self._health_history.append(health_score)
        self._time_history.append(self._elapsed_hours)

        # ── Damage budget deduction ──
        if damage_events:
            for event in damage_events:
                event_id = event.id if hasattr(event, 'id') else event.get('id', '')
                if event_id and event_id not in self._applied_events:
                    self._applied_events.add(event_id)
                    severity_str = event.severity if hasattr(event, 'severity') else event.get('severity', 'NONE')
                    try:
                        sev = Severity(severity_str)
                    except ValueError:
                        sev = Severity.NONE
                    impact = rul_impact_hours(sev)
                    self._budget_hours = max(0, self._budget_hours + impact)

        # ── Trend-based projection ──
        trend_rul = self._compute_trend_rul()

        # ── Final RUL = min(trend, budget) ──
        if trend_rul is not None and trend_rul < self._budget_hours:
            self._rul_hours = max(0, trend_rul)
            self._rul_source = "trend"
        else:
            self._rul_hours = max(0, self._budget_hours)
            self._rul_source = "damage_budget"

        # ── Bootstrap CI ──
        self._compute_confidence_interval()

        return {
            'rul_hours': round(self._rul_hours, 1),
            'rul_source': self._rul_source,
            'ci_lower': round(self._ci_lower, 1),
            'ci_upper': round(self._ci_upper, 1),
            'budget_hours': round(self._budget_hours, 1),
            'elapsed_hours': round(self._elapsed_hours, 2),
        }

    def _compute_trend_rul(self) -> Optional[float]:
        """Linear trend extrapolation to degradation threshold."""
        if len(self._health_history) < 30:
            return None

        times = np.array(self._time_history)
        healths = np.array(self._health_history)

        try:
            coeffs = np.polyfit(times, healths, 1)
            slope = coeffs[0]
            
            if slope >= 0:
                return None  # Not degrading

            current_health = healths[-1]
            hours_to_threshold = (self._degradation_threshold - current_health) / slope
            return max(0, hours_to_threshold)
        except (np.linalg.LinAlgError, ValueError):
            return None

    def _compute_confidence_interval(self, n_bootstrap: int = 300, ci: float = 0.90):
        """Bootstrap confidence interval for RUL."""
        if len(self._health_history) < 30:
            self._ci_lower = self._rul_hours * 0.7
            self._ci_upper = self._rul_hours * 1.3
            return

        times = np.array(self._time_history)
        healths = np.array(self._health_history)

        try:
            coeffs = np.polyfit(times, healths, 1)
            residuals = healths - np.polyval(coeffs, times)

            rng = np.random.RandomState(42)
            rul_samples = []

            for _ in range(n_bootstrap):
                boot_residuals = rng.choice(residuals, size=len(residuals), replace=True)
                boot_healths = np.polyval(coeffs, times) + boot_residuals

                try:
                    boot_coeffs = np.polyfit(times, boot_healths, 1)
                    if boot_coeffs[0] < 0:
                        hours_to = (self._degradation_threshold - boot_healths[-1]) / boot_coeffs[0]
                        rul_samples.append(max(0, hours_to))
                except:
                    pass

            if rul_samples:
                alpha = (1 - ci) / 2
                self._ci_lower = max(0, np.percentile(rul_samples, alpha * 100))
                self._ci_upper = np.percentile(rul_samples, (1 - alpha) * 100)
            else:
                self._ci_lower = self._rul_hours * 0.7
                self._ci_upper = self._rul_hours * 1.3
        except:
            self._ci_lower = self._rul_hours * 0.7
            self._ci_upper = self._rul_hours * 1.3

    @property
    def rul_hours(self) -> float:
        return self._rul_hours

    @property
    def rul_source(self) -> str:
        return self._rul_source

    def reset(self):
        """Reset RUL estimator to initial state."""
        self._budget_hours = self._initial_budget
        self._health_history.clear()
        self._time_history.clear()
        self._elapsed_hours = 0.0
        self._rul_hours = self._initial_budget
        self._rul_source = "damage_budget"
        self._applied_events.clear()
