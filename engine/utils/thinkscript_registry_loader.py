"""Load and cache the ThinkScript registry YAML."""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

import yaml

from schemas.thinkscript_registry import ScriptRegistry

DEFAULT_REGISTRY_PATH = Path("C:/Users/mattm/ThinkorSwim/jarvis-trader/thinkorswim-scripts/registry.yaml")


def _resolve_path() -> Path:
    env = os.environ.get("JARVIS_TRADER_SCRIPTS_PATH")
    if env:
        return Path(env) / "registry.yaml"
    return DEFAULT_REGISTRY_PATH


@lru_cache(maxsize=1)
def load_registry() -> ScriptRegistry:
    path = _resolve_path()
    if not path.exists():
        raise FileNotFoundError(
            f"registry.yaml not found at {path}. Set JARVIS_TRADER_SCRIPTS_PATH env var."
        )
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    return ScriptRegistry(**raw)


def read_doc(doc_relative_path: str) -> str:
    base = _resolve_path().parent
    doc_path = base / doc_relative_path
    if not doc_path.exists():
        return ""
    return doc_path.read_text(encoding="utf-8")
