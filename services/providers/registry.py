"""Which providers exist, and which are switched on for this run.

A provider is off unless `PROVIDER_<KEY>_ENABLED=true`. One instance per
provider per process (`enabled_providers()` is cached), so the sync step and
the refresh share its download cache.
"""
from __future__ import annotations

import os
from typing import Mapping, Optional

from .base import SourceProvider
from .boi import BoiSdmxProvider

PROVIDER_CLASSES: dict[str, type[SourceProvider]] = {
    BoiSdmxProvider.key: BoiSdmxProvider,
}

_enabled: Optional[dict[str, SourceProvider]] = None


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


def reset_providers() -> None:
    """Forget the cached instances (tests; a long-lived process re-reading env)."""
    global _enabled
    _enabled = None


def provider_for_key(key: Optional[str],
                     providers: Optional[Mapping[str, SourceProvider]] = None
                     ) -> Optional[SourceProvider]:
    if not key:
        return None
    return (enabled_providers() if providers is None else providers).get(key)


def provider_for_id(dataset_id: str) -> Optional[type[SourceProvider]]:
    """The provider class whose id prefix claims `dataset_id` (enabled or not)."""
    for cls in PROVIDER_CLASSES.values():
        if dataset_id.startswith(cls.id_prefix):
            return cls
    return None
