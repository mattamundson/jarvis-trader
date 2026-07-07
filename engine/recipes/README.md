# Trading Playbook Recipes

YAML-based recipe definitions for JARVIS TRADER trading strategies. Each recipe specifies entry conditions, confluence thresholds, and position sizing overrides.

## Schema

### Top-level fields

- **name** (string, required): Recipe identifier. Must be non-empty.
- **version** (integer, required): Schema version. Must be >= 1.
- **parameters** (object, optional): Parameter overrides.
- **required_tools** (list[string], optional): List of tools required to execute the recipe.
- **steps** (list[string], optional): Ordered execution steps.

### Parameters

| Field | Type | Range | Default | Description |
|-------|------|-------|---------|-------------|
| `entry_max_vix` | float | [10, 80] | 28.0 | Maximum VIX ceiling for entry signals. |
| `min_confluence` | float | [0, 1] | 0.65 | Minimum confluence score (0–1) to trigger a trade. |
| `size_mult` | float | [0.5, 1.5] | 1.0 | Position sizing multiplier (JARVIS bounds: 0.5x–1.5x base). |

## Example: MCL Crude Oil Long (Hidden Pivots)

```yaml
name: mcl_crude_long_hp
version: 1
parameters:
  entry_max_vix: 28
  min_confluence: 0.65
  size_mult: 1.2
required_tools:
  - market_data
  - ib_paper_trader
  - hidden_pivots
steps:
  - collect_data
  - validate_hp_bias
  - confluence_check
  - size_and_enter
```

This recipe:
- Enters crude oil longs only when VIX ≤ 28
- Requires ≥65% confluence from technical signals
- Sizes positions at 120% of base (subject to max contract limits)
- Uses hidden pivots as primary bias validation

## Usage

```python
from engine.services.recipe_loader import RecipeLoader
from pathlib import Path

loader = RecipeLoader(Path(__file__).parent / "recipes")
recipe = loader.load("mcl_crude_long_hp")
print(f"Recipe: {recipe.name}, size_mult={recipe.parameters.size_mult}")
```

## Validation

Recipes are validated on load. Invalid fields raise `RecipeValidationError`:
- Missing or empty `name`
- `version` < 1
- `entry_max_vix` outside [10, 80]
- `min_confluence` outside [0, 1]
- `size_mult` outside [0.5, 1.5]
- Non-list `required_tools` or non-string elements
