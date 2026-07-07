"""
FreqAI "Data Kitchen" Pattern
============================
Handles specialized data preparation, normalization, and windowing
for machine learning models in the JARVIS engine.
"""

from typing import Optional, Tuple

import numpy as np
import pandas as pd


class FreqaiDataKitchen:
    def __init__(self, window_size: int = 100, live: bool = False):
        self.window_size = window_size
        self.live = live
        self._mean: Optional[pd.Series] = None
        self._std: Optional[pd.Series] = None

    def prepare_data(self, df: pd.DataFrame, target_col: str) -> Tuple[pd.DataFrame, pd.Series]:
        """
        Clean, normalize, and split features from targets.
        """
        df = df.copy()

        # 1. Handle NaNs
        df = df.ffill().bfill()

        # 2. Extract Label
        y = df[target_col].shift(-1) # Predict next bar
        X = df.drop(columns=[target_col])

        # 3. Normalization (Z-Score)
        if not self.live or self._mean is None:
            self._mean = X.mean()
            self._std = X.std().replace(0, 1)

        X_norm = (X - self._mean) / self._std

        return X_norm.dropna(), y.loc[X_norm.dropna().index]

    def create_sliding_windows(self, X: pd.DataFrame, y: pd.Series) -> Tuple[np.ndarray, np.ndarray]:
        """
        Convert tabular data to 3D windows (Samples, TimeSteps, Features).
        """
        X_values = X.values
        y_values = y.values

        X_windows = []
        y_windows = []

        for i in range(len(X_values) - self.window_size):
            X_windows.append(X_values[i : i + self.window_size])
            y_windows.append(y_values[i + self.window_size])

        return np.array(X_windows), np.array(y_windows)

    def data_cleaning_predict(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Ensure consistent formatting for live inference.
        """
        if self._mean is not None:
            return (df - self._mean) / self._std
        return df
