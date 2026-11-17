#!/usr/bin/env bash
# Hourly gate for the authoring routine (scheduled task "govil.ai recipe
# authoring"): fire it only when there is work, so an idle hour costs no model
# tokens. The checks are a few free GitHub API calls; only a fire starts a
# model, and the fire itself is one short Haiku `claude -p` call (~$0.005)
# that calls RemoteTrigger (the CLI has no trigger command, and this way the
# OAuth token never leaves Claude Code).
#
# Runs from a systemd user timer on the owner's machine, as a local copy that
# `gate.sh install` puts in ~/.local/libexec (never main's latest piped to bash:
# update it by re-running install after reviewing the change). By hand:
#   bash gate.sh            # check, fire if due
#   DRY_RUN=1 bash gate.sh  # check, print the decision, fire nothing
#   bash gate.sh install    # write + enable the systemd user timer
#
# Fires when, after dropping issues an open same-repo PR already closes:
#   - an open `[author] … (<id>)` issue by darkdiamond is not `authoring-blocked`, or
#   - it is the daily hour (AUTHORING_GATE_DAILY_HOUR, 6) and any such issue is
#     open, blocked ones included, so the skill's recovery and upstream-unblock
#     checks run once a day;
# and not when a batch is still running in its worktree (the skill's own step 0
# check), nor when the same issue set was fired less than
# AUTHORING_GATE_REFIRE_HOURS (4) ago (a run that left them untouched).
set -euo pipefail

REPO=darkdiamond/govil.ai
TRIGGER=trig_01J1zwYMCbCtSXY8yFGeJ23e
WT=/home/zilbert/workdir/govdata-authoring
STATE=${XDG_STATE_HOME:-$HOME/.local/state}/govil-authoring-gate
REFIRE_H=${AUTHORING_GATE_REFIRE_HOURS:-4}
DAILY_HOUR=${AUTHORING_GATE_DAILY_HOUR:-6}
export PATH="$HOME/.local/bin:/usr/local/bin:/usr/bin:/bin"

mkdir -p "$STATE"
log() { echo "$(date -Is) $*" | tee -a "$STATE/log"; }

if [ "${1:-}" = install ]; then
  UNITS=${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user
  BIN=$HOME/.local/libexec/govil-authoring-gate.sh
  mkdir -p "$UNITS" "$(dirname "$BIN")"
  install -m 0755 "$0" "$BIN"
  cat >"$UNITS/govil-authoring-gate.service" <<EOF
[Unit]
Description=govil.ai authoring gate (fires the authoring routine when issues wait)

[Service]
Type=oneshot
ExecStart=/bin/bash $BIN
EOF
  cat >"$UNITS/govil-authoring-gate.timer" <<'EOF'
[Unit]
Description=govil.ai authoring gate, hourly 06:37-21:37 Israel time

[Timer]
OnCalendar=*-*-* 06..21:37:00 Asia/Jerusalem
Persistent=false

[Install]
WantedBy=timers.target
EOF
  systemctl --user daemon-reload
  systemctl --user enable --now govil-authoring-gate.timer
  systemctl --user list-timers govil-authoring-gate.timer --no-pager
  exit 0
fi

if find "$WT" -mmin -180 -print -quit 2>/dev/null | grep -q .; then
  log "skip: batch still running in $WT"
  exit 0
fi

# number<TAB>blocked for each open pipeline issue (same filters as the skill's step 1).
issues=$(gh issue list --repo "$REPO" --author darkdiamond --state open \
  --search 'in:title "[author]"' --limit 1000 --json number,title,labels \
  --jq '.[] | select(.title | test("^\\[author\\] .*\\(([0-9a-f]{8}|(boi|cbs)-[a-z0-9-]{1,60})\\)$"))
        | "\(.number)\t\([.labels[].name] | index("authoring-blocked") != null)"')
in_pr=$(gh pr list --repo "$REPO" --state open --limit 100 \
  --json number,body,isCrossRepository \
  --jq '[.[] | select(.isCrossRepository == false) | .body // "" | scan("(?i)\\b(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?):?\\s+#([0-9]+)") | .[0]] | unique | .[]')

open_all=() ready=()
while IFS=$'\t' read -r n blocked; do
  [ -n "$n" ] || continue
  grep -qx "$n" <<<"$in_pr" && continue
  open_all+=("$n")
  [ "$blocked" = false ] && ready+=("$n")
done <<<"$issues"

hour=$(TZ=Asia/Jerusalem date +%-H)
today=$(TZ=Asia/Jerusalem date +%F)
reason=""
if [ ${#ready[@]} -gt 0 ]; then
  reason="ready: ${ready[*]}"
elif [ "$hour" -eq "$DAILY_HOUR" ] && [ ${#open_all[@]} -gt 0 ] \
     && [ "$(cat "$STATE/daily" 2>/dev/null)" != "$today" ]; then
  reason="daily recheck: ${open_all[*]}"
fi
if [ -z "$reason" ]; then
  log "skip: nothing to do (${#open_all[@]} open, all blocked or in a PR)"
  exit 0
fi

key=$(printf '%s\n' "${ready[@]:-}" | sort -n | tr '\n' ' ')
if [ ${#ready[@]} -gt 0 ] && [ -f "$STATE/last_key" ] && [ "$(cat "$STATE/last_key")" = "$key" ] \
   && [ $(( $(date +%s) - $(stat -c %Y "$STATE/last_key") )) -lt $(( REFIRE_H * 3600 )) ]; then
  log "skip: same issues fired under ${REFIRE_H}h ago ($key)"
  exit 0
fi

if [ -n "${DRY_RUN:-}" ]; then
  log "dry run: would fire ($reason)"
  exit 0
fi

out=$(cd "$STATE" && timeout 180 claude -p --model haiku --strict-mcp-config \
  --allowedTools RemoteTrigger --output-format json \
  "Call the RemoteTrigger tool once with action \"run\" and trigger_id \"$TRIGGER\" and no body. Do nothing else. If the call succeeded, reply with exactly FIRED. Otherwise reply FAILED: followed by the error." \
  | python3 -c 'import json,sys; print(json.load(sys.stdin).get("result","").strip())') || out="FAILED: claude -p exited non-zero"

if [ "$out" = FIRED ]; then
  log "fired ($reason)"
  [ ${#ready[@]} -gt 0 ] && printf '%s' "$key" >"$STATE/last_key"
  [ "$hour" -eq "$DAILY_HOUR" ] && echo "$today" >"$STATE/daily"
  exit 0
fi
log "fire failed ($reason): $out"
exit 1
