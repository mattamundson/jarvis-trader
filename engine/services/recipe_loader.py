"""Trading playbook recipe loader ported from Goose crates/goose/src/recipe/build_recipe/.

Lightweight dataclass-validated YAML recipes. No templating engine.
Standalone — no engine imports besides stdlib and PyYAML.
"""
from dataclasses import dataclass, field
from pathlib import Path

import yaml


@dataclass
class RecipeParameters:
    entry_max_vix: float = 28.0
    min_confluence: float = 0.65
    size_mult: float = 1.0


@dataclass
class Recipe:
    name: str
    version: int
    parameters: RecipeParameters
    required_tools: list[str] = field(default_factory=list)
    steps: list[str] = field(default_factory=list)


class RecipeValidationError(ValueError):
    """Raised when a recipe fails schema validation."""


class RecipeLoader:
    def __init__(self, recipes_dir: str | Path):
        self.recipes_dir = Path(recipes_dir)

    def load(self, name: str) -> Recipe:
        """Load `<name>.yaml` from recipes_dir, parse, validate, return Recipe."""
        path = self.recipes_dir / f"{name}.yaml"
        if not path.exists():
            raise FileNotFoundError(f"Recipe not found: {path}")
        with open(path, "r") as f:
            raw = yaml.safe_load(f)
        params_raw = raw.get("parameters", {}) or {}
        params = RecipeParameters(
            entry_max_vix=float(params_raw.get("entry_max_vix", 28.0)),
            min_confluence=float(params_raw.get("min_confluence", 0.65)),
            size_mult=float(params_raw.get("size_mult", 1.0)),
        )
        recipe = Recipe(
            name=raw.get("name", ""),
            version=int(raw.get("version", 0)),
            parameters=params,
            required_tools=list(raw.get("required_tools", []) or []),
            steps=list(raw.get("steps", []) or []),
        )
        self.validate(recipe)
        return recipe

    def list_available(self) -> list[str]:
        """Return names of all *.yaml files in recipes_dir (without extension)."""
        if not self.recipes_dir.exists():
            return []
        return sorted(p.stem for p in self.recipes_dir.glob("*.yaml"))

    def validate(self, recipe: Recipe) -> None:
        """Raise RecipeValidationError on any invalid field."""
        if not recipe.name or not isinstance(recipe.name, str):
            raise RecipeValidationError("name must be non-empty string")
        if recipe.version < 1:
            raise RecipeValidationError(f"version must be >= 1, got {recipe.version}")
        p = recipe.parameters
        if not (10.0 <= p.entry_max_vix <= 80.0):
            raise RecipeValidationError(
                f"entry_max_vix must be in [10, 80], got {p.entry_max_vix}"
            )
        if not (0.0 <= p.min_confluence <= 1.0):
            raise RecipeValidationError(
                f"min_confluence must be in [0, 1], got {p.min_confluence}"
            )
        if not (0.5 <= p.size_mult <= 1.5):
            raise RecipeValidationError(
                f"size_mult must be in [0.5, 1.5] (JARVIS sizing bounds), got {p.size_mult}"
            )
        if not isinstance(recipe.required_tools, list):
            raise RecipeValidationError("required_tools must be a list")
        if not all(isinstance(t, str) for t in recipe.required_tools):
            raise RecipeValidationError("required_tools must contain only strings")


# Wired at engine/agents/pipeline.py:TradingPipeline.analyze_and_decide via
# the optional active_recipe_name kwarg. When set, the recipe's entry_max_vix,
# min_confluence, and size_mult override pipeline defaults;
# active_recipe_name=None preserves legacy behavior.
