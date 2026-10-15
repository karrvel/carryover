#!/usr/bin/env python3
# © 2026 karrvel — MIT License. See LICENSE.md.
"""kb-update.py — pull the latest carryover scripts into this project's tooling directory.

Copy this script (with the other tooling/*.py files) into your project's _meta/ dir at init time.
Run it from there whenever you want to pull in new kit versions.

Usage:
  python3 _meta/kb-update.py            # interactive — shows diffs, prompts before each file
  python3 _meta/kb-update.py --yes      # silent — overwrites without prompting (read the warning)
  python3 _meta/kb-update.py --check    # dry-run — show what would change, exit 1 if updates exist
                                        #   (--dry-run / -n are aliases; --check never writes)
  python3 _meta/kb-update.py --main     # track the default branch tip instead of a release
  python3 _meta/kb-update.py --ref v0.5 # pin to an explicit tag, branch or sha

Which ref gets pulled: by default the NEWEST RELEASE TAG on the remote (tags shaped like v1.2.3
or 1.2, compared numerically — v0.10 is newer than v0.9; rc/beta/other tags are ignored). If the
remote has no such tags, kb-update falls back to the default branch and says so. --main and --ref
override the default; they cannot be combined.

Exit codes:
  0  nothing to do, or scripts applied      2  usage error, git ls-remote or git clone failed
  1  updates exist (--check) / aborted      3  interactive run with no terminal on stdin

What gets updated: the *.py and *.sh scripts in the same directory as this file (your _meta/ or
tooling/ copy), plus the project's .githooks/pre-commit when one exists next to that directory (the
hard or advisory variant, whichever you installed). Each is shown as a diff and offered like any
other file. The template/ scaffold (your _knowledge/ contents) is NEVER touched — it's init-only and
belongs to your project, not the kit.

Downgrades are refused: if the target's version is older than the installed kb-sync.py's, kb-update
stops (exit 2) unless you named the ref yourself with --ref.
"""
import difflib, os, re, shutil, subprocess, sys, tempfile, textwrap, time

REPO_URL  = "https://github.com/karrvel/carryover.git"
REPO_TOOL = "tooling"          # subdirectory inside the kit that holds the scripts
VERSION_FILE = "kb.version"    # written next to this script after a successful update

# ── helpers ──────────────────────────────────────────────────────────────────

def _current_version(script_dir: str) -> str:
    """The installed version: kb-sync.py's own VERSION, else the kb.version pin, else "unknown".

    kb-sync.py is what actually runs, so it is the truth. The pin is only a fallback: a pin file
    goes stale whenever scripts are copied by hand rather than through kb-update, and reading it
    first made kb-update report (and compare against) a version that wasn't installed.
    """
    ks = os.path.join(script_dir, "kb-sync.py")
    if os.path.exists(ks):
        m = re.search(r'^VERSION\s*=\s*["\']([^"\']+)', open(ks).read(), re.M)
        if m:
            return m.group(1)
    vf = os.path.join(script_dir, VERSION_FILE)
    if os.path.exists(vf):
        return open(vf).read().strip() or "unknown"
    return "unknown"

def _remote_version(kit_tool_dir: str) -> str:
    ks = os.path.join(kit_tool_dir, "kb-sync.py")
    if os.path.exists(ks):
        m = re.search(r'^VERSION\s*=\s*["\']([^"\']+)', open(ks).read(), re.M)
        if m:
            return m.group(1)
    return "unknown"

# ── release-tag resolution ───────────────────────────────────────────────────

VERSION_TAG_RE = re.compile(r"^v?(\d+(?:\.\d+)*)$")

def _version_key(tag: str):
    """(1, 2, 3) for 'v1.2.3' / '1.2.3'; None for anything that isn't a plain version tag."""
    m = VERSION_TAG_RE.match(tag)
    if not m:
        return None
    return tuple(int(part) for part in m.group(1).split("."))

def _newest_release_tag(tags: list) -> str:
    """Newest version-shaped tag, compared as a numeric tuple — v0.10 beats v0.9. "" if none."""
    versioned = [(k, t) for t in tags if (k := _version_key(t)) is not None]
    if not versioned:
        return ""
    return max(versioned)[1]

def _remote_tags(repo_url: str) -> tuple:
    """(tags, "") on success; (None, stderr) if git ls-remote failed — never a silent fallback."""
    result = subprocess.run(
        ["git", "ls-remote", "--tags", "--refs", repo_url],
        capture_output=True, text=True
    )
    if result.returncode != 0:
        return None, (result.stderr.strip() or f"git ls-remote exited {result.returncode}")
    tags = []
    for line in result.stdout.splitlines():
        _, _, ref = line.partition("\t")
        if ref.startswith("refs/tags/"):
            tags.append(ref[len("refs/tags/"):].strip())
    return tags, ""

def _clone_kit(repo_url: str, clone_ref: str, dest: str) -> tuple:
    """Shallow-clone the kit at `clone_ref` ("" = default branch tip) into `dest`.

    `--branch` covers tags and branches; a raw sha needs a full clone + checkout, so that is
    tried second. Git's benign "not a commit" note for annotated tags lands in the captured
    stderr and is only ever shown when the clone actually failed.
    """
    cmd = ["git", "clone", "--depth", "1", "--quiet"]
    if clone_ref:
        cmd += ["--branch", clone_ref]
    result = subprocess.run(cmd + [repo_url, dest], capture_output=True, text=True)
    if result.returncode == 0:
        return True, ""
    if not clone_ref:
        return False, result.stderr.strip()

    # second chance: --ref may be a sha, which --branch cannot take
    shutil.rmtree(dest, ignore_errors=True)
    os.makedirs(dest, exist_ok=True)
    full = subprocess.run(["git", "clone", "--quiet", repo_url, dest], capture_output=True, text=True)
    if full.returncode != 0:
        return False, full.stderr.strip()
    out = subprocess.run(["git", "-C", dest, "checkout", "--quiet", clone_ref],
                         capture_output=True, text=True)
    if out.returncode != 0:
        return False, (result.stderr.strip() + "\n" + out.stderr.strip()).strip()
    return True, ""

def _unified_diff(path_a: str, path_b: str, label: str) -> list[str]:
    a = open(path_a).readlines() if os.path.exists(path_a) else []
    b = open(path_b).readlines() if os.path.exists(path_b) else []
    return list(difflib.unified_diff(a, b, fromfile=f"{label} (current)", tofile=f"{label} (new)", n=3))

def _colour(text: str, code: str) -> str:
    if not sys.stdout.isatty():
        return text
    return f"\033[{code}m{text}\033[0m"

def _print_diff(lines: list[str]) -> None:
    for line in lines:
        if line.startswith("+") and not line.startswith("+++"):
            print(_colour(line, "32"), end="")
        elif line.startswith("-") and not line.startswith("---"):
            print(_colour(line, "31"), end="")
        elif line.startswith("@@"):
            print(_colour(line, "36"), end="")
        else:
            print(line, end="")

# ── silent-mode warning ───────────────────────────────────────────────────────

SILENT_WARNING = """\
╔══════════════════════════════════════════════════════════════════════════════╗
║  ⚠  SILENT MODE (--yes)                                                     ║
║                                                                              ║
║  Scripts in this directory will be OVERWRITTEN without review.               ║
║                                                                              ║
║  Before continuing, make sure you understand:                               ║
║  • Any local modifications to these scripts will be lost.                   ║
║  • New scripts may change how your vault scans for secrets or paths.        ║
║  • The PII denylist (.pii-denylist.local) is NOT touched, but script        ║
║    logic that calls it may change — review the diff manually first.         ║
║                                                                              ║
║  Run WITHOUT --yes to review diffs interactively before applying.           ║
║                                                                              ║
║  Proceeding in 8 seconds … Ctrl+C to abort.                                 ║
╚══════════════════════════════════════════════════════════════════════════════╝"""

# ── argument handling ─────────────────────────────────────────────────────────

KNOWN_FLAGS = {"--yes", "-y", "--check", "--dry-run", "-n", "--main", "--ref", "--help", "-h"}
USAGE = ("usage: kb-update.py [--yes|-y] [--check|--dry-run|-n] [--main | --ref <REF>] [--help|-h]\n"
         "  default   update to the newest release tag on the remote\n"
         "  --main    track the default branch tip instead\n"
         "  --ref R   pin to an explicit tag, branch or sha")
NO_TTY = ("Error: interactive mode needs a terminal, but stdin is not a tty.\n"
          "  Re-run with --yes to apply silently, or --check for a read-only dry-run.")

def _split_ref_arg(args: list) -> tuple:
    """Pull the value out of `--ref <REF>` so it never reaches the unknown-flag check.

    Returns (flags, ref, error). `--ref` itself stays in flags so KNOWN_FLAGS still governs it.
    """
    flags, ref, i = [], "", 0
    while i < len(args):
        arg = args[i]
        flags.append(arg)
        if arg == "--ref":
            value = args[i + 1] if i + 1 < len(args) else ""
            if not value or value.startswith("-"):
                return flags, "", "--ref needs a value (a tag, branch or sha)"
            ref = value
            i += 2
            continue
        i += 1
    return flags, ref, ""

# ── main ─────────────────────────────────────────────────────────────────────

def main() -> int:
    args = sys.argv[1:]
    if "--help" in args or "-h" in args:
        print(USAGE)
        return 0
    flags, ref, ref_err = _split_ref_arg(args)
    unknown = [a for a in flags if a not in KNOWN_FLAGS]
    if unknown:
        print(_colour(f"Error: unrecognised argument(s): {' '.join(unknown)}", "31"))
        print(USAGE)
        return 2
    if ref_err:
        print(_colour(f"Error: {ref_err}", "31"))
        print(USAGE)
        return 2
    silent  = "--yes" in flags or "-y" in flags
    dry_run = "--check" in flags or "--dry-run" in flags or "-n" in flags
    use_main = "--main" in flags
    if use_main and ref:
        print(_colour("Error: --main and --ref are mutually exclusive — pick one ref.", "31"))
        print(USAGE)
        return 2

    # interactive mode needs a real terminal — refuse before cloning or touching anything
    if not silent and not dry_run and not sys.stdin.isatty():
        print(_colour(NO_TTY, "31"))
        return 3

    script_dir = os.path.dirname(os.path.abspath(__file__))
    current_ver = _current_version(script_dir)

    print(f"kb-update  |  current version: {_colour(current_ver, '33')}")
    print(f"           |  directory: {script_dir}")

    # which ref do we pull? default = newest release tag, so nobody gets mid-development code
    fallback_note = ""
    if ref:
        clone_ref, target_label = ref, f"{ref} (--ref)"
    elif use_main:
        clone_ref, target_label = "", "default branch (--main)"
    else:
        tags, err = _remote_tags(REPO_URL)
        if tags is None:
            print()
            print(_colour(f"Error: git ls-remote failed:\n{err}", "31"))
            return 2
        newest = _newest_release_tag(tags)
        if newest:
            clone_ref, target_label = newest, f"{newest} (newest release)"
        else:
            clone_ref, target_label = "", "default branch (no release tags found)"
            fallback_note = ("Note: the remote publishes no release tags — falling back to the "
                             "default branch.")
    print(f"           |  target: {_colour(target_label, '36')}")
    if fallback_note:
        print(_colour(fallback_note, "33"))
    print()

    if silent and not dry_run:
        print(_colour(SILENT_WARNING, "33"))
        print()
        try:
            for i in range(8, 0, -1):
                print(f"\r  {i}s …", end="", flush=True)
                time.sleep(1)
            print("\r         ")
        except KeyboardInterrupt:
            print("\nAborted.")
            return 1

    # clone the kit into a temp dir
    tmp = tempfile.mkdtemp(prefix="kb-update-")
    try:
        print(f"Fetching kit @ {clone_ref or 'default branch'} …")
        ok, err = _clone_kit(REPO_URL, clone_ref, tmp)
        if not ok:
            print(_colour(f"Error: could not fetch the kit:\n{err}", "31"))
            if clone_ref:
                print(f"  (ref requested: {clone_ref} — check that it exists on the remote)")
            return 2

        kit_tool_dir = os.path.join(tmp, REPO_TOOL)
        if not os.path.isdir(kit_tool_dir):
            # any ref is reachable via --ref, including ones predating the current layout
            print(_colour(f"Error: the kit at {clone_ref or 'the default branch'} has no "
                          f"{REPO_TOOL}/ directory — nothing to update from.", "31"))
            return 2
        remote_ver   = _remote_version(kit_tool_dir)
        print(f"           |  remote version:  {_colour(remote_ver, '32')}")
        print()

        # downgrade guard: a release older than what's installed would silently undo fixes.
        # Only an explicit --ref may go backwards — that is a deliberate pin, not a default.
        cur_key, rem_key = _version_key(current_ver), _version_key(remote_ver)
        if cur_key and rem_key and rem_key < cur_key and not ref:
            print(_colour(f"Error: {target_label} is version {remote_ver}, older than the installed "
                          f"{current_ver} — refusing to downgrade.", "31"))
            print("  Nothing was changed. Installed from the development branch? Use --main.")
            print("  To go back on purpose, name the ref: --ref <tag-or-branch>.")
            return 2
        if cur_key and cur_key == rem_key and not (ref or use_main):
            print(_colour(f"Note: installed and target are both {current_ver}, but the scripts may "
                          "differ — an install from --main can be ahead of the release. Read the diffs "
                          "before applying.", "33"))
            print()

        # collect *.py and *.sh files present in the kit's tooling/
        kit_scripts = sorted(
            f for f in os.listdir(kit_tool_dir)
            if f.endswith((".py", ".sh")) and os.path.isfile(os.path.join(kit_tool_dir, f))
        )

        changed, new_files = [], []
        for name in kit_scripts:
            local = os.path.join(script_dir, name)
            remote = os.path.join(kit_tool_dir, name)
            diff = _unified_diff(local, remote, name)
            if diff:
                (new_files if not os.path.exists(local) else changed).append((name, local, remote, diff))

        # The project's pre-commit hook lives at <root>/.githooks/, outside this dir, and used to be
        # left at whatever version was first copied — so hook fixes never reached anyone. Offer it
        # when it exists (never install one that isn't there), matched to the variant in use.
        hook = os.path.join(os.path.dirname(script_dir), ".githooks", "pre-commit")
        if os.path.isfile(hook):
            variant = "pre-commit-advisory" if "(ADVISORY)" in open(hook, errors="ignore").read(400) \
                else "pre-commit"
            remote = os.path.join(kit_tool_dir, "hooks", variant)
            if os.path.isfile(remote):
                diff = _unified_diff(hook, remote, ".githooks/pre-commit")
                if diff:
                    changed.append((".githooks/pre-commit", hook, remote, diff))

        if not changed and not new_files:
            print(_colour("✓ Already up to date.", "32"))
            if not dry_run:                       # --check is strictly read-only
                _write_version(script_dir, remote_ver)
            return 0

        total = len(changed) + len(new_files)
        print(f"  {total} script(s) would change "
              f"({len(changed)} updated, {len(new_files)} new):\n")
        for name, *_ in changed + new_files:
            tag = _colour("NEW", "32") if (name, *_) in new_files else _colour("UPD", "33")
            print(f"  [{tag}]  {name}")
        print()

        if dry_run:
            # show full diffs then exit
            for name, local, remote, diff in changed + new_files:
                print(_colour(f"── {name} " + "─" * (60 - len(name)), "36"))
                _print_diff(diff)
                print()
            return 1  # exit 1 = updates exist (useful in CI)

        # interactive or silent apply
        applied = 0
        accept_all = silent

        for name, local, remote, diff in changed + new_files:
            print(_colour(f"── {name} " + "─" * (60 - len(name)), "36"))
            _print_diff(diff)
            print()

            if accept_all:
                shutil.copy2(remote, local)
                print(_colour(f"  ✓ applied {name}", "32"))
                applied += 1
                continue

            while True:
                try:
                    choice = input("  Apply? [y]es / [n]o / [a]ll / [q]uit  > ").strip().lower()
                except EOFError:
                    print()
                    print(_colour(NO_TTY, "31"))
                    return 3          # stop here — pin stays at the previous version
                except KeyboardInterrupt:
                    # Ctrl+C at the prompt is a normal way to bail out of a tool that
                    # overwrites executable scripts — report state, never a traceback.
                    print()
                    print(_colour(f"Interrupted. Applied {applied}/{total} script(s); "
                                  f"version pin left at {current_ver}.", "33"))
                    return 1
                if choice in ("y", "yes"):
                    shutil.copy2(remote, local)
                    print(_colour(f"  ✓ applied", "32"))
                    applied += 1
                    break
                elif choice in ("n", "no"):
                    print("  skipped.")
                    break
                elif choice in ("a", "all"):
                    shutil.copy2(remote, local)
                    print(_colour(f"  ✓ applied (switching to apply-all)", "32"))
                    applied += 1
                    accept_all = True
                    break
                elif choice in ("q", "quit"):
                    print("Quit — no further files applied.")
                    if applied == total and not dry_run:
                        _write_version(script_dir, remote_ver)
                    else:
                        print(f"  Applied {applied}/{total} — version pin left at {current_ver}.")
                    return 0

            print()

        if applied == total:
            if not dry_run:
                _write_version(script_dir, remote_ver)
            print(_colour(f"Done. Applied {applied}/{total} script(s). "
                          f"Version: {current_ver} → {remote_ver}", "32"))
        elif applied:
            # partial apply — the pin would lie about what's on disk, so leave it alone
            print(_colour(f"Done. Applied {applied}/{total} script(s); "
                          f"{total - applied} skipped.", "33"))
            print(f"  Version pin left at {current_ver} (re-run to finish updating).")
        else:
            print("No scripts applied.")

    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    return 0

def _write_version(script_dir: str, version: str) -> None:
    with open(os.path.join(script_dir, VERSION_FILE), "w") as f:
        f.write(version + "\n")

if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:          # Ctrl+C outside the prompt (e.g. during the clone)
        print("\nInterrupted.")
        sys.exit(1)
