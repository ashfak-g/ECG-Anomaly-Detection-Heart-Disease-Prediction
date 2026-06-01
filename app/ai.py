"""
ai.py — ECG Analysis using Local Deep Learning Model + Gemini Fallback.

Primary: Uses trained CNN+BiLSTM+Attention model for inference
Fallback: Google Gemini Vision API (if model fails or env var set)
"""

import os
import logging
import time
import numpy as np
import json
from PIL import Image
from typing import Tuple, Dict, Optional

logger = logging.getLogger(__name__)

# ============================================================================
# LOCAL DL MODEL (Primary)
# ============================================================================

_ml_engine = None


def _get_ml_engine():
    """Lazy-initialize the ML engine (ModelManager)."""
    global _ml_engine
    if _ml_engine is not None:
        return _ml_engine
    
    try:
        from app.ml_engine import get_model_manager
        _ml_engine = get_model_manager()
        logger.info("ML Engine initialized successfully")
        return _ml_engine
    except Exception as e:
        logger.warning(f"Failed to initialize ML Engine: {e}")
        return None


# ============================================================================
# IMAGE PROCESSING
# ============================================================================

def extract_signal_from_image(image_path: str) -> Optional[np.ndarray]:
    """
    Extract ECG signal from image.
    
    Currently a placeholder that returns None (image preprocessing not yet implemented).
    Future: Implement image → signal extraction using contour detection, etc.
    
    Args:
        image_path: Path to ECG image
        
    Returns:
        ECG signal array (187 values) or None if extraction fails
    """
    try:
        img = Image.open(image_path).convert("L")
        arr = np.asarray(img, dtype=np.float32)
        if arr.ndim != 2:
            return None

        height, width = arr.shape
        if height < 64 or width < 64:
            logger.warning("Image is too small for reliable ECG extraction")
            return None

        # Remove borders that usually contain labels/grid artifacts.
        y0, y1 = int(height * 0.05), int(height * 0.95)
        x0, x1 = int(width * 0.03), int(width * 0.97)
        roi = arr[y0:y1, x0:x1]
        if roi.size == 0:
            return None

        # Basic quality gate: if contrast is too low, extraction is unreliable.
        if float(np.std(roi)) < 8.0:
            logger.warning("Low-contrast image; signal extraction skipped")
            return None

        h, w = roi.shape
        x_idx = np.arange(w)
        col_min_y = np.argmin(roi, axis=0).astype(np.float32)
        col_min_val = np.min(roi, axis=0)

        # Keep columns with sufficiently dark trace candidates.
        dark_threshold = np.percentile(col_min_val, 40)
        valid = col_min_val <= dark_threshold
        if int(np.count_nonzero(valid)) < max(20, int(w * 0.15)):
            logger.warning("Could not detect stable ECG trace columns")
            return None

        if not np.all(valid):
            valid_x = x_idx[valid]
            valid_y = col_min_y[valid]
            col_min_y = np.interp(x_idx, valid_x, valid_y)

        # Smooth traced curve with a small moving-average kernel.
        kernel_size = max(5, (w // 80) * 2 + 1)
        kernel = np.ones(kernel_size, dtype=np.float32) / float(kernel_size)
        smooth_y = np.convolve(col_min_y, kernel, mode="same")

        # Convert y-position to a normalized waveform in [-1, 1].
        signal = ((h - 1 - smooth_y) / max(1.0, (h - 1))) * 2.0 - 1.0

        # Resample to model input length (187).
        target_len = 187
        src_x = np.linspace(0.0, 1.0, num=signal.size, endpoint=True)
        tgt_x = np.linspace(0.0, 1.0, num=target_len, endpoint=True)
        signal = np.interp(tgt_x, src_x, signal).astype(np.float32)

        # Final normalization and stability checks.
        sig_std = float(np.std(signal))
        if sig_std < 1e-6:
            logger.warning("Extracted signal has near-zero variance")
            return None

        signal = (signal - float(np.mean(signal))) / sig_std
        signal = np.clip(signal, -5.0, 5.0).astype(np.float32)
        return signal

    except Exception as e:
        logger.error(f"Failed to extract ECG signal from image: {e}")
        return None


# ============================================================================
# GEMINI FALLBACK (Legacy)
# ============================================================================

_gemini_model = None


def _get_gemini_model():
    """Lazy-initialise the Gemini generative model."""
    global _gemini_model
    if _gemini_model is not None:
        return _gemini_model

    api_key = os.environ.get('GEMINI_API_KEY')
    if not api_key:
        logger.debug("GEMINI_API_KEY not set")
        return None

    try:
        from google import genai
        _gemini_model = genai.Client(api_key=api_key)
        logger.info("Gemini Vision model initialised successfully.")
        return _gemini_model
    except Exception as exc:
        logger.error("Failed to initialise Gemini model: %s", exc)
        return None


ECG_ANALYSIS_PROMPT = """You are a medical AI assistant specializing in ECG analysis.

Analyze this ECG image and determine if it shows normal or abnormal heart rhythm.

Return a JSON object with:
{
  "result": "Normal" or "Abnormal",
  "confidence": <float 0.0-1.0>,
  "details": "<brief explanation>"
}
"""


def _predict_with_gemini(image_path: str) -> Tuple[str, float]:
    """
    Fallback prediction using Gemini Vision API.
    
    Args:
        image_path: Path to ECG image
        
    Returns:
        (result, confidence)
    """
    client = _get_gemini_model()
    if client is None:
        return "Unknown", 0.0

    try:
        img = Image.open(image_path)
        from google import genai
        # Read the prompt and image using the new google-genai syntax
        response = client.models.generate_content(
            model='gemini-2.5-flash',
            contents=[ECG_ANALYSIS_PROMPT, img],
            config=genai.types.GenerateContentConfig(
                temperature=0.1,
                max_output_tokens=300,
            )
        )

        text = response.text.strip()
        if text.startswith("```"):
            lines = [line for line in text.splitlines() if not line.strip().startswith("```")]
            text = "\n".join(lines).strip()

        logger.info(f"Gemini response: {text[:200]}")

        # Basic JSON extraction
        try:
            data = json.loads(text)
            result = data.get("result", "Unknown")
            confidence = float(data.get("confidence", 0.5))
            confidence = max(0.0, min(1.0, confidence))
            if result not in ("Normal", "Abnormal"):
                result = "Abnormal"
            return result, confidence
        except json.JSONDecodeError:
            logger.warning("Failed to parse Gemini JSON response")
            return "Unknown", 0.5

    except Exception as e:
        logger.error(f"Gemini prediction failed: {e}")
        return "Unknown", 0.0


# ============================================================================
# PUBLIC API
# ============================================================================

def predict_image(image_path: str) -> Tuple[str, float, Dict]:
    """
    Analyse an ECG image and return prediction.
    
    Primary: Local DL model
    Fallback: Gemini Vision API (if enabled)
    
    Args:
        image_path: Absolute path to ECG image
        
    Returns:
        (result, confidence, metadata_dict)
        - result: "Normal" or "Abnormal"
        - confidence: float 0.0-1.0
        - metadata_dict: {
            "method": "dl_model" or "gemini",
            "processing_time_ms": float,
            "class_name": Optional[str],  # For DL model
            "all_probabilities": Optional[Dict]  # For DL model
          }
    """
    start_time = time.time()
    metadata = {
        "method": None,
        "processing_time_ms": 0.0,
        "class_name": None,
        "all_probabilities": None
    }

    # Try local DL model first
    try:
        ml_engine = _get_ml_engine()
        if ml_engine is not None:
            # Try to extract signal from image
            signal = extract_signal_from_image(image_path)
            
            if signal is not None and len(signal) == 187:
                # Success: Use DL model with actual signal
                class_name, confidence, probabilities = ml_engine.predict(signal)
                
                processing_time = (time.time() - start_time) * 1000
                
                # Map class to Normal/Abnormal
                result = "Normal" if class_name == "N" else "Abnormal"
                
                metadata["method"] = "dl_model"
                metadata["processing_time_ms"] = processing_time
                metadata["class_name"] = class_name
                metadata["all_probabilities"] = probabilities
                
                logger.info(f"DL prediction: {class_name} ({confidence:.4f}) "
                           f"in {processing_time:.2f}ms")
                
                return result, confidence, metadata
            else:
                logger.warning("Signal extraction failed or invalid signal length")
                # Fall through to Gemini fallback below
    
    except Exception as e:
        logger.error(f"DL model prediction failed: {e}")
        # Fall through to Gemini fallback below

    # Fallback to Gemini
    logger.info("Falling back to Gemini Vision API")
    try:
        result, confidence = _predict_with_gemini(image_path)
        
        processing_time = (time.time() - start_time) * 1000
        metadata["method"] = "gemini"
        metadata["processing_time_ms"] = processing_time
        
        logger.info(f"Gemini fallback: {result} ({confidence:.4f})")
        return result, confidence, metadata
    
    except Exception as e:
        logger.error(f"All prediction methods failed: {e}")
        # Return default error response
        processing_time = (time.time() - start_time) * 1000
        metadata["method"] = "error"
        metadata["processing_time_ms"] = processing_time
        return "Unknown", 0.0, metadata


def predict_signal(signal: np.ndarray) -> Tuple[str, float, Dict]:
    """
    Analyse an ECG signal directly (no image).
    
    Args:
        signal: ECG signal array (187 values)
        
    Returns:
        (result, confidence, metadata_dict)
    """
    start_time = time.time()
    metadata = {
        "method": None,
        "processing_time_ms": 0.0,
        "class_name": None,
        "all_probabilities": None
    }

    try:
        ml_engine = _get_ml_engine()
        if ml_engine is None:
            raise RuntimeError("ML Engine not available")
        
        class_name, confidence, probabilities = ml_engine.predict(signal)
        
        processing_time = (time.time() - start_time) * 1000
        
        # Map class to Normal/Abnormal
        result = "Normal" if class_name == "N" else "Abnormal"
        
        metadata["method"] = "dl_model"
        metadata["processing_time_ms"] = processing_time
        metadata["class_name"] = class_name
        metadata["all_probabilities"] = probabilities
        
        logger.info(f"Signal prediction: {class_name} ({confidence:.4f}) "
                   f"in {processing_time:.2f}ms")
        
        return result, confidence, metadata
    
    except Exception as e:
        logger.error(f"Signal prediction failed: {e}")
        processing_time = (time.time() - start_time) * 1000
        metadata["method"] = "error"
        metadata["processing_time_ms"] = processing_time
        return "Unknown", 0.0, metadata


def get_model_status() -> Dict:
    """Get model status and health information."""
    try:
        from app.ml_engine import get_model_status
        return get_model_status()
    except Exception as e:
        return {
            "status": "error",
            "error": str(e)
        }
