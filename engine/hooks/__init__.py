"""Trading hook system — event-driven automations (ECC pattern)."""

from .registry import HookRegistry, get_hook_registry

__all__ = ["HookRegistry", "get_hook_registry"]
