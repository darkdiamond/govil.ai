"""Every committed recipe directory holds only recipe files.

The repo is public: a stray CSV or exploration script in recipes/<id>/ would
publish raw dataset rows. author verify enforces the same rule while authoring.
"""

from __future__ import annotations

from pathlib import Path

from services.page_builder import author
from services.page_builder.recipe import Recipe

RECIPES = Path(__file__).resolve().parents[3] / "recipes"


def test_committed_recipe_dirs_hold_only_recipe_files():
    dirs = sorted(d for d in RECIPES.iterdir() if d.is_dir())
    assert dirs, f"no recipes under {RECIPES}"
    stray = [f for d in dirs for f in author._stray_file_findings(Recipe.load(d))]
    assert not stray, "\n".join(stray)
