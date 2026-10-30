# Cloud Run job container for govdata-builder-job — the daily recipe refresh.
#
# One execution per scheduler tick: scan → refresh recipe'd pages (no LLM) →
# queue authoring issues → dispatch the publisher. Python-only — the
# Node/Firebase build runs in GitHub Actions (publish.yml).

FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONPATH=/app \
    GRPC_ENABLE_FORK_SUPPORT=0

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Unprivileged identity for recipe compute.py subprocesses
# (services/page_builder/local_sandbox.py). The builder process itself
# stays root — it must setuid into this user per command — so recipe code
# can't read the host process's /proc/<pid>/environ (GitHub token etc.)
# or rewrite anything under /app, incl. the host-side check.py gate.
RUN useradd --system --uid 10001 --home-dir /nonexistent --no-create-home \
        --shell /usr/sbin/nologin sandbox

WORKDIR /app

# Install deps first so the layer is cached across code changes.
COPY services/page_builder/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Copy only what the job needs.
COPY services/__init__.py ./services/__init__.py
COPY services/shared ./services/shared
COPY services/scanner ./services/scanner
COPY services/page_builder ./services/page_builder
COPY services/providers ./services/providers
# Host-side page gate (run on every rendered body before it is staged).
COPY agent/skills/check.py ./agent/skills/check.py
# Belt-and-braces: COPY keeps build-context modes, so make sure nothing
# under /app is group/world-writable for the sandbox user.
RUN chmod -R go-w /app

CMD ["python", "-m", "services.page_builder.pipeline", "--mode", "scheduled"]
