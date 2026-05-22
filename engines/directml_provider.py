"""
DirectML ONNX Inference Provider — AMD GPU acceleration for YOLO models.

This module provides a direct ONNX Runtime session with DmlExecutionProvider,
bypassing Ultralytics' default CPUExecutionProvider selection.

Usage:
    provider = DirectMLProvider("models/v11n-416-2.onnx", imgsz=416)
    detections = provider.infer(bgr_frame)

Requires: pip install onnxruntime-directml
"""

import numpy as np
import cv2
import os
import time
import logging
from typing import List, Optional, Tuple

logger = logging.getLogger(__name__)


def get_available_providers() -> list:
    """List available ONNX Runtime execution providers."""
    try:
        import onnxruntime as ort
        return ort.get_available_providers()
    except ImportError:
        return []


def has_directml() -> bool:
    """Check if DirectML provider is available."""
    return 'DmlExecutionProvider' in get_available_providers()


class DirectMLProvider:
    """
    Direct ONNX Runtime inference with DmlExecutionProvider (AMD GPU).
    
    Falls back to CPUExecutionProvider if DirectML is unavailable.
    """
    
    def __init__(self, model_path: str, imgsz: int = 416, conf: float = 0.55):
        """
        Args:
            model_path: Path to .onnx model
            imgsz: Input image size
            conf: Confidence threshold
        """
        self.model_path = model_path
        self.imgsz = imgsz
        self.conf = conf
        self.session = None
        self.input_name = None
        self.output_names = None
        self._provider_used = "none"
    
    def load(self) -> bool:
        """Initialize ONNX Runtime session with DirectML."""
        try:
            import onnxruntime as ort
            
            if not os.path.exists(self.model_path):
                logger.error(f"ONNX model not found: {self.model_path}")
                return False
            
            # Try DirectML first, then CPU fallback
            providers_priority = []
            available = ort.get_available_providers()
            
            if 'DmlExecutionProvider' in available:
                providers_priority.append('DmlExecutionProvider')
                
            if 'CPUExecutionProvider' in available:
                providers_priority.append('CPUExecutionProvider')
            
            logger.info(f"Available providers: {available}")
            logger.info(f"Using providers: {providers_priority}")
            
            # Session options for performance
            opts = ort.SessionOptions()
            opts.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
            opts.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
            opts.enable_mem_pattern = True
            
            self.session = ort.InferenceSession(
                self.model_path,
                sess_options=opts,
                providers=providers_priority,
            )
            
            # Get actual provider used
            self._provider_used = self.session.get_providers()[0]
            logger.info(f"Active provider: {self._provider_used}")
            
            # Get I/O info
            self.input_name = self.session.get_inputs()[0].name
            self.output_names = [o.name for o in self.session.get_outputs()]
            
            input_shape = self.session.get_inputs()[0].shape
            logger.info(f"Input: {self.input_name} shape={input_shape}")
            logger.info(f"Outputs: {self.output_names}")
            
            # Warmup
            dummy = np.zeros((1, 3, self.imgsz, self.imgsz), dtype=np.float32)
            for _ in range(3):
                self.session.run(self.output_names, {self.input_name: dummy})
            
            logger.info(f"DirectML provider ready ({self._provider_used})")
            return True
            
        except ImportError:
            logger.error("onnxruntime not installed. pip install onnxruntime-directml")
            return False
        except Exception as e:
            logger.error(f"DirectML load failed: {e}")
            return False
    
    def preprocess(self, frame: np.ndarray) -> np.ndarray:
        """
        Preprocess BGR frame for YOLO11 ONNX inference.
        
        Args:
            frame: BGR uint8 image (H, W, 3)
            
        Returns:
            NCHW float32 tensor (1, 3, imgsz, imgsz)
        """
        
        # Resize to model input
        resized = cv2.resize(frame, (self.imgsz, self.imgsz))
        
        # BGR -> RGB
        rgb = cv2.cvtColor(resized, cv2.COLOR_BGR2RGB)
        
        # Normalize to [0, 1]
        normalized = rgb.astype(np.float32) / 255.0
        
        # HWC -> CHW -> NCHW
        tensor = np.transpose(normalized, (2, 0, 1))
        tensor = np.expand_dims(tensor, axis=0)
        
        return tensor
    
    def postprocess(self, output: np.ndarray, 
                    orig_w: int, orig_h: int) -> List[dict]:
        """
        Postprocess YOLO11 ONNX output.
        
        YOLO11 output shape: (1, 6, N) where 6 = [x, y, w, h, cls0_conf, cls1_conf]
        
        Args:
            output: Raw model output
            orig_w, orig_h: Original frame dimensions
            
        Returns:
            List of detection dicts with keys: class_id, confidence, x, y, w, h
        """
        # Output shape: (1, 6, N) -> transpose to (N, 6)
        preds = output[0].T  # (N, 6)
        
        # Columns: x_center, y_center, width, height, class_0_conf, class_1_conf
        boxes = preds[:, :4]
        class_scores = preds[:, 4:]  # (N, num_classes)
        
        # Get best class per detection
        class_ids = np.argmax(class_scores, axis=1)
        confidences = np.max(class_scores, axis=1)
        
        # Filter by confidence
        mask = confidences >= self.conf
        boxes = boxes[mask]
        class_ids = class_ids[mask]
        confidences = confidences[mask]
        
        if len(boxes) == 0:
            return []
        
        # Apply NMS via OpenCV
        
        # Convert center format to x1,y1,w,h for cv2.dnn.NMSBoxes
        x1 = boxes[:, 0] - boxes[:, 2] / 2
        y1 = boxes[:, 1] - boxes[:, 3] / 2
        w = boxes[:, 2]
        h = boxes[:, 3]
        
        nms_boxes = np.stack([x1, y1, w, h], axis=1).tolist()
        nms_scores = confidences.tolist()
        
        indices = cv2.dnn.NMSBoxes(nms_boxes, nms_scores, self.conf, 0.45)
        
        if len(indices) == 0:
            return []
        
        # Scale back to original frame coordinates
        scale_x = orig_w / self.imgsz
        scale_y = orig_h / self.imgsz
        
        detections = []
        for idx in indices:
            # cv2.dnn.NMSBoxes returns either a list of single-element arrays
            # (older OpenCV) or a flat 1-D ndarray (OpenCV 4.x); normalize to a
            # native int. ``hasattr(idx, "__len__")`` matches both wrapped
            # shapes; bare numpy scalars take the ``int(idx)`` branch.
            i = int(idx[0]) if hasattr(idx, "__len__") else int(idx)
            detections.append({
                'class_id': int(class_ids[i]),
                'confidence': float(confidences[i]),
                'x': float(boxes[i, 0] * scale_x),  # center x
                'y': float(boxes[i, 1] * scale_y),  # center y
                'w': float(boxes[i, 2] * scale_x),
                'h': float(boxes[i, 3] * scale_y),
            })
        
        return detections
    
    def infer(self, frame: np.ndarray) -> Tuple[List[dict], float]:
        """
        Run full inference pipeline.
        
        Args:
            frame: BGR uint8 image
            
        Returns:
            (detections, inference_ms)
        """
        t0 = time.perf_counter()
        
        orig_h, orig_w = frame.shape[:2]
        tensor = self.preprocess(frame)
        
        # Run inference
        outputs = self.session.run(self.output_names, {self.input_name: tensor})
        
        # Postprocess
        detections = self.postprocess(outputs[0], orig_w, orig_h)
        
        elapsed = (time.perf_counter() - t0) * 1000
        return detections, elapsed
    
    @property
    def provider_name(self) -> str:
        return self._provider_used
    
    def release(self):
        """Release ONNX session."""
        self.session = None


__all__ = ['DirectMLProvider', 'has_directml']
