"""Non-CKAN data sources ("providers") for the recipe pipeline.

See `base.py` for the contract, `registry.py` for what's enabled, and
`sync.py` for the daily step that turns `recipes/<id>/source.json` into a
`sources/<id>` doc the recipe refresh can render.
"""
from .base import (
    SOURCE_CONFIG_FILENAME,
    ProviderError,
    ProviderFacts,
    ProviderResource,
    ProviderSettings,
    SourceConfig,
    SourcePresentation,
    SourceProvider,
)
from .registry import (
    PROVIDER_CLASSES,
    build_providers,
    enabled_providers,
    provider_for_id,
    provider_for_key,
    reset_providers,
)

__all__ = [
    "PROVIDER_CLASSES",
    "SOURCE_CONFIG_FILENAME",
    "ProviderError",
    "ProviderFacts",
    "ProviderResource",
    "ProviderSettings",
    "SourceConfig",
    "SourcePresentation",
    "SourceProvider",
    "build_providers",
    "enabled_providers",
    "provider_for_id",
    "provider_for_key",
    "reset_providers",
]
