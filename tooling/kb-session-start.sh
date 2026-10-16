#!/bin/sh
# kb-session-start.sh — print vault problems (via kb-doctor.py, if present), then gotcha titles,
# for quick orientation at session start.
# Usage: sh _meta/kb-session-start.sh   (or add to AGENTS.md as "First action")
# Reads _knowledge/gotchas/*.md and prints name + title of each, plus any active tasks.
# No dependencies beyond sh and grep.

ROOT="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
VAULT="${KB_VAULT:-$ROOT/_knowledge}"
HERE="$(cd "$(dirname "$0")" && pwd)"

# Protection problems first (never committed, gate unwired, possible rollback …) — kb-doctor is
# silent when the vault is healthy, so this costs nothing on a good day.
PY="$(command -v python3 || command -v python)"
if [ -n "$PY" ] && [ -f "$HERE/kb-doctor.py" ] && [ -d "$VAULT" ]; then
    KB_ROOT="${KB_ROOT:-$ROOT}" KB_VAULT="$VAULT" "$PY" "$HERE/kb-doctor.py" --brief && echo ""
fi

if [ ! -d "$VAULT/gotchas" ]; then
    echo "No gotchas vault found at $VAULT/gotchas — run kb-sync.py first."
    exit 0
fi

_active_count=0
for f in "$VAULT/gotchas/"*.md; do
    [ -f "$f" ] || continue
    _s="$(grep '^status:' "$f" | head -1 | sed 's/status: *//')"
    { [ "$_s" = "superseded" ] || [ "$_s" = "resolved" ]; } && continue
    _active_count=$((_active_count + 1))
done
echo "=== Active gotchas ($_active_count shards) ==="
for f in "$VAULT/gotchas/"*.md; do
    [ -f "$f" ] || continue
    name="$(grep '^name:' "$f" | head -1 | sed 's/name: *//')"
    title="$(grep '^title:' "$f" | head -1 | sed 's/title: *//' | tr -d '"')"
    status="$(grep '^status:' "$f" | head -1 | sed 's/status: *//')"
    { [ "$status" = "superseded" ] || [ "$status" = "resolved" ]; } && continue
    printf "  [[%s]] — %s\n" "$name" "$title"
done

echo ""
echo "=== Active tasks ==="
for f in "$VAULT/tasks/"*.md; do
    [ -f "$f" ] || continue
    status="$(grep '^status:' "$f" | head -1 | sed 's/status: *//')"
    [ "$status" = "active" ] || continue
    name="$(grep '^name:' "$f" | head -1 | sed 's/name: *//')"
    title="$(grep '^title:' "$f" | head -1 | sed 's/title: *//' | tr -d '"')"
    printf "  [[%s]] — %s\n" "$name" "$title"
done
