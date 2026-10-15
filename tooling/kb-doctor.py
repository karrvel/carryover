#!/usr/bin/env python3
# © 2026 karrvel — MIT License. See LICENSE.md.
"""kb-doctor.py — check that a vault is actually protected, not just well-formed. Read-only.

kb-lint, kb-links and kb-sync --check all judge the vault's *content*, and they all report green on
a vault that has never been committed, has no gate installed, or was just rolled back by an editor.
The gate itself only runs on `git commit`, so a vault that is never committed never meets it. This
script checks the operational layer around the content:

  git        is the root a git repo, does HEAD exist, is the vault tracked, how much vault work is
             uncommitted and how old it is, is there a remote at all
  gate       core.hooksPath set, .githooks/pre-commit present, _meta/ ignored, kb.env not swallowed
             by a `*.env` ignore rule
  wiring     CLAUDE.md LIVE markers, MEMORY.md at the dir Claude Code actually loads
  rollback   the working tree deleting far more vault text than it adds vs HEAD, or shards whose
             `updated:` went BACKWARDS — the signature of an editor/agent restoring an old snapshot.
             Running kb-sync on top of that bakes the rollback into MEMORY.md, which git can't undo.

CONFIG: KB_ROOT · KB_VAULT · KB_MEMORY_DIR · KB_PLATFORMS (same meaning and defaults as kb-sync.py;
also read from <root>/.githooks/kb.env — the environment wins).

Usage:  python3 kb-doctor.py            # full report
        python3 kb-doctor.py --brief    # only the problems (silent when healthy) — for session start
        python3 kb-doctor.py --fail     # exit 1 if any problem was found (for CI / scripts)
Exit: 0 (or 1 with --fail and a problem) · 2 usage error or no vault.
"""
import os, re, subprocess, sys, time

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
MEMORY_DIR = os.environ.get("KB_MEMORY_DIR") or os.path.expanduser(
    "~/.claude/projects/" + re.sub(r"[/.]", "-", ROOT) + "/memory")
PLATFORMS = {x.strip() for x in (os.environ.get("KB_PLATFORMS") or "claude,codex,gemini,cursor").split(",")
             if x.strip()}
ROLLBACK_MIN_DELETED = 200    # lines; below this a net deletion is ordinary editing
USAGE = "usage: kb-doctor.py [--brief] [--fail] [--help]"

problems, report = [], []


def git(*args):
    """(returncode, stdout) — never raises; a missing git binary reads as 'not a repo'."""
    try:
        r = subprocess.run(["git", "-C", ROOT, *args], capture_output=True, text=True)
        return r.returncode, r.stdout.strip()
    except OSError:
        return 127, ""


def ok(msg):
    report.append(f"  ✓ {msg}")


def info(msg):
    report.append(f"  ℹ {msg}")


def problem(msg, fix):
    problems.append(msg)
    report.append(f"  ⚠ {msg}\n      → {fix}")


def frontmatter_updated(text):
    m = re.search(r"^---\n.*?^updated:\s*([0-9]{4}-[0-9]{2}-[0-9]{2})", text or "", re.S | re.M)
    return m.group(1) if m else None


def check_git():
    """True when ROOT is inside a git work tree (so the gate checks make sense)."""
    rc, top = git("rev-parse", "--show-toplevel")
    if rc != 0:
        problem("not a git repository — the vault has no history, no backup and no gate",
                "git init, add a .gitignore (see setup/), then make a first commit")
        return False
    if os.path.realpath(top) != os.path.realpath(ROOT):
        info(f"vault root is nested inside the git repo at {top}")
    rc, _ = git("rev-parse", "-q", "--verify", "HEAD")
    if rc != 0:
        problem("the repo has no commits — nothing here is recorded anywhere, and the pre-commit gate "
                "has never run", "check .gitignore covers _meta/ and secrets, then: git add -A && git commit")
        return True                       # still a repo: the gate checks below apply
    vrel = os.path.relpath(VAULT, top)
    _, tracked = git("ls-files", "--full-name", "--", VAULT)
    if not tracked:
        problem(f"{vrel}/ is not tracked — the vault has never been committed",
                f"git add {vrel} && git commit")
        return True
    _, untracked = git("ls-files", "--others", "--exclude-standard", "--full-name", "--", VAULT)
    _, modified = git("diff", "--name-only", "HEAD", "--", VAULT)
    pending = [p for p in (untracked.splitlines() + modified.splitlines()) if p]
    if pending:
        ages = []
        for p in pending:
            try:
                ages.append(time.time() - os.path.getmtime(os.path.join(top, p)))
            except OSError:
                pass
        oldest = int(max(ages) // 86400) if ages else 0
        msg = (f"{len(pending)} vault file(s) uncommitted ({len(untracked.splitlines()) if untracked else 0} "
               f"new, {len(modified.splitlines()) if modified else 0} modified); oldest change {oldest} day(s) old")
        if oldest >= 3:
            problem(msg, "commit the vault at the end of each session")
        else:
            info(msg)
    else:
        ok("vault fully committed")
    _, remotes = git("remote")
    if not remotes:
        info("no git remote — unless this machine is backed up, this disk is the only copy")
    else:
        ok(f"remote: {', '.join(remotes.split())}")
    check_rollback(top, modified.splitlines() if modified else [])
    return True


def check_rollback(top, modified):
    _, numstat = git("diff", "--numstat", "HEAD", "--", VAULT)
    added = deleted = 0
    for ln in numstat.splitlines():
        a, d, _ = (ln.split("\t") + ["", ""])[:3]
        if a.isdigit() and d.isdigit():
            added, deleted = added + int(a), deleted + int(d)
    backwards = []
    for p in modified:
        if not p.endswith(".md"):
            continue
        _, head_txt = git("show", f"HEAD:{p}")
        try:
            cur_txt = open(os.path.join(top, p), errors="ignore").read()
        except OSError:
            continue
        h, c = frontmatter_updated(head_txt), frontmatter_updated(cur_txt)
        if h and c and c < h:
            backwards.append(p)
    if backwards or (deleted >= ROLLBACK_MIN_DELETED and deleted > 3 * max(added, 1)):
        detail = []
        if deleted >= ROLLBACK_MIN_DELETED:
            detail.append(f"the working tree deletes {deleted} vault line(s) vs HEAD and adds {added}")
        if backwards:
            detail.append(f"{len(backwards)} shard(s) have an OLDER `updated:` than at HEAD "
                          f"(e.g. {backwards[0]})")
        problem("possible rollback: " + "; ".join(detail),
                "if you didn't do this, an editor/agent may have restored an old snapshot — recover it "
                "(git diff HEAD, the tool's undo/snapshot store) BEFORE running kb-sync, which would bake "
                "it into MEMORY.md")


def check_gate():
    rc, hooks_path = git("config", "--get", "core.hooksPath")
    hook = os.path.join(ROOT, ".githooks", "pre-commit")
    if rc != 0 or not hooks_path:
        problem("the pre-commit gate is not wired (core.hooksPath is unset)",
                "git config core.hooksPath .githooks   (per clone)")
    elif not os.path.isfile(os.path.join(ROOT, hooks_path, "pre-commit")):
        problem(f"core.hooksPath points at {hooks_path}/ but there is no pre-commit hook in it — the "
                "gate is silently off", "copy the kit's tooling/hooks/pre-commit into .githooks/")
    else:
        ok(f"gate wired ({hooks_path}/pre-commit)")
    if os.path.isfile(hook) and not os.access(hook, os.X_OK):
        problem(".githooks/pre-commit is not executable — git skips it", "chmod +x .githooks/pre-commit")
    meta = os.path.join(ROOT, "_meta")
    if os.path.isdir(meta):
        rc_ign, _ = git("check-ignore", "-q", "_meta/kb-sync.py")
        _, meta_tracked = git("ls-files", "--", "_meta")
        if meta_tracked:
            info("_meta/ is tracked in git — fine if intentional; kb-update then needs a commit after each update")
        elif rc_ign != 0:
            problem("_meta/ is neither ignored nor tracked — one `git add -A` away from committing it",
                    "add `_meta/` to .gitignore (see setup/)")
    env = os.path.join(ROOT, ".githooks", "kb.env")
    if os.path.isfile(env):
        rc_env, _ = git("check-ignore", "-q", ".githooks/kb.env")
        _, env_tracked = git("ls-files", "--", ".githooks/kb.env")
        if rc_env == 0 and not env_tracked:
            problem(".githooks/kb.env is gitignored (a `*.env` rule?) — your KB settings are never versioned",
                    "add `!.githooks/kb.env` to .gitignore")


def check_wiring():
    if "claude" not in PLATFORMS:
        return
    cm = os.path.join(ROOT, "CLAUDE.md")
    if not os.path.isfile(cm):
        problem("no CLAUDE.md at the root — the LIVE blocks have nowhere to go",
                "create it with the two <!-- BEGIN/END:sync:… --> marker pairs (README quick start)")
    elif "BEGIN:sync:live-security" not in open(cm, errors="ignore").read():
        problem("CLAUDE.md has no LIVE sync markers", "add the two marker pairs (README quick start)")
    else:
        ok("CLAUDE.md LIVE markers present")
    mem = os.path.join(MEMORY_DIR, "MEMORY.md")
    if not os.path.isfile(mem):
        problem(f"no MEMORY.md where Claude Code loads it ({MEMORY_DIR.replace(os.path.expanduser('~'), '~')}) — "
                "if the project moved, the old memory dir is orphaned", "run kb-sync.py from this root")
    else:
        ok("MEMORY.md present at the derived memory dir")


def main():
    args = sys.argv[1:]
    if "--help" in args or "-h" in args:
        print(USAGE)
        return 0
    unknown = [a for a in args if a not in ("--brief", "--fail")]
    if unknown:
        print(f"kb-doctor: unrecognised argument(s): {' '.join(unknown)}\n{USAGE}", file=sys.stderr)
        return 2
    if not os.path.isdir(VAULT):
        print(f"kb-doctor: no vault at {VAULT}", file=sys.stderr)
        return 2
    brief = "--brief" in args
    if check_git():
        check_gate()
    check_wiring()
    if brief:
        if problems:
            print(f"=== kb-doctor: {len(problems)} problem(s) ===")
            print("\n".join(line for line in report if line.lstrip().startswith("⚠") or "→" in line))
    else:
        print(f"kb-doctor: {os.path.relpath(VAULT, ROOT)} at {ROOT.replace(os.path.expanduser('~'), '~')}")
        print("\n".join(report))
        print(f"\n{len(problems)} problem(s)." + ("  healthy ✓" if not problems else ""))
    return 1 if (problems and "--fail" in args) else 0


if __name__ == "__main__":
    sys.exit(main())
