"""Which providers exist, and which are switched on for this run.

A provider is off unless `PROVIDER_<KEY>_ENABLED=true`. One instance per
provider per process (`enabled_providers()` is cached), so the sync step and
the refresh share its download cache.
"""
from __future__ import annotations

import os
from collections.abc import Mapping

from .base import SourceProvider
from .boi import BoiSdmxProvider
from .cbs import CbsReleasesProvider
from .cbs_index import CbsIndexProvider

PROVIDER_CLASSES: dict[str, type[SourceProvider]] = {
    BoiSdmxProvider.key: BoiSdmxProvider,
    CbsReleasesProvider.key: CbsReleasesProvider,
    CbsIndexProvider.key: CbsIndexProvider,
}

_enabled: dict[str, SourceProvider] | None = None


def build_providers(environ: Mapping[str, str] = os.environ) -> dict[str, SourceProvider]:
    out = {}
    for key, cls in PROVIDER_CLASSES.items():
        p = cls.from_env(environ)
        if p.settings.enabled:
            out[key] = p
    return out


def enabled_providers() -> dict[str, SourceProvider]:
    global _enabled
    if _enabled is None:
        _enabled = build_providers()
    return _enabled


def provider_for_key(key: str | None,
                     providers: Mapping[str, SourceProvider] | None = None
                     ) -> SourceProvider | None:
    if not key:
        return None
    return (enabled_providers() if providers is None else providers).get(key)


def provider_for_id(dataset_id: str) -> type[SourceProvider] | None:
    """The provider class whose id prefix claims `dataset_id` (enabled or not).
    The longest prefix wins: `cbs-index-` is inside `cbs-`."""
    hits = [c for c in PROVIDER_CLASSES.values() if dataset_id.startswith(c.id_prefix)]
    return max(hits, key=lambda c: len(c.id_prefix)) if hits else None
