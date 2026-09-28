"""
YOLO-based damage detection module.
Supports both real model inference and high-fidelity, physically consistent simulated detection.
Maintains temporal continuity and spatial tracking across frames for all defect classes:
CRACK, TEAR, SURFACE_DAMAGE, SURFACE_WEAR, SPLICE_GAP, EDGE_DAMAGE, FOREIGN_OBJECT.
"""

import time
import logging
import os
from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any, Tuple
from pathlib import Path

import numpy as np
import yaml

from ai.severity import classify_severity, Severity, get_class_meta

logger = logging.getLogger(__name__)


@dataclass
class Detection:
    """A single bounding-box detection from YOLO or consistent simulation."""
    class_id: int
    class_name: str
    confidence: float
    bbox_xyxy: List[float]  # [x1, y1, x2, y2]
    severity: str = "NONE"
    length_cm: float = 0.0
    rul_impact_hours: float = 0.0
    track_id: Optional[str] = None
    mask_polygon: Optional[List[List[float]]] = None


@dataclass
class YOLOConfig:
    """YOLO model configuration."""
    model_path: str = "models/best.pt"
    confidence_threshold: float = 0.12
    iou_threshold: float = 0.50
    image_size: int = 640
    device: str = "auto"
    class_mapping: Dict[int, str] = field(default_factory=lambda: {
        0: "CRACK",
        1: "TEAR",
        2: "SURFACE_DAMAGE",
        3: "SURFACE_WEAR",
        4: "SPLICE_GAP",
        5: "EDGE_DAMAGE",
        6: "FOREIGN_OBJECT",
    })
    pixels_to_cm_ratio: float = 0.15

    @classmethod
    def from_yaml(cls, path: str = "config/yolo.yaml") -> "YOLOConfig":
        """Load config from YAML file."""
        try:
            with open(path, 'r') as f:
                data = yaml.safe_load(f)
            yolo_data = data.get('yolo', {})
            mapping = yolo_data.get('class_mapping', {})
            int_mapping = {int(k): v for k, v in mapping.items()} if mapping else None
            return cls(
                model_path=yolo_data.get('model_path', cls.model_path),
                confidence_threshold=yolo_data.get('confidence_threshold', cls.confidence_threshold),
                iou_threshold=yolo_data.get('iou_threshold', cls.iou_threshold),
                image_size=yolo_data.get('image_size', cls.image_size),
                device=yolo_data.get('device', cls.device),
                class_mapping=int_mapping if int_mapping else cls().class_mapping,
                pixels_to_cm_ratio=yolo_data.get('pixels_to_cm_ratio', cls.pixels_to_cm_ratio),
            )
        except Exception as e:
            logger.warning(f"YOLO config not found/invalid at {path} ({e}), using defaults")
            return cls()


class SimulatedDefectAnchor:
    """A physical defect anchored at a fixed coordinate on the 500m conveyor belt loop."""
    def __init__(self, defect_id: str, belt_pos_m: float, class_name: str, length_cm: float,
                 base_confidence: float = 0.92, lateral_offset_px: int = 240, width_px: int = 120, height_px: int = 80):
        self.defect_id = defect_id
        self.belt_pos_m = belt_pos_m
        self.class_name = class_name
        self.length_cm = length_cm
        self.base_confidence = base_confidence
        self.lateral_offset_px = lateral_offset_px
        self.width_px = width_px
        self.height_px = height_px


class YOLODamageDetector:
    """
    Damage detector using Ultralytics YOLO with fallback to high-fidelity,
    temporally consistent simulation mode.
    """

    def __init__(self, config: Optional[YOLOConfig] = None):
        self.config = config or YOLOConfig.from_yaml()
        self.model = None
        self._simulation_mode = True
        self._sim_counter = 0
        self._sim_belt_position_m = 0.0
        self._belt_length_m = 500.0  # standard NMDC conveyor loop length
        self._active_tracks: Dict[str, dict] = {}
        
        # Define realistic, consistent physical defects anchored on the 500m belt loop
        self._belt_defects = [
            SimulatedDefectAnchor(
                defect_id="DEFECT-01-CRACK",
                belt_pos_m=28.0,
                class_name="CRACK",
                length_cm=9.5,
                base_confidence=0.91,
                lateral_offset_px=220,
                width_px=75,
                height_px=45
            ),
            SimulatedDefectAnchor(
                defect_id="DEFECT-02-SURFACE",
                belt_pos_m=85.0,
                class_name="SURFACE_DAMAGE",
                length_cm=14.0,
                base_confidence=0.88,
                lateral_offset_px=310,
                width_px=110,
                height_px=80
            ),
            SimulatedDefectAnchor(
                defect_id="DEFECT-03-SPLICE",
                belt_pos_m=175.0,
                class_name="SPLICE_GAP",
                length_cm=3.2,
                base_confidence=0.94,
                lateral_offset_px=180,
                width_px=280,
                height_px=30
            ),
            SimulatedDefectAnchor(
                defect_id="DEFECT-04-EDGE",
                belt_pos_m=290.0,
                class_name="EDGE_DAMAGE",
                length_cm=18.5,
                base_confidence=0.89,
                lateral_offset_px=40,
                width_px=90,
                height_px=130
            ),
            SimulatedDefectAnchor(
                defect_id="DEFECT-05-WEAR",
                belt_pos_m=380.0,
                class_name="SURFACE_WEAR",
                length_cm=12.0,
                base_confidence=0.86,
                lateral_offset_px=200,
                width_px=160,
                height_px=95
            ),
        ]
        
        self._load_model()

    def _load_model(self):
        """Attempt to load the YOLO model."""
        model_path = Path(self.config.model_path)
        if model_path.exists():
            try:
                # Ensure compatibility for custom/newer YOLO layer heads (e.g. Proto26, Segment26, Detect26)
                try:
                    import ultralytics.nn.modules.head as head_mod
                    import ultralytics.nn.modules.block as block_mod
                    import ultralytics.nn.modules.conv as conv_mod
                    for mod in [head_mod, block_mod, conv_mod]:
                        for attr in list(dir(mod)):
                            if not attr.endswith('26'):
                                setattr(mod, attr + '26', getattr(mod, attr))
                except Exception as comp_err:
                    logger.debug(f"Compatibility alias setup: {comp_err}")

                from ultralytics import YOLO
                self.model = YOLO(str(model_path))
                self._simulation_mode = False

                # Dynamically sync class names from model
                if hasattr(self.model, 'names') and isinstance(self.model.names, dict):
                    self.config.class_mapping = {
                        int(k): str(v).upper().replace(" ", "_")
                        for k, v in self.model.names.items()
                    }
                logger.info(f"Loaded YOLO model from {model_path} with classes: {self.config.class_mapping}")
            except Exception as e:
                logger.warning(f"Failed to load YOLO model: {e}. Using high-fidelity simulation mode.")
                self._simulation_mode = True
        else:
            logger.info(f"No YOLO model at {model_path}. Running in high-fidelity simulation mode.")
            self._simulation_mode = True

    def detect(self, frame: Optional[np.ndarray] = None, belt_position_m: Optional[float] = None,
               conf_threshold: Optional[float] = None) -> tuple:
        """
        Run detection on a frame.
        
        Args:
            frame: BGR numpy array (H, W, 3). If None or model unavailable, simulates detection.
            belt_position_m: Optional current belt position along conveyor for spatial tracking.
            conf_threshold: Optional confidence override for inference sensitivity.
            
        Returns:
            (detections: List[Detection], inference_ms: float, annotated_frame: np.ndarray or None)
        """
        if frame is None or self._simulation_mode:
            return self._simulate_detection(frame, belt_position_m)
        return self._run_real_inference(frame, conf_threshold=conf_threshold)

    def _run_real_inference(self, frame: np.ndarray, conf_threshold: Optional[float] = None) -> tuple:
        """Run actual YOLO inference with multi-class severity classification and segmentation masks."""
        start = time.perf_counter()
        effective_conf = conf_threshold if conf_threshold is not None else self.config.confidence_threshold
        
        results = self.model.predict(
            frame,
            conf=effective_conf,
            iou=self.config.iou_threshold,
            imgsz=self.config.image_size,
            verbose=False
        )
        inference_ms = (time.perf_counter() - start) * 1000

        detections = []
        annotated_frame = results[0].plot() if results else frame.copy()

        if results and results[0].boxes is not None:
            boxes = results[0].boxes
            masks = results[0].masks if hasattr(results[0], 'masks') else None
            
            for i in range(len(boxes)):
                cls_id = int(boxes.cls[i].item())
                conf = float(boxes.conf[i].item())
                bbox = boxes.xyxy[i].cpu().numpy().tolist()

                class_name = self.config.class_mapping.get(cls_id, "CRACK")
                bbox_width_px = bbox[2] - bbox[0]
                length_cm = bbox_width_px * self.config.pixels_to_cm_ratio

                severity, rul_impact, _ = classify_severity(conf, length_cm, class_name=class_name)

                # Extract polygon mask coordinates if available from segmentation model
                mask_poly = None
                if masks is not None and hasattr(masks, 'xy') and len(masks.xy) > i:
                    raw_poly = masks.xy[i]
                    if raw_poly is not None and len(raw_poly) > 0:
                        # Downsample polygon if > 32 points for lightweight wire transfer
                        if len(raw_poly) > 32:
                            step = max(1, len(raw_poly) // 32)
                            raw_poly = raw_poly[::step]
                        mask_poly = [[round(float(pt[0]), 1), round(float(pt[1]), 1)] for pt in raw_poly]

                detections.append(Detection(
                    class_id=cls_id,
                    class_name=class_name,
                    confidence=round(conf, 3),
                    bbox_xyxy=[round(b, 1) for b in bbox],
                    severity=severity.value,
                    length_cm=round(length_cm, 1),
                    rul_impact_hours=rul_impact,
                    track_id=f"det-{i+1}",
                    mask_polygon=mask_poly
                ))

        return detections, round(inference_ms, 1), annotated_frame

    def _simulate_detection(self, frame: Optional[np.ndarray] = None, belt_position_m: Optional[float] = None) -> tuple:
        """
        High-fidelity, temporally and physically consistent simulation.
        Defects stay anchored to physical coordinates on the belt loop and move smoothly
        across the camera inspection station FOV.
        """
        start = time.perf_counter()
        self._sim_counter += 1
        
        # Advance belt position smoothly (3.15 m/s)
        if belt_position_m is not None:
            current_pos = belt_position_m % self._belt_length_m
        else:
            # Advance ~0.35m per step for 10Hz video or 1.0m per tick
            self._sim_belt_position_m = (self._sim_belt_position_m + 0.60) % self._belt_length_m
            current_pos = self._sim_belt_position_m

        detections = []
        
        # Camera FOV captures a window of 3.0 meters at station x=0
        # Check if any anchored belt defect is currently passing through camera station
        fov_window_m = 3.2
        
        for defect in self._belt_defects:
            # Calculate distance from camera station (at 0m)
            dist_to_cam = (defect.belt_pos_m - current_pos) % self._belt_length_m
            
            # Check if defect is inside camera FOV window [-1.6m, +1.6m]
            if dist_to_cam <= fov_window_m or dist_to_cam >= (self._belt_length_m - fov_window_m):
                # Normalize position in FOV [0.0 = top of frame, 1.0 = bottom of frame]
                if dist_to_cam <= fov_window_m:
                    norm_y = 1.0 - (dist_to_cam / fov_window_m)
                else:
                    norm_y = (self._belt_length_m - dist_to_cam) / fov_window_m

                # Calculate smooth frame coordinates
                frame_h = frame.shape[0] if frame is not None else 480
                frame_w = frame.shape[1] if frame is not None else 640
                
                center_y = norm_y * frame_h
                x1 = max(10, min(frame_w - defect.width_px - 10, defect.lateral_offset_px))
                y1 = max(10, min(frame_h - defect.height_px - 10, int(center_y - defect.height_px / 2)))
                x2 = x1 + defect.width_px
                y2 = y1 + defect.height_px

                # Micro-jitter on confidence for realism (within ±0.015)
                conf_jitter = (np.sin(self._sim_counter * 0.4) * 0.012)
                conf = round(float(np.clip(defect.base_confidence + conf_jitter, 0.75, 0.98)), 3)

                # Class ID lookup
                class_id = 0
                for cid, cname in self.config.class_mapping.items():
                    if cname == defect.class_name:
                        class_id = cid
                        break

                severity, rul_impact, _ = classify_severity(conf, defect.length_cm, class_name=defect.class_name)

                detections.append(Detection(
                    class_id=class_id,
                    class_name=defect.class_name,
                    confidence=conf,
                    bbox_xyxy=[float(x1), float(y1), float(x2), float(y2)],
                    severity=severity.value,
                    length_cm=round(defect.length_cm, 1),
                    rul_impact_hours=rul_impact,
                    track_id=defect.defect_id
                ))

        inference_ms = 18.5 + (np.sin(self._sim_counter) * 3.2)
        
        annotated_frame = None
        if frame is not None:
            annotated_frame = self._annotate_frame(frame.copy(), detections)

        return detections, round(inference_ms, 1), annotated_frame

    def _annotate_frame(self, frame: np.ndarray, detections: List[Detection]) -> np.ndarray:
        """Draw bounding boxes, badges, and labels on frame."""
        import cv2

        SEVERITY_COLORS = {
            'NONE': (128, 128, 128),
            'MINOR': (52, 211, 153),       # emerald green
            'MODERATE': (36, 191, 251),     # amber / orange
            'SEVERE': (23, 115, 249),      # vivid orange/red
            'CRITICAL': (68, 68, 239),      # deep red
        }

        for det in detections:
            x1, y1, x2, y2 = [int(v) for v in det.bbox_xyxy]
            color = SEVERITY_COLORS.get(det.severity, (128, 128, 128))

            # Main bounding box
            cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)

            # Corner brackets (HUD style)
            c_len = min(16, (x2 - x1) // 4, (y2 - y1) // 4)
            cv2.line(frame, (x1, y1), (x1 + c_len, y1), color, 4)
            cv2.line(frame, (x1, y1), (x1, y1 + c_len), color, 4)
            cv2.line(frame, (x2, y1), (x2 - c_len, y1), color, 4)
            cv2.line(frame, (x2, y1), (x2, y1 + c_len), color, 4)
            cv2.line(frame, (x1, y2), (x1 + c_len, y2), color, 4)
            cv2.line(frame, (x1, y2), (x1, y2 - c_len), color, 4)
            cv2.line(frame, (x2, y2), (x2 - c_len, y2), color, 4)
            cv2.line(frame, (x2, y2), (x2, y2 - c_len), color, 4)

            # Label banner
            label = f"{det.class_name} {det.confidence:.0%}"
            meta = f"{det.severity} | {det.length_cm:.1f}cm"
            
            (tw1, th1), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.45, 1)
            (tw2, th2), _ = cv2.getTextSize(meta, cv2.FONT_HERSHEY_SIMPLEX, 0.38, 1)
            banner_w = max(tw1, tw2) + 12
            banner_h = th1 + th2 + 10
            
            banner_y1 = max(0, y1 - banner_h)
            cv2.rectangle(frame, (x1, banner_y1), (x1 + banner_w, banner_y1 + banner_h), color, -1)
            cv2.putText(frame, label, (x1 + 6, banner_y1 + th1 + 2),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.45, (255, 255, 255), 1, cv2.LINE_AA)
            cv2.putText(frame, meta, (x1 + 6, banner_y1 + th1 + th2 + 6),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.38, (240, 240, 240), 1, cv2.LINE_AA)

        return frame

    @property
    def is_simulation_mode(self) -> bool:
        return self._simulation_mode
