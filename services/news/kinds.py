"""What kind of article a brief becomes. Stored on the article doc as `kind`
(a missing field means `news`: every article before kinds existed)."""
from __future__ import annotations

from enum import StrEnum


class ArticleKind(StrEnum):
    NEWS = "news"          # a fresh period that moved (signals → editor)
    FEATURE = "feature"    # an explainer on a high-demand dataset (the daily floor's fill)
    DIGEST = "digest"      # the weekly roundup of small moves
