#!/usr/bin/env bash
# Cap how many Firebase Hosting versions the site keeps (site config `maxVersions`).
#
# Every publish is a Hosting deploy, and with hourly builder ticks that is ~15
# versions a day (265 in 2026-11 up to the 26th). Unset, Hosting keeps every
# version forever (514 by 2026-11-26) and storage past the free 10 GB is billed.
# Older versions are deleted by Hosting itself; the live release is never
# touched. MAX_VERSIONS=100 is about a week of deploys: that is the rollback
# window (`firebase hosting:rollback`, or the console's release history).
#
# The version history used to double as the list of every URL the site ever
# served (the 2026-11-01 404 audit). Before the first cap it was exported to
# gs://govdata-il-staging/hosting-history/paths-2026-11-26.tsv.gz
# (path, first_seen, last_seen); a version deleted by the cap is gone from the
# API, so export again before lowering the cap.
#
#   ./infra/hosting-retention.setup.sh          # apply (MAX_VERSIONS, default 100)
#   ./infra/hosting-retention.setup.sh --show   # print the current config
#
# A cap below MIN_SAFE (50) is refused unless FORCE=1: Hosting deletes the
# versions past it at once, and they can't be restored.
set -euo pipefail

PROJECT=${PROJECT:-govdata-il}
SITE=${SITE:-govdata-il}
MAX_VERSIONS=${MAX_VERSIONS:-100}
MIN_SAFE=50
URL="https://firebasehosting.googleapis.com/v1beta1/sites/$SITE/config"
TOKEN="$(gcloud auth print-access-token)"
auth=(-H "Authorization: Bearer $TOKEN" -H "x-goog-user-project: $PROJECT")

case "${1:-}" in
  --show) curl -sS --fail-with-body "${auth[@]}" "$URL"; echo; exit 0 ;;
  "") ;;
  *) echo "usage: $0 [--show]" >&2; exit 2 ;;
esac

if ! [[ "$MAX_VERSIONS" =~ ^[1-9][0-9]*$ ]]; then
  echo "MAX_VERSIONS must be a positive integer, got '$MAX_VERSIONS'" >&2; exit 2
fi
if (( MAX_VERSIONS < MIN_SAFE )) && [[ "${FORCE:-}" != 1 ]]; then
  echo "refusing MAX_VERSIONS=$MAX_VERSIONS (< $MIN_SAFE): older versions are deleted for good." >&2
  echo "Export the URL history first, then re-run with FORCE=1." >&2
  exit 2
fi

echo "==> $SITE: maxVersions=$MAX_VERSIONS"
curl -sS --fail-with-body -X PATCH "${auth[@]}" -H "Content-Type: application/json" \
  "$URL?updateMask=maxVersions" -d "{\"maxVersions\": \"$MAX_VERSIONS\"}"
echo
