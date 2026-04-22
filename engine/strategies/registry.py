"""
JARVIS TRADER — Strategy Registry with Hot-Loading
Dynamic importlib-based strategy discovery and management.
Inspired by rv64m/autotrade's strategy loader pattern.
"""

from __future__ import annotations

import importlib
import importlib.util
import logging
from pathlib import Path
from typing import Dict, List, Optional

from strategies.base_strategy import BaseStrategy

logger = logging.getLogger(__name__)

_GENERATED_DIR = Path(__file__).parent / "generated"
_BUILTIN_DIR = Path(__file__).parent / "builtin"


class StrategyRegistry:
    """Hot-loadable strategy registry with importlib dynamic loading."""

    def __init__(self) -> None:
        self._strategies: Dict[str, BaseStrategy] = {}

    def load_from_file(self, path: Path) -> BaseStrategy:
        """
        Dynamic import of a strategy file.
        Expects exactly one BaseStrategy subclass in the module.
        """
        if not path.exists():
            raise FileNotFoundError(f"Strategy file not found: {path}")

        spec = importlib.util.spec_from_file_location(path.stem, path)
        if spec is None or spec.loader is None:
            raise ImportError(f"Cannot create import spec for {path}")

        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        candidates = []
        for attr_name in dir(module):
            if attr_name.startswith("_"):
                continue
            obj = getattr(module, attr_name)
            if (
                isinstance(obj, type)
                and issubclass(obj, BaseStrategy)
                and obj is not BaseStrategy
            ):
                candidates.append(obj)

        if not candidates:
            raise ValueError(f"No BaseStrategy subclass found in {path.name}")
        if len(candidates) > 1:
            names = ", ".join(c.__name__ for c in candidates)
            raise ValueError(f"Multiple BaseStrategy subclasses in {path.name}: {names}")

        instance = candidates[0]()
        self._strategies[instance.name or path.stem] = instance
        logger.info(f"Loaded strategy: {instance}")
        return instance

    def scan_generated(self) -> List[str]:
        """Scan generated/ directory and load all strategy files."""
        loaded = []
        for path in sorted(_GENERATED_DIR.glob("*.py")):
            if path.name == "__init__.py":
                continue
            try:
                instance = self.load_from_file(path)
                loaded.append(instance.name or path.stem)
            except Exception as e:
                logger.warning(f"Failed to load {path.name}: {e}")
        return loaded

    def scan_builtin(self) -> List[str]:
        """Scan builtin/ directory and load all strategy files."""
        loaded = []
        for path in sorted(_BUILTIN_DIR.glob("*.py")):
            if path.name == "__init__.py":
                continue
            try:
                instance = self.load_from_file(path)
                loaded.append(instance.name or path.stem)
            except Exception as e:
                logger.warning(f"Failed to load {path.name}: {e}")
        return loaded

    def scan_all(self) -> List[str]:
        """Load all strategies from both builtin and generated directories."""
        return self.scan_builtin() + self.scan_generated()

    def get(self, name: str) -> Optional[BaseStrategy]:
        """Get a strategy by name."""
        return self._strategies.get(name)

    def list_all(self) -> List[dict]:
        """Return metadata for all loaded strategies."""
        return [s.metadata() for s in self._strategies.values()]

    def list_kept(self) -> List[dict]:
        """Return metadata for strategies with keep=True."""
        return [s.metadata() for s in self._strategies.values() if s.keep]

    def remove(self, name: str) -> bool:
        """Remove a strategy from the registry."""
        if name in self._strategies:
            del self._strategies[name]
            return True
        return False

    @property
    def count(self) -> int:
        return len(self._strategies)
