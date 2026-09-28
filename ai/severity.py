"""
Severity classification and defect knowledge base for conveyor belt damage.
Maps detection class, confidence, and estimated defect length to severity levels,
RUL impact hours, and health score penalties adhering to ISO 15236 & DIN 22101.
Includes plain-English explanations and operator recommendations for regular users.
"""

from enum import Enum
from typing import Tuple, Optional, Dict, Any, Union


class Severity(str, Enum):
    NONE = "NONE"
    MINOR = "MINOR"
    MODERATE = "MODERATE"
    SEVERE = "SEVERE"
    CRITICAL = "CRITICAL"


# Class-specific engineering thresholds: (length_cm thresholds, severities, rul_impact, penalty)
# Calibrated for Steel Cord ST-2500 / Fabric EP-1000 industrial belts under DIN 22101 & ISO 15236
_CLASS_SPECIFIC_THRESHOLDS: Dict[str, list] = {
    "CRACK": [
        (6.0,   Severity.MINOR,    -3.5,  -3),
        (14.0,  Severity.MODERATE, -8.0,  -8),
        (22.0,  Severity.SEVERE,   -16.0, -18),
        (999.0, Severity.CRITICAL, -28.0, -30),
    ],
    "TEAR": [
        (6.0,   Severity.MODERATE, -12.0, -12),
        (18.0,  Severity.SEVERE,   -22.0, -22),
        (999.0, Severity.CRITICAL, -38.0, -38),
    ],
    "SURFACE_DAMAGE": [
        (6.0,   Severity.MINOR,    -2.0,  -2),
        (14.0,  Severity.MODERATE, -5.5,  -5),
        (24.0,  Severity.SEVERE,   -12.0, -12),
        (999.0, Severity.CRITICAL, -24.0, -25),
    ],
    "SURFACE_WEAR": [
        (8.0,   Severity.MINOR,    -2.0,  -2),
        (16.0,  Severity.MODERATE, -5.5,  -5),
        (999.0, Severity.SEVERE,  -11.0, -12),
    ],
    "SPLICE_GAP": [
        (1.5,   Severity.MINOR,    -4.0,  -4),
        (3.0,   Severity.MODERATE, -12.0, -12),
        (5.5,   Severity.SEVERE,   -24.0, -24),
        (999.0, Severity.CRITICAL, -36.0, -36),
    ],
    "EDGE_DAMAGE": [
        (6.0,   Severity.MINOR,    -3.0,  -3),
        (16.0,  Severity.MODERATE, -7.5,  -7),
        (26.0,  Severity.SEVERE,   -16.0, -16),
        (999.0, Severity.CRITICAL, -28.0, -28),
    ],
    "FOREIGN_OBJECT": [
        (5.0,   Severity.MINOR,    -2.0,  -2),
        (12.0,  Severity.MODERATE, -8.0,  -8),
        (20.0,  Severity.SEVERE,   -18.0, -18),
        (999.0, Severity.CRITICAL, -30.0, -30),
    ],
}

_DEFAULT_THRESHOLDS = [
    (5.0,   Severity.MINOR,    -3.0,  -3),
    (15.0,  Severity.MODERATE, -8.0,  -8),
    (25.0,  Severity.SEVERE,   -18.0, -18),
    (999.0, Severity.CRITICAL, -30.0, -30),
]

# Plain-English and engineering descriptions for all defect classes
DEFECT_METADATA: Dict[str, Dict[str, Any]] = {
    "CRACK": {
        "title": "Cover Surface Crack",
        "category": "Surface Degradation",
        "description_plain": "A crack or fracture line in the top rubber protective layer. Caused by rubber aging, flex fatigue, or sun exposure.",
        "description_technical": "Transverse or longitudinal micro-fissuring of the top cover compound. Potential path for moisture ingress into steel cords.",
        "danger_plain": "If ignored, rainwater and fine dust seep inside and rust the steel cords or rot fabric plies, causing sudden belt break.",
        "action_plain": "Monitor during next routine walkaround. Apply cold vulcanizing rubber patch or sealant during scheduled stoppage.",
        "iso_standard": "ISO 15236-2 (Surface Quality & Cover Cracking Limits)",
        "color": "#38bdf8",
        "badge_color": "var(--blue, #38bdf8)",
        "icon": "⚡",
    },
    "TEAR": {
        "title": "Longitudinal / Through Tear",
        "category": "Structural Integrity",
        "description_plain": "A deep cut or rip piercing through the conveyor belt. Usually caused by sharp rock edges or trapped metal at the transfer chute.",
        "description_technical": "Carcass penetration with longitudinal split or puncture breaching core tensile cords. High stress concentration zone.",
        "danger_plain": "CRITICAL: The tear can rapidly spread along the entire conveyor length within minutes, causing catastrophic belt splitting and massive downtime.",
        "action_plain": "Slow conveyor immediately. Inspect transfer chute. Install emergency mechanical fastener rip-stop clips or hot vulcanized repair patch.",
        "iso_standard": "ISO 15236-4 (Longitudinal Rip Resistance & DIN 22101 Tension Integrity)",
        "color": "#ef4444",
        "badge_color": "var(--red, #ef4444)",
        "icon": "💥",
    },
    "SURFACE_DAMAGE": {
        "title": "Cover Gouge / Impact Crater",
        "category": "Cover Integrity",
        "description_plain": "A chunk or gouge of rubber torn off the carrying surface from heavy rock drops at the feed chute.",
        "description_technical": "Localized severe abrasion, chunking, or cover gouging exposing under-ply or cord skim rubber.",
        "danger_plain": "Reduces carrying capacity and allows ore fines to pack into the gouge, causing further rubber tearing under idler rollers.",
        "action_plain": "Clean debris from crater and fill with fast-curing polyurethane repair compound during lunch stoppage.",
        "iso_standard": "ISO 15236-2 (Impact Damage & Cover Thickness Retention)",
        "color": "#fbbf24",
        "badge_color": "var(--amber, #fbbf24)",
        "icon": "🕳️",
    },
    "SURFACE_WEAR": {
        "title": "Abrasive Surface Wear",
        "category": "Cover Degradation",
        "description_plain": "General thinning of the top rubber cover caused by continuous friction with abrasive iron ore.",
        "description_technical": "Uniform abrasive wear and cover thickness reduction over large belt surface areas.",
        "danger_plain": "When the rubber gets too thin, the internal steel cords or fabric plies contact idlers directly and wear out rapidly.",
        "action_plain": "Measure remaining cover thickness with ultrasonic gauge. Plan belt re-covering or replacement when thickness < 2.0 mm.",
        "iso_standard": "ISO 4649 / DIN 53516 (Abrasion Resistance & Cover Life)",
        "color": "#a855f7",
        "badge_color": "var(--purple, #a855f7)",
        "icon": "📉",
    },
    "SPLICE_GAP": {
        "title": "Joint Splice Gap / Separation",
        "category": "Joint Integrity",
        "description_plain": "Opening or stretching at the belt connection joint (splice). The glue/vulcanized bond between belt ends is pulling apart.",
        "description_technical": "Splice step opening, vulcanized finger joint delamination, or chord pull-out under dynamic tension.",
        "danger_plain": "VERY HIGH: A failing splice can snap completely under full ore load, dropping the belt into the conveyor structure.",
        "action_plain": "Inspect joint step separation immediately with caliper. Schedule emergency re-splicing if gap > 3.0 mm.",
        "iso_standard": "DIN 22129 / ISO 15236-3 (Static & Dynamic Splice Strength)",
        "color": "#f97316",
        "badge_color": "var(--orange, #f97316)",
        "icon": "🔗",
    },
    "EDGE_DAMAGE": {
        "title": "Belt Edge Fray / Sidewall Wear",
        "category": "Tracking & Idler Damage",
        "description_plain": "Frayed or shredded edges caused by the belt rubbing against conveyor steel frames or misaligned guide rollers.",
        "description_technical": "Edge rubber delamination, ply edge fraying, and lateral carcass reduction resulting from structural mistracking.",
        "danger_plain": "Weakens the lateral stiffness of the belt, causes severe mistracking, and risks steel cords peeling out from the sides.",
        "action_plain": "Re-align training idlers and adjust belt tracking sensor limit switches. Trim frayed cords.",
        "iso_standard": "IS 11592 / DIN 22101 (Belt Alignment & Edge Clearance)",
        "color": "#ec4899",
        "badge_color": "#ec4899",
        "icon": "✂️",
    },
    "FOREIGN_OBJECT": {
        "title": "Trapped Foreign Object / Scrap",
        "category": "Chute & Carry Hazard",
        "description_plain": "Unwanted metal piece (tramp iron), wedged boulder, or scraper tool stuck on the belt or in the skirtboard.",
        "description_technical": "Tramp iron, oversize debris, or dislodged skirtboard liner wedged between chute and moving belt.",
        "danger_plain": "Acts like a knife, scoring or slicing the entire length of the conveyor belt as it runs.",
        "action_plain": "Stop feed chute, safely lock out conveyor, and manually remove the trapped foreign object immediately.",
        "iso_standard": "IS 11592 Safety Regulations & Chute Clearance",
        "color": "#06b6d4",
        "badge_color": "var(--cyan, #06b6d4)",
        "icon": "⚠️",
    },
}

# Plain-English and engineering explanations for Severity levels
SEVERITY_METADATA: Dict[Severity, Dict[str, Any]] = {
    Severity.NONE: {
        "label": "None / Baseline",
        "color": "#6b7280",
        "plain_explanation": "No significant defect detected. Belt is operating normally in pristine condition.",
        "operator_urgency": "No action needed. Continue standard continuous monitoring.",
    },
    Severity.MINOR: {
        "label": "Minor (Low Risk)",
        "color": "#34d399",
        "plain_explanation": "Small surface blemish or hairline crack. Does not immediately affect conveyor safety.",
        "operator_urgency": "Log in routine maintenance ledger. Inspect during next weekly scheduled stoppage.",
    },
    Severity.MODERATE: {
        "label": "Moderate (Attention Required)",
        "color": "#fbbf24",
        "plain_explanation": "Defect is expanding and starting to degrade belt service life. Requires engineering attention.",
        "operator_urgency": "Schedule inspection and patch repair within 48 to 72 hours. Monitor closely.",
    },
    Severity.SEVERE: {
        "label": "Severe (High Risk)",
        "color": "#f97316",
        "plain_explanation": "Major defect penetrating deep into the belt structure. High chance of rapid worsening under full load.",
        "operator_urgency": "Reduce conveyor speed/load. Plan immediate maintenance window within 12 to 24 hours.",
    },
    Severity.CRITICAL: {
        "label": "Critical (Immediate Danger)",
        "color": "#ef4444",
        "plain_explanation": "Dangerous structural damage (e.g. through-tear or parting splice). Failure could happen at any moment.",
        "operator_urgency": "HALT OR INTERVENE IMMEDIATELY. Apply emergency repair clamp or initiate controlled shutdown.",
    },
}


def _normalize_class_name(class_name: str) -> str:
    """Normalize input class name and resolve common aliases."""
    if not class_name:
        return "CRACK"
    norm = class_name.upper().strip().replace(" ", "_")
    if norm in _CLASS_SPECIFIC_THRESHOLDS:
        return norm
    if "TEAR" in norm or "RIP" in norm:
        return "TEAR"
    if "SPLICE" in norm or "JOINT" in norm:
        return "SPLICE_GAP"
    if "EDGE" in norm or "SIDE" in norm:
        return "EDGE_DAMAGE"
    if "FOREIGN" in norm or "OBJECT" in norm or "TRAMP" in norm or "DEBRIS" in norm:
        return "FOREIGN_OBJECT"
    if "WEAR" in norm:
        return "SURFACE_WEAR"
    if "DAMAGE" in norm or "GOUGE" in norm or "HOLE" in norm:
        return "SURFACE_DAMAGE"
    if "CRACK" in norm or "FISSURE" in norm:
        return "CRACK"
    return "CRACK"


def classify_severity(confidence: float, length_cm: float, class_name: str = "CRACK") -> Tuple[Severity, float, int]:
    """
    Classify severity based on class name, confidence, and estimated defect size.
    
    Returns:
        (severity: Severity, rul_impact_hours: float, health_penalty: int)
    """
    if confidence < 0.10 or length_cm < 0.5:
        return Severity.NONE, 0.0, 0

    norm_class = _normalize_class_name(class_name)
    thresholds = _CLASS_SPECIFIC_THRESHOLDS.get(norm_class, _DEFAULT_THRESHOLDS)

    for max_len, sev, rul_impact, health_pen in thresholds:
        if length_cm <= max_len:
            # Scale slightly with confidence (0.85 - 1.10)
            conf_factor = min(1.10, max(0.85, confidence))
            scaled_rul = round(rul_impact * conf_factor, 1)
            scaled_pen = int(round(health_pen * conf_factor))
            return sev, scaled_rul, scaled_pen

    last_sev, last_rul, last_pen = thresholds[-1]
    return last_sev, last_rul, last_pen


def rul_impact_hours(severity: Union[Severity, str]) -> float:
    """Get approximate default RUL impact hours for a given severity."""
    if isinstance(severity, str):
        try:
            sev_enum = Severity(severity.upper().strip())
        except ValueError:
            sev_enum = Severity.NONE
    else:
        sev_enum = severity

    table = {
        Severity.NONE: 0.0,
        Severity.MINOR: -3.5,
        Severity.MODERATE: -9.0,
        Severity.SEVERE: -20.0,
        Severity.CRITICAL: -35.0,
    }
    return table.get(sev_enum, 0.0)


def health_penalty(severity: Union[Severity, str]) -> int:
    """Get approximate default health score penalty for a given severity."""
    if isinstance(severity, str):
        try:
            sev_enum = Severity(severity.upper().strip())
        except ValueError:
            sev_enum = Severity.NONE
    else:
        sev_enum = severity

    table = {
        Severity.NONE: 0,
        Severity.MINOR: -3,
        Severity.MODERATE: -8,
        Severity.SEVERE: -20,
        Severity.CRITICAL: -35,
    }
    return table.get(sev_enum, 0)


def get_class_meta(class_name: str) -> Dict[str, Any]:
    """Retrieve metadata and plain-English guides for a given defect class."""
    norm = _normalize_class_name(class_name)
    if norm in DEFECT_METADATA:
        return DEFECT_METADATA[norm]
    return {
        "title": class_name.replace("_", " ").title(),
        "category": "General Anomaly",
        "description_plain": f"Detected irregularity of type {class_name} on the conveyor belt.",
        "description_technical": f"Unclassified anomaly detected by AI vision system: {class_name}.",
        "danger_plain": "May cause localized stress concentration or premature wear.",
        "action_plain": "Visually inspect during next scheduled belt walkaround.",
        "iso_standard": "IS 11592 Industrial Standard",
        "color": "#94a3b8",
        "badge_color": "var(--text-secondary)",
        "icon": "🔍",
    }


def get_severity_meta(severity: Union[Severity, str]) -> Dict[str, Any]:
    """Retrieve metadata and plain-English explanations for a given severity level."""
    try:
        if isinstance(severity, str):
            sev_enum = Severity(severity.upper().strip())
        else:
            sev_enum = severity
    except ValueError:
        sev_enum = Severity.NONE
    return SEVERITY_METADATA.get(sev_enum, SEVERITY_METADATA[Severity.NONE])


def get_severity_color(severity: Union[Severity, str]) -> str:
    """Retrieve hex color code for a severity level."""
    meta = get_severity_meta(severity)
    return meta.get("color", "#6b7280")


def get_class_color(class_name: str) -> str:
    """Retrieve hex color code for a defect class."""
    meta = get_class_meta(class_name)
    return meta.get("color", "#38bdf8")
