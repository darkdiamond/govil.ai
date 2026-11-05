"""Shared helpers for recipe `compute.py` files.

The builder copies this package into every compute sandbox next to
`recipe_exec.py`, so a recipe imports it like any module:

    from govlib import cbs, fmt, frame, geo

Modules:
  fmt    Hebrew number, percent, date and list text
  frame  pandas idioms: stable ranked counts, top-N + "אחר", cleaning, parsing
  geo    map geometry: simplify, delta-encode rings, pack JSON islands
  cbs    CBS release tables (the cbs_releases grid): find headers by label,
         periods by content, parse CBS's missing-value marks

Self-contained on purpose (stdlib + pandas only, no `services.*` imports),
like recipe_exec.py.

Stability rule: every recipe on main renders through this code with no
`recipe_version` bump, so a published function's output must never change.
Fix a bug or change a default under a new name or a new keyword argument,
and move recipes onto it one at a time (with their own version bump).
The builder image ships this package and recipes are read from main at run
time, so a new helper must be deployed with the job before a recipe that
uses it merges.
"""

__version__ = "1"
