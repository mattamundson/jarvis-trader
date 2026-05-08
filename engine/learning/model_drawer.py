"""
FreqAI "Model Drawer" Pattern
============================
Handles model versioning, persistence, and inference for the Super-Engine.
"""

import logging
import os
from typing import Optional

try:
    import joblib  # noqa: F401 — imported for availability check
    import xgboost as xgb

    _ML_DEPS_AVAILABLE = True
except ImportError:
    xgb = None  # type: ignore[assignment]
    joblib = None  # type: ignore[assignment]
    _ML_DEPS_AVAILABLE = False

logger = logging.getLogger("jarvis_trader.learning.model_drawer")


class ModelDrawer:
    def __init__(self, model_dir: str = "models"):
        self.model_dir = model_dir
        os.makedirs(model_dir, exist_ok=True)
        self.current_model: Optional[object] = None

    def save_model(self, model: object, symbol: str) -> None:
        if not _ML_DEPS_AVAILABLE:
            logger.warning("model_drawer: xgboost/joblib not installed — skipping save_model")
            return None
        path = os.path.join(self.model_dir, f"{symbol}_latest.json")
        model.save_model(path)  # type: ignore[union-attr]
        logger.info(f"Model saved to {path}")

    def load_model(self, symbol: str) -> bool:
        if not _ML_DEPS_AVAILABLE:
            logger.warning("model_drawer: xgboost/joblib not installed — skipping load_model")
            return False
        path = os.path.join(self.model_dir, f"{symbol}_latest.json")
        if os.path.exists(path):
            self.current_model = xgb.XGBRegressor()  # type: ignore[union-attr]
            self.current_model.load_model(path)  # type: ignore[union-attr]
            return True
        return False

    def predict(self, X: object) -> object:
        if not _ML_DEPS_AVAILABLE:
            logger.warning("model_drawer: xgboost/joblib not installed — skipping predict")
            return None
        if self.current_model:
            return self.current_model.predict(X)  # type: ignore[union-attr]
        return None
