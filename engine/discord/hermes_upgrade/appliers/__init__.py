"""Per-type appliers. Each subclass of BaseApplier implements one UpgradeType."""

from .base import BaseApplier
from .config_patcher import ConfigPatcher
from .cron_register import CronRegister
from .library_integrator import LibraryIntegrator
from .mcp_adder import McpAdder
from .skill_installer import SkillInstaller
from .soul_patcher import SoulPatcher

__all__ = [
    "BaseApplier",
    "ConfigPatcher",
    "CronRegister",
    "LibraryIntegrator",
    "McpAdder",
    "SkillInstaller",
    "SoulPatcher",
]
