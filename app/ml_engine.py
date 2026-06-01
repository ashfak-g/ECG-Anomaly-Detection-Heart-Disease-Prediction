"""
ml_engine.py — Deep Learning Model Management for ECG Classification.

Handles model loading, caching, preprocessing, and inference for the
trained CNN+BiLSTM+Attention model.
"""

import os
import json
import logging
import numpy as np
from pathlib import Path
import time
from typing import Tuple, Dict, List, Optional

logger = logging.getLogger(__name__)

# Global model cache
_model_cache = None
_metadata_cache = None
_model_lock = None


class ModelException(Exception):
    """Custom exception for model-related errors."""
    pass


def _build_custom_objects():
    """Create custom objects required for model deserialization."""
    import tensorflow as tf

    class MultiHeadSelfAttention(tf.keras.layers.Layer):
        """Training-parity Multi-Head Self-Attention layer."""

        def __init__(self, embed_dim=128, num_heads=4, dropout_rate=0.1, **kwargs):
            super().__init__(**kwargs)
            self.embed_dim = int(embed_dim)
            self.num_heads = int(num_heads)
            if self.embed_dim % self.num_heads != 0:
                raise ValueError("embed_dim must be divisible by num_heads")
            self.projection_dim = self.embed_dim // self.num_heads
            self.dropout_rate = float(dropout_rate)

            self.query_dense = tf.keras.layers.Dense(self.embed_dim)
            self.key_dense = tf.keras.layers.Dense(self.embed_dim)
            self.value_dense = tf.keras.layers.Dense(self.embed_dim)
            self.combine_heads = tf.keras.layers.Dense(self.embed_dim)
            self.dropout = tf.keras.layers.Dropout(self.dropout_rate)
            self.layer_norm = tf.keras.layers.LayerNormalization(epsilon=1e-6)

        def _split_heads(self, x, batch_size):
            x = tf.reshape(x, (batch_size, -1, self.num_heads, self.projection_dim))
            return tf.transpose(x, perm=[0, 2, 1, 3])

        def _attention(self, q, k, v, training=None):
            scale = tf.math.sqrt(tf.cast(tf.shape(k)[-1], tf.float32))
            scores = tf.matmul(q, k, transpose_b=True) / scale
            weights = tf.nn.softmax(scores, axis=-1)
            weights = self.dropout(weights, training=training)
            return tf.matmul(weights, v)

        def call(self, inputs, training=None):
            batch_size = tf.shape(inputs)[0]
            q = self._split_heads(self.query_dense(inputs), batch_size)
            k = self._split_heads(self.key_dense(inputs), batch_size)
            v = self._split_heads(self.value_dense(inputs), batch_size)

            attn = self._attention(q, k, v, training=training)
            attn = tf.transpose(attn, perm=[0, 2, 1, 3])
            attn = tf.reshape(attn, (batch_size, -1, self.embed_dim))

            out = self.combine_heads(attn)
            out = self.dropout(out, training=training)
            return self.layer_norm(inputs + out)

        def get_config(self):
            config = super().get_config()
            config.update(
                {
                    'embed_dim': self.embed_dim,
                    'num_heads': self.num_heads,
                    'dropout_rate': self.dropout_rate,
                }
            )
            return config

    class FeedForward(tf.keras.layers.Layer):
        """Training-parity feed-forward residual block."""

        def __init__(self, d_model, dff, dropout_rate=0.1, **kwargs):
            super().__init__(**kwargs)
            self.d_model = int(d_model)
            self.dff = int(dff)
            self.dropout_rate = float(dropout_rate)

            self.dense1 = tf.keras.layers.Dense(self.dff, activation='relu')
            self.dense2 = tf.keras.layers.Dense(self.d_model)
            self.dropout = tf.keras.layers.Dropout(self.dropout_rate)
            self.layer_norm = tf.keras.layers.LayerNormalization(epsilon=1e-6)

        def call(self, x, training=None):
            residual = x
            x = self.dense1(x)
            x = self.dense2(x)
            x = self.dropout(x, training=training)
            return self.layer_norm(residual + x)

        def get_config(self):
            config = super().get_config()
            config.update(
                {
                    'd_model': self.d_model,
                    'dff': self.dff,
                    'dropout_rate': self.dropout_rate,
                }
            )
            return config

    class StochasticDepth(tf.keras.layers.Layer):
        """Training-parity stochastic depth (DropPath) layer."""

        def __init__(self, survival_prob=0.8, **kwargs):
            super().__init__(**kwargs)
            self.survival_prob = float(survival_prob)

        def call(self, x, training=None):
            if training is False:
                return x
            batch = tf.shape(x)[0]
            random_depth = self.survival_prob + tf.random.uniform([batch, 1, 1], dtype=x.dtype)
            binary_mask = tf.floor(random_depth)
            return (x / self.survival_prob) * binary_mask

        def get_config(self):
            config = super().get_config()
            config.update({'survival_prob': self.survival_prob})
            return config

    return {
        'MultiHeadSelfAttention': MultiHeadSelfAttention,
        'FeedForward': FeedForward,
        'StochasticDepth': StochasticDepth,
    }


class ModelManager:
    """
    Manages the lifecycle of the ECG classification model.
    
    Responsibilities:
    - Load and cache the trained model
    - Load model metadata
    - Preprocess ECG signals
    - Run inference
    - Post-process predictions
    """
    
    def __init__(self, model_dir: str = None):
        """
        Initialize the ModelManager.
        
        Args:
            model_dir: Path to models directory. Defaults to app/models/
        """
        if model_dir is None:
            # Get absolute path to models directory
            project_root = Path(__file__).parent.parent
            model_dir = project_root / "models"
        
        self.model_dir = Path(model_dir)
        self.model_path = self.model_dir / "best_model.keras"
        self.metadata_path = self.model_dir / "metadata.json"
        
        # Validate paths
        if not self.model_path.exists():
            raise ModelException(f"Model not found at {self.model_path}")
        if not self.metadata_path.exists():
            raise ModelException(f"Metadata not found at {self.metadata_path}")
        
        # Load metadata
        self.metadata = self._load_metadata()
        
        # Load model
        self.model = self._load_model()
        
        # Performance tracking
        self.inference_times = []
        self.prediction_count = 0
        
        logger.info(f"ModelManager initialized with model from {self.model_path}")
    
    def _load_metadata(self) -> Dict:
        """Load and validate model metadata."""
        try:
            with open(self.metadata_path, 'r') as f:
                metadata = json.load(f)
            
            # Validate required fields
            required_fields = ['class_names', 'input_length', 'num_classes']
            for field in required_fields:
                if field not in metadata:
                    raise ModelException(f"Missing metadata field: {field}")
            
            logger.info(f"Metadata loaded: {len(metadata['class_names'])} classes, "
                       f"input_length={metadata['input_length']}")
            return metadata
        except json.JSONDecodeError as e:
            raise ModelException(f"Invalid JSON in metadata: {e}")
        except Exception as e:
            raise ModelException(f"Failed to load metadata: {e}")
    
    def _load_model(self):
        """Load the Keras model."""
        try:
            import tensorflow as tf
            custom_objects = _build_custom_objects()
            model = tf.keras.models.load_model(
                str(self.model_path),
                custom_objects=custom_objects,
                compile=False,
            )
            logger.info(f"Model loaded successfully. Parameters: {model.count_params()}")
            return model
        except ImportError as e:
            if getattr(e, 'name', '') == 'tensorflow':
                raise ModelException("TensorFlow not installed. Install with: pip install tensorflow")
            raise ModelException(f"Dependency import failed while loading model: {e}")
        except Exception as e:
            raise ModelException(f"Failed to load model: {e}")
    
    def preprocess_signal(self, signal: np.ndarray) -> np.ndarray:
        """
        Preprocess ECG signal for inference.
        
        Args:
            signal: Raw ECG signal (1D array)
        
        Returns:
            Preprocessed signal ready for model input (1, 187)
        
        Raises:
            ModelException: If signal is invalid
        """
        try:
            # Convert to numpy array if needed
            if isinstance(signal, list):
                signal = np.array(signal, dtype=np.float32)
            elif not isinstance(signal, np.ndarray):
                signal = np.array(signal, dtype=np.float32)
            
            # Validate length
            expected_length = self.metadata['input_length']
            if len(signal) != expected_length:
                raise ModelException(
                    f"Signal length {len(signal)} != expected {expected_length}"
                )
            
            # Check for NaN/Inf
            if np.isnan(signal).any() or np.isinf(signal).any():
                raise ModelException("Signal contains NaN or Inf values")
            
            # Normalize: subtract mean, divide by std
            # (assuming standard ECG signal normalization)
            signal = signal.astype(np.float32)
            
            # Add batch dimension: (187,) → (1, 187)
            signal = np.expand_dims(signal, axis=0)
            
            return signal
        except ModelException:
            raise
        except Exception as e:
            raise ModelException(f"Preprocessing failed: {e}")
    
    def predict(self, signal: np.ndarray) -> Tuple[str, float, Dict]:
        """
        Run inference on a single ECG signal.
        
        Args:
            signal: ECG signal (187 timesteps)
        
        Returns:
            tuple: (class_name, confidence, class_probabilities_dict)
        
        Raises:
            ModelException: If inference fails
        """
        start_time = time.time()
        
        try:
            # Preprocess
            processed_signal = self.preprocess_signal(signal)
            
            # Inference
            logits = self.model.predict(processed_signal, verbose=0)
            
            # Softmax to get probabilities
            import tensorflow as tf
            probabilities = tf.nn.softmax(logits[0]).numpy()
            
            # Get class with highest probability
            class_idx = np.argmax(probabilities)
            class_name = self.metadata['class_names'][class_idx]
            confidence = float(probabilities[class_idx])
            
            # Build probability dictionary
            prob_dict = {
                self.metadata['class_names'][i]: float(probabilities[i])
                for i in range(len(self.metadata['class_names']))
            }
            
            # Track performance
            inference_time = time.time() - start_time
            self.inference_times.append(inference_time)
            self.prediction_count += 1
            
            logger.info(f"Prediction: {class_name} (confidence: {confidence:.4f}, "
                       f"time: {inference_time*1000:.2f}ms)")
            
            return class_name, confidence, prob_dict
        
        except ModelException:
            raise
        except Exception as e:
            raise ModelException(f"Inference failed: {e}")
    
    def batch_predict(self, signals: List[np.ndarray]) -> List[Tuple[str, float, Dict]]:
        """
        Run inference on multiple ECG signals.
        
        Args:
            signals: List of ECG signals
        
        Returns:
            List of (class_name, confidence, probabilities) tuples
        """
        results = []
        for signal in signals:
            try:
                result = self.predict(signal)
                results.append(result)
            except ModelException as e:
                logger.error(f"Batch prediction failed for one signal: {e}")
                results.append((None, 0.0, {}))
        
        return results
    
    def get_class_names(self) -> List[str]:
        """Get all class names."""
        return self.metadata['class_names']
    
    def get_class_full_names(self) -> List[str]:
        """Get full names of classes (e.g., 'Supraventricular' for 'S')."""
        return self.metadata.get('class_full', self.metadata['class_names'])
    
    def get_model_info(self) -> Dict:
        """Get model metadata and performance info."""
        avg_inference_time = (
            np.mean(self.inference_times) if self.inference_times else 0.0
        )
        
        return {
            'model_path': str(self.model_path),
            'input_length': self.metadata['input_length'],
            'num_classes': self.metadata['num_classes'],
            'class_names': self.metadata['class_names'],
            'class_full_names': self.get_class_full_names(),
            'test_accuracy': self.metadata.get('test_accuracy', None),
            'test_auc': self.metadata.get('test_auc', None),
            'total_predictions': self.prediction_count,
            'avg_inference_time_ms': avg_inference_time * 1000,
            'num_model_parameters': self.model.count_params()
        }


# Global model manager instance
_model_manager = None


def get_model_manager() -> ModelManager:
    """
    Get or create the global ModelManager instance (singleton).
    
    Returns:
        ModelManager instance
    
    Raises:
        ModelException: If model initialization fails
    """
    global _model_manager
    
    if _model_manager is None:
        try:
            _model_manager = ModelManager()
        except ModelException as e:
            logger.error(f"Failed to initialize ModelManager: {e}")
            raise
    
    return _model_manager


def predict_signal(signal: np.ndarray) -> Tuple[str, float, Dict]:
    """
    Convenience function for quick inference.
    
    Args:
        signal: ECG signal array
    
    Returns:
        (class_name, confidence, probabilities)
    """
    manager = get_model_manager()
    return manager.predict(signal)


def get_model_status() -> Dict:
    """Get model health and status information."""
    try:
        manager = get_model_manager()
        return {
            'status': 'healthy',
            'model_info': manager.get_model_info()
        }
    except Exception as e:
        return {
            'status': 'error',
            'error': str(e)
        }
