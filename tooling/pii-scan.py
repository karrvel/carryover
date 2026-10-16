#!/usr/bin/env python3
# © 2026 karrvel — MIT License. See LICENSE.md.
"""pii-scan.py — mechanical PII / private-context guard for a repo that goes PUBLIC.

Codified, not inferred: a fixed list of regexes. Exits non-zero (blocks) on any match, so it can
gate a pre-push hook. Generic patterns only live here (safe to publish). User/project-specific
literals (other private project names, personal emails) live in a LOCAL denylist that is gitignored
and NEVER committed — pass it via --denylist or $PII_DENYLIST, or drop a `.pii-denylist.local` at the
repo root (one entry per line; `#` comments; a line is a regex if it starts with `re:` else literal).

Scans, in order of what leaks:
  files    tracked file contents           (default: `git ls-files`, under the current dir)
  commits  in a range (--range BASE..HEAD, or via the pre-push hook): messages, lines added
           anywhere in the range, and author/committer identities — `git log` publishes
           names and emails, the most common way a personal address reaches a public repo
  staged   staged diff added lines         (--staged)

Project-specific false positives go in a `.pii-allowlist.local` at the repo root (one safe substring
per line, `#` comments), so they survive kit updates instead of living in this file's ALLOW.

Usage:
  python3 tooling/pii-scan.py                      # scan all tracked files
  python3 tooling/pii-scan.py --staged             # scan staged additions (pre-commit)
  python3 tooling/pii-scan.py --range origin/main..HEAD   # scan commit messages too
  PII_DENYLIST=~/kb.pii python3 tooling/pii-scan.py --range ...
Exit 0 = clean, 1 = matches found, 2 = usage/error.
"""
import os, re, subprocess, sys

# ── Codified generic patterns (public-safe). (label, compiled regex). ────────────────────────────
PATTERNS = [
    ("claude-session-url",   re.compile(r"claude\.ai/code/session[_/][A-Za-z0-9._-]+")),
    ("claude-session-trailer", re.compile(r"(?im)^\s*Claude-Session\s*:")),
    # no trailing-slash requirement — `/Users/me` at end-of-line is just as much a leak as
    # `/Users/me/…`; the ALLOW list masks the documentation placeholders below.
    ("home-path-users",      re.compile(r"/Users/[A-Za-z0-9._-]+")),
    ("home-path-home",       re.compile(r"/home/[A-Za-z0-9._-]+")),
    ("private-key-block",    re.compile(r"-----BEGIN (?:[A-Z ]+ )?PRIVATE KEY-----")),
    ("aws-access-key",       re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("github-token",         re.compile(r"\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{20,}\b|\bgithub_pat_[A-Za-z0-9_]{20,}\b")),
    # OpenAI/Anthropic keys: sk-, optional family prefix (ant/proj/live/test), then ≥20 chars that
    # MAY contain '-'/'_' — so `sk-ant-api03-…` and `sk-proj-…` match (the old `[A-Za-z0-9]{20,}`
    # stopped at the first hyphen and missed every current-generation key).
    ("api-key-sk",           re.compile(r"\bsk-[A-Za-z0-9][A-Za-z0-9_-]{19,}")),
    ("slack-token",          re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b")),
    ("google-api-key",       re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b")),
    # secret-looking assignment. The key may end an UPPER_SNAKE name (`JWT_SECRET=`, `BOT_TOKEN=`) —
    # `\b` never fires after `_`, which hid every env-file secret. The value must be a quoted literal
    # (≥8), or an unquoted ≥12-char token containing a digit that isn't a call — so code like
    # `password: string`, `token = token.strip()`, `password = os.environ.get(...)` stays quiet.
    ("generic-secret-assign", re.compile(
        r"(?i)(?<![A-Za-z0-9])(?:api[_-]?key|secret|password|passwd|token)\b['\"]?\s*[:=]\s*"
        r"(?:['\"][^'\"\s]{8,}['\"]|(?![A-Za-z_][\w.]*\s*\()(?=[^\s'\"(),;]*\d)[^\s'\"(),;]{12,})")),
    ("email",                re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")),
]
# Known-safe substrings that suppress a match on the SAME line (avoid false positives). Extend freely.
ALLOW = [
    # generic no-reply / example addresses
    "noreply@anthropic.com", "noreply@github.com", "@users.noreply.github.com",
    "@example.com", "@example.org",
    "user@host", "you@example", "name@example", "<email>", "example@",
    # git SSH host (public, appears in clone commands)
    "git@github.com", "git@gitlab.com",
    # documentation placeholder home paths (slashless so they mask with or without a trailing '/';
    # real usernames stay blocked). `/Users/...` / `/home/...` are the ellipsis form used in docs.
    "/Users/me", "/Users/you", "/Users/name", "/Users/<", "/Users/...",
    "/home/me", "/home/you", "/home/...",
]
# Binary/vendored paths never worth scanning.
SKIP_PATH = re.compile(r"(?:^|/)(?:\.git/|__pycache__/|\.png$|\.jpg$|\.jpeg$|\.gif$|\.pdf$|\.ico$|\.woff2?$|\.lock$)")

def load_denylist():
    """Extra user/project literals or regexes from a LOCAL, gitignored source."""
    pats, path = [], (opt("--denylist") or os.environ.get("PII_DENYLIST"))
    if not path:
        default = os.path.join(repo_root(), ".pii-denylist.local")
        path = default if os.path.exists(default) else None
    if not path or not os.path.exists(os.path.expanduser(path)):
        return pats
    for raw in open(os.path.expanduser(path), errors="ignore"):
        s = raw.strip()
        if not s or s.startswith("#"):
            continue
        if s.startswith("re:"):
            pats.append(("denylist-regex", re.compile(s[3:], re.I)))
        else:
            pats.append(("denylist-literal", re.compile(re.escape(s), re.I)))
    return pats

def load_allow():
    """Project-specific safe substrings from a LOCAL `.pii-allowlist.local` at the repo root."""
    path = os.path.join(repo_root(), ".pii-allowlist.local")
    if not os.path.exists(path):
        return []
    return [ln.strip() for ln in open(path, errors="ignore")
            if ln.strip() and not ln.strip().startswith("#")]

def opt(flag):
    if flag in sys.argv:
        i = sys.argv.index(flag)
        return sys.argv[i + 1] if i + 1 < len(sys.argv) else ""
    return None

def repo_root():
    try:
        return subprocess.check_output(["git", "rev-parse", "--show-toplevel"], text=True).strip()
    except subprocess.CalledProcessError:
        return os.getcwd()

def git(*args):
    r = subprocess.run(["git", *args], capture_output=True, text=True)
    if r.returncode != 0:
        # FAIL CLOSED: a git error (e.g. an invalid range on a first/root-commit push) must never
        # be mistaken for "clean". Abort loudly so the guard blocks instead of passing empty output.
        sys.stderr.write(f"✗ pii-scan: `git {' '.join(args)}` failed (exit {r.returncode}): "
                         f"{r.stderr.strip()}\n")
        sys.exit(2)
    return r.stdout

def scan_text(text, patterns, where, hits):
    for n, ln in enumerate(text.splitlines(), 1):
        # mask known-safe substrings in place (preserve offsets) so OTHER patterns on the same
        # line still fire — do not skip the whole line.
        masked = ln
        for a in ALLOW:
            if a in masked:
                masked = masked.replace(a, " " * len(a))
        for label, rx in patterns:
            m = rx.search(masked)
            if m:
                snip = m.group(0).strip()
                if len(snip) > 60: snip = snip[:57] + "…"
                hits.append((where, n, label, snip))

def main():
    patterns = PATTERNS + load_denylist()
    ALLOW.extend(load_allow())
    root = repo_root()
    hits = []

    # 1. tracked files (default surface). --full-name: from a subdirectory (a vault nested in a
    #    bigger repo), plain `ls-files` prints cwd-relative paths, and joining those onto the repo
    #    root read the WRONG files — a clean report for files that were never looked at.
    n_files = 0
    for rel in git("ls-files", "--full-name").splitlines():
        if SKIP_PATH.search(rel):
            continue
        p = os.path.join(root, rel)
        try:
            with open(p, "rb") as fh:
                raw = fh.read()
            if b"\x00" in raw[:4096]:
                continue  # binary
            n_files += 1
            scan_text(raw.decode("utf-8", "ignore"), patterns, rel, hits)
        except OSError:
            continue

    # 2. a commit range (history is permanent once public): scan BOTH messages AND file content
    #    added anywhere in the range — a secret added in commit A and deleted in B still ships.
    rng = opt("--range")
    if rng:
        for sha in git("rev-list", rng).splitlines():
            body = git("show", "-s", "--format=%B", sha)
            scan_text(body, patterns, f"commit {sha[:9]} (message)", hits)
        diff = git("log", "-p", "--no-color", "--unified=0", "--format=%n", rng)
        added = "\n".join(l[1:] for l in diff.splitlines()
                          if l.startswith("+") and not l.startswith("+++"))
        scan_text(added, patterns, f"range {rng} (added lines in history)", hits)
        # author/committer identity — pushed with every commit and shown by any `git log`
        idents = git("log", "--format=%an <%ae>%n%cn <%ce>", rng)
        scan_text("\n".join(sorted(set(idents.splitlines()))), patterns,
                  f"range {rng} (author/committer identity)", hits)

    # 3. staged additions
    if "--staged" in sys.argv:
        diff = git("diff", "--cached", "--unified=0")
        added = "\n".join(l[1:] for l in diff.splitlines() if l.startswith("+") and not l.startswith("+++"))
        scan_text(added, patterns, "staged diff", hits)

    if hits:
        print(f"✗ pii-scan: {len(hits)} potential leak(s) — BLOCKED:\n")
        for where, n, label, snip in hits:
            print(f"    {where}:{n}  [{label}]  {snip}")
        print("\n  Scrub them, or if a hit is a false positive add the safe substring to a")
        print("  `.pii-allowlist.local` at the repo root. Bypass once (last resort): git push/commit --no-verify.")
        return 1
    if n_files == 0 and not rng and "--staged" not in sys.argv:
        # "no PII found" after looking at nothing is a false all-clear — e.g. a repo with no commits
        print("✗ pii-scan: 0 tracked files scanned — nothing is committed here yet, so there is "
              "nothing to vouch for.")
        return 1
    print(f"✓ pii-scan: no PII / private-context patterns found ({n_files} tracked file(s)"
          + (f", range {rng}" if rng else "") + ").")
    return 0

if __name__ == "__main__":
    sys.exit(main())
