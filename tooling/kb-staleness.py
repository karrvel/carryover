#!/usr/bin/env python3
# © 2026 karrvel — MIT License. See LICENSE.md.
"""kb-staleness.py — surface the volatile shards that are overdue for re-verification.

The one discipline every vault skips: `decays-with-code` shards are accurate only as of their
`updated:` date and must be re-checked against the code before an agent trusts them — but nobody
re-checks them. This tool makes the backlog visible (and hook-able) instead of silent. Read-only.

Two checks:
  (A) AGE      — every volatile shard (volatility contains "decays") whose `updated:` is older than
                 KB_STALE_DAYS is flagged, newest-overdue last. This is the re-verify queue.
  (B) ANCHORS  — backtick-quoted source paths (`pkg/foo.ts`, `src/x.py:42`) that no longer exist
                 under $KB_ROOT/repos/ — a strong signal the shard describes code that moved.

Portable stdlib-only. A project with a GitHub-PR convention can layer a `gh pr view`
drift check on top; that part is project-specific and lives in the project's own _meta/.

CONFIG (env, all optional):
  KB_ROOT       project root (default: two dirs up from this file)
  KB_VAULT      vault dir                    (default: $KB_ROOT/_knowledge)
  KB_REPOS      code checkout dir for anchors (default: $KB_ROOT/repos)
  KB_STALE_DAYS age threshold in days         (default: 14)
  KB_TODAY      YYYY-MM-DD override for age math (default: real today)

Flags:
  --age-only        skip the anchor check
  --fail-on-stale   exit 1 if anything is overdue (for pre-session / CI gating)

Usage:  python3 kb-staleness.py
        KB_STALE_DAYS=7 python3 kb-staleness.py --fail-on-stale
"""
import datetime, glob, os, re, sys

ROOT = os.environ.get("KB_ROOT") or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# Read <root>/.githooks/kb.env, so a manual run sees the same KB_* settings the pre-commit hook does.
# Parsed, never executed: `KEY=value` / `export KEY="value"` lines with KB_* keys only. A variable
# already set in the environment wins. KB_ROOT can't come from this file — it is what locates it.
def _load_kb_env(root):
    try:
        lines = open(os.path.join(root, ".githooks", "kb.env"), errors="ignore").read().splitlines()
    except OSError:
        return
    for ln in lines:
        m = re.match(r"^\s*(?:export\s+)?(KB_[A-Z0-9_]+)=(.*)$", ln)
        if not m or m.group(1) == "KB_ROOT":
            continue
        v = m.group(2).strip()
        if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
            v = v[1:-1]
        else:
            v = re.split(r"\s+#", v, maxsplit=1)[0].strip()   # unquoted: drop a trailing # comment
        os.environ.setdefault(m.group(1), v)

_load_kb_env(ROOT)

VAULT = os.environ.get("KB_VAULT") or os.path.join(ROOT, "_knowledge")
REPOS = os.environ.get("KB_REPOS") or os.path.join(ROOT, "repos")
STALE_DAYS = int(os.environ.get("KB_STALE_DAYS", "14"))
COLLECTIONS = ["gotchas", "decisions", "security", "tasks", "repos"]
# backtick-quoted source paths worth anchor-checking (≥1 dir segment + a code-ish extension)
ANCHOR_RE = re.compile(r"`([A-Za-z0-9_./\-]+\.(?:ts|tsx|js|jsx|rs|py|go|sh|toml|yaml|yml|sql|rb|"
                       r"java|kt|swift|c|h|cpp|json))(?::\d+)?`")
DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def today():
    o = os.environ.get("KB_TODAY", "")
    if DATE.match(o or ""):
        return datetime.date(*(int(x) for x in o.split("-")))
    return datetime.date.today()


def parse(path):
    txt = open(path, errors="ignore").read()
    fm, body = {}, txt
    m = re.match(r"^---\n(.*?)\n---\n?(.*)$", txt, re.S)
    if m:
        body = m.group(2)
        for ln in m.group(1).splitlines():
            mm = re.match(r"^(\w+):\s*(.*)$", ln)
            if mm:
                fm[mm.group(1)] = mm.group(2).strip()
    return fm, body


def as_date(s):
    return datetime.date(*(int(x) for x in s.split("-"))) if DATE.match(s or "") else None


def repo_file_index():
    """basename -> list of repo-relative paths, one pass over $KB_REPOS (skip .git/node_modules)."""
    idx = {}
    if not os.path.isdir(REPOS):
        return idx
    for dp, dns, fns in os.walk(REPOS):
        dns[:] = [d for d in dns if d not in (".git", "node_modules", "dist", "build", "target")]
        for fn in fns:
            idx.setdefault(fn, []).append(os.path.join(dp, fn))
    return idx


def main():
    if not os.path.isdir(VAULT):
        print(f"kb-staleness: no vault at {VAULT}", file=sys.stderr)
        return 2
    now = today()
    age_only = "--age-only" in sys.argv

    files = []
    for c in COLLECTIONS:
        files += sorted(glob.glob(os.path.join(VAULT, c, "*.md")))
    arch = os.path.join(VAULT, "architecture.md")
    if os.path.exists(arch):
        files.append(arch)

    overdue = []          # (age_days, rel, updated, title)
    undated_volatile = [] # rel  (volatile but no valid updated: — can't age it, still a smell)
    n_volatile = 0
    anchor_texts = {}     # rel -> body (only for volatile shards, for the anchor pass)

    for f in files:
        rel = os.path.relpath(f, ROOT)
        fm, body = parse(f)
        vol = fm.get("volatility", "")
        if "decays" not in vol:      # durable / one-shot / missing → not on the re-verify clock
            continue
        n_volatile += 1
        anchor_texts[rel] = body
        d = as_date(fm.get("updated", ""))
        if d is None:
            undated_volatile.append(rel)
            continue
        age = (now - d).days
        if age > STALE_DAYS:
            overdue.append((age, rel, fm.get("updated", ""),
                            (fm.get("title") or fm.get("name") or "").strip().strip('"')))

    overdue.sort(reverse=True)   # oldest first

    print(f"kb-staleness: {n_volatile} volatile (decays-*) shards; "
          f"threshold {STALE_DAYS}d; today {now.isoformat()}")
    print("\n(A) RE-VERIFY QUEUE — volatile shards past the age threshold")
    if not overdue and not undated_volatile:
        print("  ✓ none overdue")
    for age, rel, upd, title in overdue:
        print(f"  ⚠️  {age:>4}d  {rel}  (updated {upd})")
        if title:
            print(f"            {title}")
    for rel in undated_volatile:
        print(f"  ?      —  {rel}  (volatile but no valid `updated:` — can't age it)")

    n_missing_anchors = 0
    if not age_only:
        print("\n(B) ANCHOR CHECK — source paths cited in volatile shards that no longer exist")
        idx = repo_file_index()
        if not idx:
            print(f"  (no code checkout at {os.path.relpath(REPOS, ROOT)} — skipping)")
        else:
            hits = []
            for rel, body in anchor_texts.items():
                for m in ANCHOR_RE.finditer(body):
                    path = m.group(1)
                    base = os.path.basename(path)
                    cands = idx.get(base, [])
                    # exists if some indexed file ends with the cited path (suffix match)
                    if not any(c.replace(os.sep, "/").endswith(path) for c in cands):
                        hits.append((rel, path))
            # de-dup (shard, path)
            seen, uniq = set(), []
            for h in hits:
                if h not in seen:
                    seen.add(h)
                    uniq.append(h)
            n_missing_anchors = len(uniq)
            if not uniq:
                print("  ✓ every cited source path still exists")
            for rel, path in uniq:
                print(f"  ⚠️  {rel}  →  `{path}` not found under repos/")

    print(f"\n{len(overdue)} overdue, {len(undated_volatile)} undated-volatile, "
          f"{n_missing_anchors} missing anchor(s).")
    if "--fail-on-stale" in sys.argv and (overdue or undated_volatile or n_missing_anchors):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
