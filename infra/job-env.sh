# Sourced by the *-job.deploy.sh scripts: read a live Cloud Run job's env, so a
# scripted redeploy (whose --set-env-vars replaces the whole set) can keep a
# runtime toggle an operator set with `gcloud run jobs update --update-env-vars`.
#
#   load_live_job_env JOB REGION PROJECT   # once; aborts if the job can't be read
#   live_job_env NAME                      # prints the live value ("" if unset)
#
# A job that doesn't exist yet (first deploy) reads as an empty env. Any other
# describe failure (auth, network) aborts the deploy: guessing would turn a
# thrown kill switch back on.

LIVE_JOB_JSON=""

load_live_job_env() {
  local job=$1 region=$2 project=$3 err
  err=$(mktemp)
  if LIVE_JOB_JSON=$(gcloud run jobs describe "$job" --region="$region" --project="$project" \
      --format=json 2>"$err"); then
    rm -f "$err"
    return 0
  fi
  if grep -qiE 'cannot find job|not found|NOT_FOUND' "$err"; then
    echo "==> job $job does not exist yet: no live env to keep"
    LIVE_JOB_JSON=""
    rm -f "$err"
    return 0
  fi
  cat "$err" >&2
  rm -f "$err"
  echo "ERROR: could not read the live job $job (see above); not deploying" >&2
  exit 1
}

live_job_env() {
  [ -n "$LIVE_JOB_JSON" ] || return 0
  printf '%s' "$LIVE_JOB_JSON" | python3 -c '
import json, sys
name = sys.argv[1]
spec = json.load(sys.stdin).get("spec", {}).get("template", {}).get("spec", {})
for c in spec.get("template", {}).get("spec", {}).get("containers", []):
    for e in c.get("env") or []:
        if e.get("name") == name and "value" in e:
            print(e["value"])
            sys.exit(0)
' "$1"
}

# keep_live_value NAME DEFAULT: the value to deploy for NAME. An exported
# value wins (even an empty one); else the live job's; else DEFAULT. Use as
# `X=$(keep_live_value X default)` under `set -e`: an unreadable live env then
# aborts the deploy.
keep_live_value() {
  local name=$1 default=$2 live
  if [ -n "${!name+x}" ]; then
    printf '%s' "${!name}"
    return 0
  fi
  live=$(live_job_env "$name") || {
    echo "ERROR: could not read $name from the live job's env; not deploying" >&2
    return 1
  }
  if [ -n "$live" ]; then
    echo "==> keeping the live job's $name=$live" >&2
    printf '%s' "$live"
  else
    printf '%s' "$default"
  fi
}

# join_env_pairs PAIR...: one --set-env-vars value, joined with gcloud's
# alternate delimiter (`^D^K=V<D>K=V`, see `gcloud topic escaping`). D is the
# first of ; | ~ @ ! that no pair holds: hour lists hold commas, and a
# User-Agent holds ';'.
join_env_pairs() {
  local d all="$*"
  for d in ';' '|' '~' '@' '!'; do
    if [[ $all != *"$d"* ]]; then
      (IFS=$d; printf '^%s^%s' "$d" "$*")
      return 0
    fi
  done
  echo "ERROR: every delimiter candidate appears in an env value" >&2
  return 1
}
