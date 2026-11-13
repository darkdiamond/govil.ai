"""Every committed recipe directory holds only recipe files.

The repo is public: a stray CSV or exploration script in recipes/<id>/ would
publish raw dataset rows. author verify enforces the same rule while authoring.
"""

from __future__ import annotations

import shutil
from pathlib import Path

from services.page_builder import author
from services.page_builder.recipe import Recipe

RECIPES = Path(__file__).resolve().parents[3] / "recipes"


def test_committed_recipe_dirs_hold_only_recipe_files():
    dirs = sorted(d for d in RECIPES.iterdir() if d.is_dir())
    assert dirs, f"no recipes under {RECIPES}"
    stray = [f for d in dirs for f in author._stray_file_findings(Recipe.load(d))]
    assert not stray, "\n".join(stray)


def test_a_symlinked_directory_in_a_recipe_dir_is_stray(tmp_path):
    # is_dir() follows the link and rglob doesn't descend into it: the link
    # itself must still be flagged, or a PR could commit it.
    src = next(d for d in sorted(RECIPES.iterdir()) if d.is_dir() and not d.name.startswith("."))
    recipe_dir = tmp_path / src.name
    shutil.copytree(src, recipe_dir, ignore=shutil.ignore_patterns("__pycache__"))
    (tmp_path / "rows").mkdir()
    (tmp_path / "rows" / "raw.csv").write_text("a,b\n1,2\n", encoding="utf-8")
    (recipe_dir / "extract").symlink_to(tmp_path / "rows", target_is_directory=True)
    (recipe_dir / "sub").mkdir()  # a real directory is skipped (its files are checked)
    stray = author._stray_file_findings(Recipe.load(recipe_dir))
    assert stray == [(f"STRAY: recipes/{src.name}/extract is not a recipe file; move it to "
                     "tmp/authoring/ (raw rows must not be committed)")]
