"""Page builder: Managed Agents controller that produces a per-dataset HTML page."""
import os

# Sandbox tool calls fork() this process (subprocess with user=/group= can't
# vfork). With the Firestore gRPC client's threads alive, gRPC's atfork
# handlers intermittently kill the child (SIGABRT "Epoll1Poller ... Bad file
# descriptor"), failing recipe compute. Must be set before grpc is imported;
# the Dockerfile sets it too.
os.environ.setdefault("GRPC_ENABLE_FORK_SUPPORT", "0")

from .schema import Manifest, ManifestEntry

__all__ = ["Manifest", "ManifestEntry"]
