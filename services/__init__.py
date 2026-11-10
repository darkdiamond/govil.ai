"""GovData services."""
import os

# Recipe compute fork()s the builder (subprocess with user=/group= can't
# vfork). With the Firestore gRPC client's threads alive, gRPC's atfork
# handlers intermittently kill the child (SIGABRT "Epoll1Poller ... Bad file
# descriptor"), failing recipe compute. Must be set before grpc is imported,
# so it lives at the root of every `services.*` import; the Dockerfile sets
# it too.
os.environ.setdefault("GRPC_ENABLE_FORK_SUPPORT", "0")
