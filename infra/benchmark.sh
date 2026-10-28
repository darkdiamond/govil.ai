#!/usr/bin/env bash
# Run the model benchmark the way production runs a session.
#
#   infra/benchmark.sh --model tencent/hy3 --source <dataset_id>
#   infra/benchmark.sh --model x/y --batch <id1> <id2> --reasoning-effort max
#
# Everything after the script name goes to `cli/model_test`. The point is
# that the benchmark is not a lookalike: it builds the PRODUCTION image
# (./Dockerfile), runs it with the job's CPU/memory limits and the job's
# live env vars, and drives the same `agent_runner.run_validated_session`
# the daily job uses (LocalSandbox, SESSION_ATTEMPTS retries, backoff,
# all four validation gates). Only persistence differs: results land in
# tmp/model_test/<id>/ and nothing is written to GCS or Firestore.
#
# Credentials: the container never sees your Google credentials. Agent
# code can read any file in its container, so the Firestore reads happen
# here on the host (`--snapshot-out`) and the container gets a JSON file.
# The container does get OPENROUTER_API_KEY in the CLI process's env.
# Sandbox tool subprocesses get a scrubbed env, as in production, but they
# run as the same (container-root) uid, so /proc/<cli pid>/environ is
# readable to model-written code: treat the key as exposed to the agent,
# exactly as it is in the production job. Use a capped key. The output dir
# is bind-mounted read-write, so agent code can also touch earlier runs.
#
# Env source: the live job's non-secret env (gcloud run jobs describe), so
# the benchmark follows prod config changes without edits here. Set
# BENCH_ENV_FILE=<file> to use a fixed KEY=VALUE file (offline / pinned).
#
# Needs: podman; gcloud (logged in) or BENCH_ENV_FILE; the repo venv for
# the snapshot step (source .venv/bin/activate).

set -euo pipefail
cd "$(dirname "$0")/.."

PROJECT=${FIREBASE_PROJECT:-govdata-il}
REGION=${REGION:-me-west1}
JOB=${CLOUD_RUN_JOB:-govdata-builder-job}
IMAGE=${BENCH_IMAGE:-localhost/govdata-builder-bench:latest}
OUT_DIR=${BENCH_OUT:-$PWD/tmp/model_test}

for a in "$@"; do
  if [[ "$a" == "--auto-trio" ]]; then
    echo "--auto-trio reads frontend/public/datasets, which is not in the image; pass --source or --batch" >&2
    exit 2
  fi
  if [[ "$a" == "--out" || "$a" == --out=* ]]; then
    # The container is --rm and only /app/tmp/model_test is mounted, so an
    # --out path inside it would be discarded with the container.
    echo "--out would write inside the throwaway container; set BENCH_OUT=<dir> instead" >&2
    exit 2
  fi
done

if [[ -z "${OPENROUTER_API_KEY:-}" ]]; then
  KEY_FILE=${OPENROUTER_KEY_FILE:-$HOME/.config/openrouter/key}
  [[ -r "$KEY_FILE" ]] || { echo "set OPENROUTER_API_KEY or put the key in $KEY_FILE" >&2; exit 2; }
  OPENROUTER_API_KEY=$(tr -d '[:space:]' < "$KEY_FILE")
fi
export OPENROUTER_API_KEY

# mktemp -d never yields an empty path; the dir holds only this run's files.
WORK=$(mktemp -d)
chmod 700 "$WORK"
cleanup() { rm -f "$WORK/snapshot.json" "$WORK/job.env" "$WORK/limits" && rmdir "$WORK"; }
trap cleanup EXIT

echo "==> reading datasets from Firestore (host side)"
python -m services.page_builder.cli.model_test --snapshot-out "$WORK/snapshot.json" "$@"

ENV_FILE="$WORK/job.env"
# Fixed-env mode has no job to read limits from; these match
# infra/builder-job.deploy.sh (--cpu=2 --memory=4Gi).
CPUS=${BENCH_CPUS:-2}
MEMORY=${BENCH_MEMORY:-4Gi}
if [[ -n "${BENCH_ENV_FILE:-}" ]]; then
  cp "$BENCH_ENV_FILE" "$ENV_FILE"
else
  echo "==> reading live env + limits of $JOB"
  gcloud run jobs describe "$JOB" --region="$REGION" --project="$PROJECT" --format=json \
    | python3 -c '
import json, sys
c = json.load(sys.stdin)["spec"]["template"]["spec"]["template"]["spec"]["containers"][0]
with open(sys.argv[1], "w") as f:
    for e in c.get("env", []):
        if "value" in e:  # skip secret-backed entries
            f.write(e["name"] + "=" + e["value"] + "\n")
lim = (c.get("resources") or {}).get("limits") or {}
cpu = str(lim.get("cpu", "2"))
cpu = str(int(cpu[:-1]) / 1000) if cpu.endswith("m") else cpu
print(cpu, lim.get("memory", "4Gi"))
' "$ENV_FILE" > "$WORK/limits"
  read -r CPUS MEMORY < "$WORK/limits"
fi
echo "    $(wc -l < "$ENV_FILE") env vars (production config), ${CPUS} vCPU / ${MEMORY}"

echo "==> building production image"
podman build -q -t "$IMAGE" -f Dockerfile . >/dev/null

mkdir -p "$OUT_DIR"
echo "==> running benchmark in the image (${CPUS} vCPU / ${MEMORY}, like the job)"
# FIRESTORE_* and GCS_* in the job env are inert here: the CLI reads the
# snapshot and run_validated_session never touches GCS.
podman run --rm \
  --cpus="$CPUS" --memory="$MEMORY" \
  --env-file "$ENV_FILE" \
  -e OPENROUTER_API_KEY \
  -v "$WORK/snapshot.json:/snapshot.json:ro" \
  -v "$OUT_DIR:/app/tmp/model_test" \
  --entrypoint python \
  "$IMAGE" -m services.page_builder.cli.model_test --snapshot /snapshot.json "$@"
