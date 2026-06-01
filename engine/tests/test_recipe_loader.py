"""Tests for engine.services.recipe_loader."""
from pathlib import Path

import pytest

from services.recipe_loader import Recipe, RecipeLoader, RecipeParameters, RecipeValidationError


def test_load_valid_recipe_from_yaml(tmp_path):
    """Test loading a valid recipe from YAML."""
    recipe_dir = tmp_path / "recipes"
    recipe_dir.mkdir()

    recipe_file = recipe_dir / "mcl_crude_long_hp.yaml"
    recipe_file.write_text("""name: mcl_crude_long_hp
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
""")

    loader = RecipeLoader(recipe_dir)
    recipe = loader.load("mcl_crude_long_hp")

    assert recipe.name == "mcl_crude_long_hp"
    assert recipe.version == 1
    assert recipe.parameters.entry_max_vix == 28
    assert recipe.parameters.min_confluence == 0.65
    assert recipe.parameters.size_mult == 1.2
    assert recipe.required_tools == ["market_data", "ib_paper_trader", "hidden_pivots"]
    assert recipe.steps == ["collect_data", "validate_hp_bias", "confluence_check", "size_and_enter"]


def test_list_available_returns_recipe_names(tmp_path):
    """Test that list_available returns sorted recipe names."""
    recipe_dir = tmp_path / "recipes"
    recipe_dir.mkdir()

    (recipe_dir / "bravo.yaml").write_text("name: bravo\nversion: 1")
    (recipe_dir / "alpha.yaml").write_text("name: alpha\nversion: 1")

    loader = RecipeLoader(recipe_dir)
    available = loader.list_available()

    assert available == ["alpha", "bravo"]


def test_list_available_empty_dir(tmp_path):
    """Test that list_available returns empty list for empty directory."""
    recipe_dir = tmp_path / "recipes"
    recipe_dir.mkdir()

    loader = RecipeLoader(recipe_dir)
    available = loader.list_available()

    assert available == []


def test_validate_entry_max_vix_out_of_range_low(tmp_path):
    """Test validation fails for entry_max_vix below 10."""
    recipe_dir = tmp_path / "recipes"
    recipe_dir.mkdir()

    recipe_file = recipe_dir / "invalid.yaml"
    recipe_file.write_text("""name: invalid
version: 1
parameters:
  entry_max_vix: 5
""")

    loader = RecipeLoader(recipe_dir)
    with pytest.raises(RecipeValidationError, match="entry_max_vix must be in \\[10, 80\\]"):
        loader.load("invalid")


def test_validate_size_mult_too_large(tmp_path):
    """Test validation fails for size_mult above 1.5 and message contains JARVIS sizing bounds."""
    recipe_dir = tmp_path / "recipes"
    recipe_dir.mkdir()

    recipe_file = recipe_dir / "invalid.yaml"
    recipe_file.write_text("""name: invalid
version: 1
parameters:
  size_mult: 2.0
""")

    loader = RecipeLoader(recipe_dir)
    with pytest.raises(RecipeValidationError, match="JARVIS sizing bounds"):
        loader.load("invalid")


def test_validate_missing_name(tmp_path):
    """Test validation fails for missing or empty name."""
    recipe_dir = tmp_path / "recipes"
    recipe_dir.mkdir()

    recipe_file = recipe_dir / "invalid.yaml"
    recipe_file.write_text("""name: ""
version: 1
""")

    loader = RecipeLoader(recipe_dir)
    with pytest.raises(RecipeValidationError, match="name must be non-empty string"):
        loader.load("invalid")


def test_validate_version_zero(tmp_path):
    """Test validation fails for version 0."""
    recipe_dir = tmp_path / "recipes"
    recipe_dir.mkdir()

    recipe_file = recipe_dir / "invalid.yaml"
    recipe_file.write_text("""name: invalid
version: 0
""")

    loader = RecipeLoader(recipe_dir)
    with pytest.raises(RecipeValidationError, match="version must be >= 1"):
        loader.load("invalid")


def test_load_real_example_recipe():
    """Test loading the real MCL crude long hidden pivots recipe."""
    recipes_dir = Path(__file__).parent.parent / "recipes"
    loader = RecipeLoader(recipes_dir)
    recipe = loader.load("mcl_crude_long_hp")

    assert recipe.name == "mcl_crude_long_hp"
    assert recipe.version == 1
    assert recipe.parameters.entry_max_vix == 28
    assert recipe.parameters.min_confluence == 0.65
    assert recipe.parameters.size_mult == 1.2
