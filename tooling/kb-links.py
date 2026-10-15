#!/usr/bin/env python3
# © 2026 karrvel — MIT License. See LICENSE.md.
"""kb-links.py — link-rot checker for the vault (the non-LLM doc-health signal the research flagged
as highest-ROI for a plain-markdown KB, yet with no off-the-shelf tool).

Three checks, all read-only, stdlib-only:
  (A) WIKILINKS  — every [[name]] / [[name|alias]] / [[name#anchor]] whose target shard doesn't
                   exist in the vault (the classic "forward-ref to a shard never written" rot).
  (B) FILE REFS  — markdown links [text](path.md) / (reference/foo.md) to a file that isn't there.
  (C) URLS       — (opt-in, --urls) http(s) links that 404 / fail a HEAD request. Needs network.

Exit 1 if any broken internal link (A or B) is found → wire into pre-commit / CI alongside kb-lint.

CONFIG:  KB_ROOT (default two dirs up) · KB_VAULT (default $KB_ROOT/_knowledge)
         KB_LINKS_IGNORE  regex; markdown-link targets matching it are not checked as local files
                          (e.g. tracker-relative links pasted from an issue tracker: `^/[A-Z]+/issues/`)
Usage:   python3 kb-links.py            # internal links only (fast, offline)
         python3 kb-links.py --urls     # also check external URLs (slow, network)
         python3 kb-links.py --urls --timeout 5
"""
import glob, os, re, sys, urllib.request

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
WIKI = re.compile(r"\[\[([^\]\n]+)\]\]")               # single-line only (no diagram spillover)
MDLINK = re.compile(r"(?<!\!)\[[^\]]*\]\(([^)]+)\)")   # [text](target), skip ![img](...)
URL = re.compile(r"https?://[^\s)\]<>\"']+")
FENCE = re.compile(r"```.*?```|~~~.*?~~~", re.S)        # fenced code blocks
INLINE = re.compile(r"`[^`\n]*`")                      # inline code spans
COMMENT = re.compile(r"<!--.*?-->", re.S)              # HTML comments (scaffold guidance, examples)
SKIP = {"_SHARD_TEMPLATE.md"}                           # scaffold w/ intentional placeholder links
# Without an escape hatch, one pasted tracker link (`(/PROJ/issues/PROJ-87)`) fails the hard gate
# forever, and the only way out was the advisory hook — which then checks nothing.
_ignore = os.environ.get("KB_LINKS_IGNORE")
IGNORE = re.compile(_ignore) if _ignore else None


def strip_code(txt):
    """Drop code blocks, inline code, and HTML comments — a [[link]] or (path) shown in an example
    or a scaffold comment is not a real link to resolve."""
    return INLINE.sub("", COMMENT.sub("", FENCE.sub("", txt)))


def vault_md():
    return [f for f in sorted(glob.glob(os.path.join(VAULT, "**", "*.md"), recursive=True))
            if os.path.basename(f) not in SKIP]


# Navigation files kb-sync.py *generates* (INDEX.md + one MOC per collection). They're valid
# [[wikilink]] targets even when absent — e.g. on a pristine template before the first sync, or in a
# live vault edited since the last sync. Keep in step with kb-sync's INDEX + COLLECTIONS.
GENERATED = {"INDEX", "gotchas", "decisions", "security", "tasks", "repos", "reference"}


def known_names():
    """Every shard name (basename w/o .md) + generated nav files — the [[wikilink]] namespace."""
    return {os.path.basename(f)[:-3] for f in vault_md()} | GENERATED


def target_of(wikitext):
    """Normalise a wikilink target to a bare shard name, the way Obsidian resolves it:
    [[name|alias]]→name, [[name#anchor]]→name, [[dir/name]]→name, [[name.md]]→name."""
    t = wikitext.split("|")[0].split("#")[0].strip().rstrip("\\").strip()
    t = os.path.basename(t)          # [[reference/foo]] → foo
    if t.endswith(".md"):            # [[repos.md]] → repos
        t = t[:-3]
    return t


def check_internal():
    names = known_names()
    broken_wiki, broken_file = [], []
    for f in vault_md():
        rel = os.path.relpath(f, ROOT)
        txt = strip_code(open(f, errors="ignore").read())
        for m in WIKI.finditer(txt):
            tgt = target_of(m.group(1))
            if tgt and tgt not in names:
                broken_wiki.append((rel, tgt))
        for m in MDLINK.finditer(txt):
            tgt = m.group(1).strip()
            if tgt.startswith(("http://", "https://", "#", "mailto:")) or (IGNORE and IGNORE.search(tgt)):
                continue
            path = tgt.split("#")[0]
            if not path:
                continue
            abspath = path if os.path.isabs(path) else os.path.normpath(os.path.join(os.path.dirname(f), path))
            if not os.path.exists(abspath):
                broken_file.append((rel, tgt))
    return broken_wiki, broken_file


def check_urls(timeout):
    seen, dead = {}, []
    for f in vault_md():
        rel = os.path.relpath(f, ROOT)
        for m in URL.finditer(strip_code(open(f, errors="ignore").read())):
            u = m.group(0).rstrip(".,;")
            if u in seen:
                if seen[u]:
                    dead.append((rel, u, seen[u]))
                continue
            status = None
            try:
                req = urllib.request.Request(u, method="HEAD", headers={"User-Agent": "kb-links/1.0"})
                urllib.request.urlopen(req, timeout=timeout)
                status = None                     # ok
            except urllib.error.HTTPError as e:
                status = None if e.code in (403, 405, 429) else f"HTTP {e.code}"  # some hosts block HEAD
            except Exception as e:
                status = str(e)[:50]
            seen[u] = status
            if status:
                dead.append((rel, u, status))
    return dead


def main():
    do_urls = "--urls" in sys.argv
    timeout = 8
    if "--timeout" in sys.argv:
        try:
            timeout = int(sys.argv[sys.argv.index("--timeout") + 1])
        except Exception:
            pass
    if not os.path.isdir(VAULT):
        print(f"kb-links: no vault at {VAULT}", file=sys.stderr)
        return 2

    bw, bf = check_internal()
    n_files = len(vault_md())
    print(f"kb-links: {n_files} files in {os.path.relpath(VAULT, ROOT)}\n")
    print(f"(A) WIKILINKS — [[target]] pointing at a shard that doesn't exist")
    if not bw:
        print("  ✓ all wikilinks resolve")
    for rel, tgt in bw:
        print(f"  ✗ {rel}  →  [[{tgt}]]")
    print(f"\n(B) FILE REFS — markdown links to a missing local file")
    if not bf:
        print("  ✓ all local file links resolve")
    for rel, tgt in bf:
        print(f"  ✗ {rel}  →  ({tgt})")

    dead = []
    if do_urls:
        print(f"\n(C) URLS — external links failing a HEAD request (timeout {timeout}s)")
        dead = check_urls(timeout)
        if not dead:
            print("  ✓ external URLs reachable")
        for rel, u, st in dead:
            print(f"  ✗ {rel}  →  {u}  [{st}]")

    total_internal = len(bw) + len(bf)
    print(f"\n{len(bw)} broken wikilink(s), {len(bf)} broken file ref(s)"
          + (f", {len(dead)} dead URL(s)" if do_urls else "")
          + (".  clean ✓" if total_internal == 0 and not dead else "."))
    return 1 if total_internal else 0        # internal rot fails the gate; URL failures are advisory


if __name__ == "__main__":
    sys.exit(main())
