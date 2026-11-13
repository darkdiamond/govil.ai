"""Which providers exist, and which are switched on for this run.

A provider is off unless `PROVIDER_<KEY>_ENABLED=true`. One instance per
provider per process (`enabled_providers()` is cached), so the sync step and
the refresh share its download cache.
"""
from __future__ import annotations

import logging
import os
from collections.abc import Mapping

from pydantic import ValidationError

from .base import ProviderSettings, SourceProvider
from .boi import BoiSdmxProvider
from .cbs import CbsReleasesProvider
from .cbs_index import CbsIndexProvider

PROVIDER_CLASSES: dict[str, type[SourceProvider]] = {
    BoiSdmxProvider.key: BoiSdmxProvider,
    CbsReleasesProvider.key: CbsReleasesProvider,
    CbsIndexProvider.key: CbsIndexProvider,
}

log = logging.getLogger("providers")

_enabled: dict[str, SourceProvider] | None = None
# Enabled providers `enabled_providers()` left out for invalid settings.
_invalid: set[str] = set()


def build_providers(environ: Mapping[str, str] = os.environ, *,
                    invalid: set[str] | None = None) -> dict[str, SourceProvider]:
    """The enabled providers. A provider's other settings are read only once
    its `ENABLED` var says it is on, and one whose settings don't validate is
    logged and left out (its key added to `invalid`), so a bad value can't
    cost the other providers."""
    out = {}
    for key, cls in PROVIDER_CLASSES.items():
        enabled_var = f"PROVIDER_{key.upper()}_ENABLED"
        try:
            on = ProviderSettings.from_env(
                key, cls.default_settings,
                {enabled_var: environ[enabled_var]} if enabled_var in environ else {},
            ).enabled
            if not on:
                continue
            out[key] = cls.from_env(environ)
        except ValidationError as e:
            log.error("provider %s left off: invalid PROVIDER_%s_* setting: %s",
                      key, key.upper(), e)
            if invalid is not None:
                invalid.add(key)
    return out


def enabled_providers() -> dict[str, SourceProvider]:
    global _enabled
    if _enabled is None:
        _invalid.clear()
        _enabled = build_providers(invalid=_invalid)
    return _enabled


def provider_invalid(key: str | None) -> bool:
    """Whether this run's providers left `key` out for invalid settings
    (enabled, but a `PROVIDER_<KEY>_*` value didn't validate)."""
    enabled_providers()
    return bool(key) and key in _invalid


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
