"""Page builder: the daily job (scan → recipe refresh → authoring queue →
publish dispatch), local authoring tools, and the publisher."""
from .schema import Manifest, ManifestEntry

__all__ = ["Manifest", "ManifestEntry"]
