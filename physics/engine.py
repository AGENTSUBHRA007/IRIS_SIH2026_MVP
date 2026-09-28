"""
Physics Engine for Conveyor Belt Digital Twin.

Consolidated module implementing:
- Kinematics (angular velocity, belt velocity, position)
- Belt tension (Euler-Eytelwein tight/slack side)
- Belt sag (parabolic catenary model)
- Vibration (mass-spring-damper steady-state)
- Thermal (lumped thermal model)
- Roller dynamics (bearing defect frequencies)
- IS 11592/8598 compliance checks
- Load model (capacity, power, distributed weight)
"""

import math
import numpy as np
from typing import Dict, Optional
from dataclasses import dataclass, field


@dataclass
class ConveyorParams:
    """Physical parameters of the conveyor system."""
    belt_length_m: float = 500.0
    belt_width_mm: float = 1200.0
    belt_speed_mps: float = 3.15
    breaking_strength_kN: float = 800.0
    belt_mass_per_meter: float = 18.5
    troughing_angle_deg: float = 35.0
    
    drive_diameter_mm: float = 630.0
    drive_wrap_angle_deg: float = 210.0
    drive_friction_coeff: float = 0.35
    
    tail_diameter_mm: float = 500.0
    
    idler_spacing_carry_m: float = 1.2
    idler_spacing_return_m: float = 3.0
    roller_diameter_mm: float = 127.0
    
    material_density: float = 1600.0
    max_capacity_tph: float = 2000.0
    
    motor_power_kW: float = 250.0
    motor_speed_rpm: float = 1480.0
    motor_efficiency: float = 0.92
    
    ambient_temp_c: float = 35.0
    friction_factor: float = 0.025
    elevation_m: float = 0.0

    # Vibration model
    mass_kg: float = 50.0
    stiffness: float = 200000.0
    damping: float = 500.0
    
    # Thermal model
    heat_transfer_coeff: float = 25.0
    surface_area_m2: float = 2.0
    thermal_mass: float = 50000.0


class PhysicsEngine:
    """Complete physics engine for conveyor belt simulation."""

    def __init__(self, params: Optional[ConveyorParams] = None):
        self.params = params or ConveyorParams()
        self._position_m = 0.0
        self._temperature_c = self.params.ambient_temp_c
        self._vibration_rms = 3.0

    # ── Kinematics ──
    
    def angular_velocity(self, speed_mps: float = None) -> float:
        """Angular velocity of drive pulley (rad/s)."""
        v = speed_mps or self.params.belt_speed_mps
        r = self.params.drive_diameter_mm / 2000.0  # mm → m
        return v / r

    def belt_position(self, dt_s: float, speed_mps: float = None) -> float:
        """Update and return belt position (m)."""
        v = speed_mps or self.params.belt_speed_mps
        self._position_m += v * dt_s
        self._position_m %= self.params.belt_length_m
        return self._position_m

    # ── Belt Tension (Euler-Eytelwein) ──

    def belt_tension(self, load_fraction: float = 1.0) -> Dict:
        """
        Calculate tight and slack side tensions using Euler-Eytelwein.
        
        T_tight / T_slack = e^(μθ)
        """
        mu = self.params.drive_friction_coeff
        theta = math.radians(self.params.drive_wrap_angle_deg)
        
        # Effective tension from load
        P = self.params.motor_power_kW * 1000 * load_fraction
        v = self.params.belt_speed_mps
        F_eff = P / max(v, 0.1)  # N
        
        # Euler-Eytelwein
        e_mu_theta = math.exp(mu * theta)
        T_tight = F_eff * e_mu_theta / (e_mu_theta - 1)
        T_slack = T_tight - F_eff
        
        # Safety factor
        breaking_force = self.params.breaking_strength_kN * 1000  # N
        safety_factor = breaking_force / max(T_tight, 1.0)
        
        return {
            'tight_side_N': round(T_tight, 0),
            'slack_side_N': round(T_slack, 0),
            'effective_tension_N': round(F_eff, 0),
            'euler_ratio': round(e_mu_theta, 3),
            'safety_factor': round(safety_factor, 1),
            'safety_ok': safety_factor >= 8.0,
        }

    # ── Belt Sag ──

    def belt_sag(self, load_fraction: float = 1.0) -> Dict:
        """
        Calculate belt sag using parabolic catenary model.
        y = wL² / (8T)  where w = distributed weight, L = idler spacing, T = tension
        """
        tension = self.belt_tension(load_fraction)
        T = tension['slack_side_N']
        
        # Distributed weight (belt + material)
        material_load = self.params.material_density * 0.11 * (self.params.belt_width_mm / 1000) ** 2
        w = (self.params.belt_mass_per_meter + material_load * load_fraction) * 9.81  # N/m
        
        L = self.params.idler_spacing_carry_m
        
        sag_m = (w * L ** 2) / (8 * max(T, 1.0))
        sag_ratio_pct = (sag_m / L) * 100
        
        return {
            'sag_m': round(sag_m, 4),
            'sag_ratio_pct': round(sag_ratio_pct, 2),
            'idler_spacing_m': L,
            'distributed_weight_Npm': round(w, 1),
            'is_compliant': sag_ratio_pct <= 2.0,
        }

    # ── Vibration (Mass-Spring-Damper) ──

    def vibration_response(self, excitation_freq_hz: float = 25.0,
                           force_amplitude_N: float = 100.0) -> Dict:
        """
        Steady-state vibration response of mass-spring-damper system.
        X = F / sqrt((k - mω²)² + (cω)²)
        """
        m = self.params.mass_kg
        k = self.params.stiffness
        c = self.params.damping
        
        omega = 2 * math.pi * excitation_freq_hz
        natural_freq = math.sqrt(k / m) / (2 * math.pi)
        damping_ratio = c / (2 * math.sqrt(k * m))
        
        denom = math.sqrt((k - m * omega ** 2) ** 2 + (c * omega) ** 2)
        amplitude_m = force_amplitude_N / max(denom, 1e-9)
        velocity_mps = amplitude_m * omega
        
        self._vibration_rms = velocity_mps * 1000  # mm/s
        
        return {
            'amplitude_mm': round(amplitude_m * 1000, 4),
            'velocity_mms': round(self._vibration_rms, 2),
            'natural_freq_hz': round(natural_freq, 1),
            'damping_ratio': round(damping_ratio, 3),
            'frequency_ratio': round(excitation_freq_hz / natural_freq, 3),
        }

    # ── Thermal Model ──

    def thermal_update(self, dt_s: float, power_dissipated_W: float = 500.0) -> Dict:
        """
        Lumped thermal model: T_ss = T_amb + P/(h·A)
        dT/dt = (P - h·A·(T-T_amb)) / (m·c)
        """
        h = self.params.heat_transfer_coeff
        A = self.params.surface_area_m2
        T_amb = self.params.ambient_temp_c
        mc = self.params.thermal_mass
        
        T_ss = T_amb + power_dissipated_W / (h * A)
        
        # First-order response
        dT = (power_dissipated_W - h * A * (self._temperature_c - T_amb)) / mc
        self._temperature_c += dT * dt_s
        
        return {
            'current_temp_c': round(self._temperature_c, 1),
            'steady_state_c': round(T_ss, 1),
            'ambient_c': T_amb,
            'rate_c_per_s': round(dT, 4),
        }

    # ── Roller Dynamics ──

    def bearing_defect_frequencies(self, shaft_speed_hz: float = None,
                                    n_balls: int = 9,
                                    ball_diameter_mm: float = 12.7,
                                    pitch_diameter_mm: float = 46.0,
                                    contact_angle_deg: float = 0.0) -> Dict:
        """Bearing defect frequency analysis."""
        if shaft_speed_hz is None:
            shaft_speed_hz = self.angular_velocity() / (2 * math.pi)
        
        d = ball_diameter_mm
        D = pitch_diameter_mm
        n = n_balls
        alpha = math.radians(contact_angle_deg)
        f_s = shaft_speed_hz
        
        BPFO = (n / 2) * f_s * (1 - (d / D) * math.cos(alpha))
        BPFI = (n / 2) * f_s * (1 + (d / D) * math.cos(alpha))
        BSF = (D / (2 * d)) * f_s * (1 - ((d / D) * math.cos(alpha)) ** 2)
        FTF = (f_s / 2) * (1 - (d / D) * math.cos(alpha))
        
        return {
            'BPFO_hz': round(BPFO, 2),
            'BPFI_hz': round(BPFI, 2),
            'BSF_hz': round(BSF, 2),
            'FTF_hz': round(FTF, 2),
            'shaft_speed_hz': round(f_s, 2),
        }

    # ── IS 11592 Compliance ──

    def is_compliance(self, load_fraction: float = 1.0) -> Dict:
        """Check IS 11592:2000 compliance."""
        tension = self.belt_tension(load_fraction)
        sag = self.belt_sag(load_fraction)
        
        # Cross-sectional area
        B = self.params.belt_width_mm / 1000  # m
        A = 0.11 * B ** 2  # at 35° troughing
        
        # Mass capacity
        v = self.params.belt_speed_mps
        Q = 3600 * v * A * self.params.material_density / 1000  # tph
        
        # Drive power check
        P_required = (Q * self.params.belt_length_m * self.params.friction_factor) / 367
        
        checks = {
            'safety_factor': {
                'value': tension['safety_factor'],
                'limit': '≥ 8.0×',
                'compliant': tension['safety_factor'] >= 8.0,
            },
            'sag_ratio': {
                'value': sag['sag_ratio_pct'],
                'limit': '≤ 2.0%',
                'compliant': sag['sag_ratio_pct'] <= 2.0,
            },
            'belt_speed': {
                'value': v,
                'limit': '≤ 4.0 m/s',
                'compliant': v <= 4.0,
            },
            'capacity_tph': {
                'value': round(Q, 0),
                'limit': f'≤ {self.params.max_capacity_tph} tph',
                'compliant': Q <= self.params.max_capacity_tph,
            },
            'power_available': {
                'value': round(P_required, 1),
                'limit': f'≤ {self.params.motor_power_kW} kW',
                'compliant': P_required <= self.params.motor_power_kW,
            },
        }
        
        all_compliant = all(c['compliant'] for c in checks.values())
        
        return {
            'standard': 'IS 11592:2000',
            'overall_compliant': all_compliant,
            'checks': checks,
            'cross_section_m2': round(A, 4),
            'capacity_tph': round(Q, 0),
            'required_power_kW': round(P_required, 1),
        }

    # ── Load Model ──

    def load_model(self, load_fraction: float = 1.0) -> Dict:
        """Calculate load-dependent motor heat and distributed weight."""
        P = self.params.motor_power_kW * load_fraction
        losses = P * (1 - self.params.motor_efficiency)
        
        B = self.params.belt_width_mm / 1000
        material_per_meter = self.params.material_density * 0.11 * B ** 2 * load_fraction
        total_per_meter = self.params.belt_mass_per_meter + material_per_meter
        
        return {
            'motor_power_kW': round(P, 1),
            'motor_losses_kW': round(losses, 2),
            'belt_mass_per_m': self.params.belt_mass_per_meter,
            'material_per_m': round(material_per_meter, 2),
            'total_per_m': round(total_per_meter, 2),
            'load_fraction': load_fraction,
        }

    def get_full_state(self, dt_s: float = 1.0, 
                       load_fraction: float = 1.0,
                       speed_mps: float = None) -> Dict:
        """Get complete physics state for one simulation step."""
        v = speed_mps or self.params.belt_speed_mps
        
        position = self.belt_position(dt_s, v)
        tension = self.belt_tension(load_fraction)
        sag = self.belt_sag(load_fraction)
        vibration = self.vibration_response()
        thermal = self.thermal_update(dt_s, 
            self.load_model(load_fraction)['motor_losses_kW'] * 1000)
        bearing = self.bearing_defect_frequencies()
        compliance = self.is_compliance(load_fraction)
        load = self.load_model(load_fraction)
        
        return {
            'kinematics': {
                'belt_speed_mps': round(v, 2),
                'angular_velocity_rads': round(self.angular_velocity(v), 2),
                'position_m': round(position, 2),
            },
            'tension': tension,
            'sag': sag,
            'vibration': vibration,
            'thermal': thermal,
            'bearing_frequencies': bearing,
            'compliance': compliance,
            'load': load,
        }
