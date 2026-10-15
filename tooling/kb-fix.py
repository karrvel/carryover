#!/usr/bin/env python3
# © 2026 karrvel — MIT License. See LICENSE.md.
"""kb-fix.py — make shard frontmatter Obsidian-safe (repair, not just report).

Obsidian's Properties parser is strict YAML. It throws "invalid frontmatter" and refuses to render
Properties when a value is an *unquoted* scalar that contains a `: ` (colon-space), a leading
reserved indicator (`@ ! & * ? | > % # , [ { ` `), a ` #` (inline-comment), or a tab. These creep
in constantly via `provenance:`/`title:` (e.g. `Path: /Users/...`, `title: Repo: orgn`, or the
`(or: code path)` in the shard template) — which is why the vault "errors when opened after an
update." This wraps exactly those values in double quotes (escaped), leaving everything else byte-
for-byte. Idempotent: a value already cleanly quoted or a well-formed `[flow, list]` is untouched.

Read-only unless it finds fixes; run it after kb-sync.py (or on save) to keep the vault openable.

CONFIG:  KB_ROOT (default two dirs up) · KB_VAULT (default $KB_ROOT/_knowledge)
Flags:   --dry-run  show what would change, write nothing
         --check    exit 1 if any file needs fixing, write nothing (for CI / pre-commit)

Usage:   python3 kb-fix.py            # repair in place
         python3 kb-fix.py --check    # gate: fail if the vault has Obsidian-breaking frontmatter
"""
import glob, os, re, sys

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
        if v[:1] in ("\"", "'"):                         # quoted: up to the matching quote, so a
            end = v.find(v[0], 1)                         # trailing `# comment` (or a # inside the
            v = v[1:end] if end > 0 else v[1:]            # quotes) is handled either way
        else:
            v = re.split(r"\s+#", v, maxsplit=1)[0].strip()   # unquoted: drop a trailing # comment
        os.environ.setdefault(m.group(1), v)

_load_kb_env(ROOT)

VAULT = os.environ.get("KB_VAULT") or os.path.join(ROOT, "_knowledge")
FM_LINE = re.compile(r"^(\w[\w-]*):[ \t]+(.*?)[ \t]*$")   # `key: value` (value non-empty)


def already_quoted(v):
    """True if v is already a well-formed YAML quoted scalar (so re-running is a no-op)."""
    if len(v) >= 2 and v[0] == '"' and v[-1] == '"':
        i = 1                                    # double-quoted: every internal " must be \-escaped
        while i < len(v) - 1:
            if v[i] == "\\":
                i += 2
                continue
            if v[i] == '"':
                return False                     # unescaped " before the end → not one clean scalar
            i += 1
        return True
    if len(v) >= 2 and v[0] == "'" and v[-1] == "'":
        return "'" not in v[1:-1].replace("''", "")   # single-quoted: internal ' doubled as ''
    return False


def needs_quote(v):
    """True if this plain scalar would make Obsidian's YAML parser error."""
    if not v:
        return False
    if already_quoted(v):                        # keeps kb-fix idempotent
        return False
    # well-formed flow collection (tags: [a, b]) → leave it
    if (v[0] == "[" and v[-1] == "]") or (v[0] == "{" and v[-1] == "}"):
        return False
    if ": " in v or v.endswith(":"):
        return True
    if " #" in v:
        return True
    if v[0] in "!&*?|>%@`,[]{}#\"'":         # leading reserved indicator
        return True
    if "\t" in v:
        return True
    return False


def quote(v):
    return '"' + v.replace("\\", "\\\\").replace('"', '\\"') + '"'


def fix_text(txt):
    """Return (new_text, list_of_(key,before,after)). Only touches the frontmatter block."""
    m = re.match(r"^(---\n)(.*?)(\n---\n)", txt, re.S)
    if not m:
        return txt, []
    head, block, tail = m.group(1), m.group(2), m.group(3)
    changes, out = [], []
    for ln in block.split("\n"):
        detabbed = ln.replace("\t", "  ") if "\t" in ln and not FM_LINE.match(ln) else ln
        mm = FM_LINE.match(ln)
        if mm:
            k, v = mm.group(1), mm.group(2)
            if needs_quote(v):
                nl = f"{k}: {quote(v)}"
                out.append(nl)
                changes.append((k, v, quote(v)))
                continue
        out.append(detabbed)
    if not changes:
        return txt, []
    return head + "\n".join(out) + tail + txt[m.end():], changes


def main():
    if not os.path.isdir(VAULT):
        print(f"kb-fix: no vault at {VAULT}", file=sys.stderr)
        return 2
    dry = "--dry-run" in sys.argv
    check = "--check" in sys.argv
    files = sorted(glob.glob(os.path.join(VAULT, "**", "*.md"), recursive=True))
    n_fixed = n_changes = 0
    for f in files:
        rel = os.path.relpath(f, ROOT)
        txt = open(f, errors="ignore").read()
        new, changes = fix_text(txt)
        if not changes:
            continue
        n_fixed += 1
        n_changes += len(changes)
        verb = "would fix" if (dry or check) else "fixed"
        print(f"  {verb}  {rel}  ({len(changes)} value(s))")
        for k, before, after in changes:
            print(f"        {k}: {before[:64]}  →  {after[:66]}")
        if not dry and not check:
            open(f, "w").write(new)
    tag = ("check" if check else "dry-run" if dry else "fix")
    print(f"\nkb-{tag}: {n_changes} Obsidian-breaking value(s) across {n_fixed} file(s)"
          + ("" if n_fixed else " — clean ✓"))
    return 1 if (check and n_fixed) else 0


if __name__ == "__main__":
    sys.exit(main())
