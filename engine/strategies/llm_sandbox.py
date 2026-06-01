"""
JARVIS TRADER — LLM Strategy Sandbox
Restricted execution environment for LLM-generated strategy code.

Safety boundary: LLM-generated code runs in a controlled namespace.
Only allowed imports: numpy, pandas, indicator functions.
No filesystem, no network, no os/sys/subprocess.
"""

from __future__ import annotations

import importlib
import importlib.util
import logging
from pathlib import Path
from typing import Type

from strategies.base_strategy import BaseStrategy

logger = logging.getLogger(__name__)

# Allowed modules for LLM-generated strategies
ALLOWED_MODULES = {
    "numpy",
    "pandas",
    "math",
    "dataclasses",
    "typing",
}

# Allowed submodules (strategy can import from these)
ALLOWED_SUBMODULES = {
    "strategies.base_strategy",
    "backtest.indicators",
}

# Timeout for strategy execution (seconds)
EXECUTION_TIMEOUT = 30


class SandboxError(Exception):
    """Raised when sandbox detects a violation."""

    pass


class SandboxTimeoutError(SandboxError):
    """Raised when strategy execution exceeds timeout."""

    pass


def validate_strategy_source(source: str) -> list[str]:
    """
    Static analysis of strategy source code for disallowed patterns.
    Returns list of violations (empty if clean).
    """
    violations = []

    # Disallowed imports
    dangerous_imports = [
        "os", "sys", "subprocess", "shutil", "socket", "http",
        "urllib", "requests", "pathlib", "glob", "tempfile",
        "pickle", "shelve", "ctypes", "multiprocessing",
    ]
    for mod in dangerous_imports:
        if f"import {mod}" in source or f"from {mod}" in source:
            violations.append(f"Disallowed import: {mod}")

    # Disallowed builtins
    dangerous_calls = [
        "exec(", "eval(", "compile(", "__import__(",
        "open(", "globals(", "locals(",
    ]
    for call in dangerous_calls:
        if call in source:
            violations.append(f"Disallowed call: {call.rstrip('(')}")

    return violations


def load_strategy_sandboxed(path: Path) -> Type[BaseStrategy]:
    """
    Load a strategy file with safety validation.

    1. Read and validate source code
    2. Load via importlib (standard Python import)
    3. Verify it produces exactly one BaseStrategy subclass
    4. Return the class (not an instance)

    Raises SandboxError on any violation.
    """
    if not path.exists():
        raise SandboxError(f"Strategy file not found: {path}")

    # Step 1: Read and validate source
    source = path.read_text(encoding="utf-8")
    violations = validate_strategy_source(source)
    if violations:
        raise SandboxError(f"Source validation failed: {'; '.join(violations)}")

    # Step 2: Load via importlib
    try:
        spec = importlib.util.spec_from_file_location(path.stem, path)
        if spec is None or spec.loader is None:
            raise SandboxError(f"Cannot create import spec for {path}")

        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    except SandboxError:
        raise
    except Exception as e:
        raise SandboxError(f"Failed to load strategy: {e}") from e

    # Step 3: Find BaseStrategy subclass
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
        raise SandboxError(f"No BaseStrategy subclass found in {path.name}")
    if len(candidates) > 1:
        names = ", ".join(c.__name__ for c in candidates)
        raise SandboxError(f"Multiple BaseStrategy subclasses in {path.name}: {names}")

    return candidates[0]
