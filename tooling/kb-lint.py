#!/usr/bin/env python3
# © 2026 karrvel — MIT License. See LICENSE.md.
"""kb-lint.py — enforce the shard frontmatter schema so a vault can't drift into dialects.

Companion to kb-sync.py. Where kb-sync *reads* frontmatter to generate navigation, kb-lint
*validates* it: required fields present, enum values canonical (no `decays-with-prs` vs
`decays-with-code`, no off-schema `done`/`complete` status), dates well-formed, names unique +
kebab-case, and no unfilled template placeholders left behind. Idempotent, read-only, stdlib-only.

Exit code 0 = clean, 1 = at least one ERROR (wire it into a pre-commit / CI hook to hold the line).

CONFIG (env vars, all optional — same derivation as kb-sync.py):
  KB_ROOT        project root (default: two dirs up from this file)
  KB_VAULT       the vault dir                          (default: $KB_ROOT/_knowledge)
  KB_VOLATILITY  allowed volatility values (comma list) (default: durable,decays-with-code,one-shot)
  KB_STATUS      allowed status values                  (default: active,superseded,resolved)
  KB_TYPES       allowed type values                    (default below)
  KB_MAX_LINES   warn when a shard exceeds this many lines (default: 120; 0 disables)
  KB_STRICT      "1" → treat WARN as ERROR (fail the build on warnings too)

Usage:  python3 kb-lint.py            # from anywhere; lints $KB_VAULT
        KB_STRICT=1 python3 kb-lint.py
        KB_VOLATILITY=durable,decays-with-code,decays-with-prs,one-shot python3 kb-lint.py
"""
import glob, os, re, sys
from collections import defaultdict

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
VOLATILITY = set((os.environ.get("KB_VOLATILITY") or "durable,decays-with-code,one-shot").split(","))
STATUS = set((os.environ.get("KB_STATUS") or "active,superseded,resolved").split(","))
TYPES = set((os.environ.get("KB_TYPES") or
             "gotcha,decision,security,task,repo,architecture,reference").split(","))
MAX_LINES = int(os.environ.get("KB_MAX_LINES", "120"))
STRICT = os.environ.get("KB_STRICT") == "1"

# The atomic-shard collections. reference/ (raw backbone) + generated files are linted leniently.
COLLECTIONS = ["gotchas", "decisions", "security", "tasks", "repos"]
REQUIRED = ["name", "type", "title", "status", "updated", "volatility", "provenance"]
RECOMMENDED = ["area", "tags"]
OPTIONAL = ["verify", "live_summary"]   # verify: date of last human re-verification; live_summary: short phrase for LIVE blocks
# Leftovers from _SHARD_TEMPLATE.md / template/README.md that mean "nobody filled this in".
PLACEHOLDERS = ["{PROJECT}", "example-slug-kebab-case", "Copy this file, rename",
                "One-line, specific, human-readable title", "2–5 tight sentences"]
# Generated/structural files at the vault root — never shards.
ROOT_FILES = {"INDEX.md", "README.md", "log.md", "architecture.md", "_SHARD_TEMPLATE.md"} | \
             {c + ".md" for c in COLLECTIONS}
LOG_HEADING = re.compile(r"^## \[\d{4}-\d{2}-\d{2}\] [^|]+\|")
# A vault README never filled in from template/ …
README_SMELLS = ["{PROJECT}", "Copy this `template/` tree"]
# … or copied from the kit's own dogfood vault, whose H1 names the kit instead of this project.
README_H1 = re.compile(r"^# _knowledge — the (\S+) local knowledge base", re.M)
KIT_NAMES = {"kb-template", "agent-kb", "carryover"}
CLOSED_WORDS = re.compile(r"^\W*(resolved|superseded|fixed|done|closed)\b", re.I)
KEBAB = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _already_quoted(v):
    """True if v is a well-formed YAML quoted scalar. Mirrors kb-fix.already_quoted."""
    if len(v) >= 2 and v[0] == '"' and v[-1] == '"':
        i = 1
        while i < len(v) - 1:
            if v[i] == "\\":
                i += 2
                continue
            if v[i] == '"':
                return False
            i += 1
        return True
    if len(v) >= 2 and v[0] == "'" and v[-1] == "'":
        return "'" not in v[1:-1].replace("''", "")
    return False


def yaml_unsafe(v):
    """True if this scalar would make Obsidian's YAML parser error. Mirrors kb-fix.py."""
    if not v or _already_quoted(v):
        return False
    if (v[0] == "[" and v[-1] == "]") or (v[0] == "{" and v[-1] == "}"):
        return False
    return (": " in v or v.endswith(":") or " #" in v
            or v[0] in "!&*?|>%@`,[]{}#\"'" or "\t" in v)


def parse(path):
    """Return (frontmatter dict, body str). Same first-colon parsing as kb-sync.py."""
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


def valid_date(s):
    if not DATE.match(s):
        return False
    y, mo, d = (int(x) for x in s.split("-"))
    return 1 <= mo <= 12 and 1 <= d <= 31


def main():
    if not os.path.isdir(VAULT):
        print(f"kb-lint: no vault at {VAULT}", file=sys.stderr)
        return 2

    errors, warns = [], []
    names_seen = defaultdict(list)   # name -> [files]  (uniqueness across the whole vault)
    n_shards = 0

    # collect shard files from the atomic collections + architecture.md (a single shard)
    files = []
    for c in COLLECTIONS:
        files += sorted(glob.glob(os.path.join(VAULT, c, "*.md")))
    arch = os.path.join(VAULT, "architecture.md")
    if os.path.exists(arch):
        files.append(arch)

    for f in files:
        rel = os.path.relpath(f, ROOT)
        fm, body = parse(f)

        # architecture.md ships as a *fillable scaffold*. Until it's filled it still holds `{PROJECT}`
        # / `updated: TODO`, which would (correctly) trip the placeholder + date checks below. That
        # would make the documented copy-then-run flow AND the kit's own `template/` fail the gate on
        # day one. Treat an unfilled architecture scaffold as a WARNING (fill it or delete it), not an
        # ERROR — a filled one is linted normally, and KB_STRICT=1 still turns the warning into a fail.
        if f == arch and (fm.get("updated") == "TODO" or fm.get("provenance") == "TODO"
                          or "{PROJECT}" in (body + " " + fm.get("title", ""))):
            warns.append(f"{rel}: architecture scaffold not yet filled — fill it or delete it (skipped)")
            continue
        n_shards += 1

        def err(msg):
            errors.append(f"{rel}: {msg}")

        def warn(msg):
            warns.append(f"{rel}: {msg}")

        if not fm:
            err("no YAML frontmatter (a shard must open with a --- block)")
            continue

        for k in REQUIRED:
            if not fm.get(k):
                err(f"missing required field `{k}`")
        for k in RECOMMENDED:
            if not fm.get(k):
                warn(f"missing recommended field `{k}`")

        name = fm.get("name", "")
        if name:
            names_seen[name].append(rel)
            if not KEBAB.match(name):
                err(f"name `{name}` is not kebab-case")
            slug = os.path.basename(f)[:-3]
            if slug != name and f != arch:
                warn(f"name `{name}` != filename `{slug}` ([[links]] resolve by name)")

        if fm.get("type") and fm["type"] not in TYPES:
            err(f"type `{fm['type']}` not in {{{','.join(sorted(TYPES))}}}")
        if fm.get("status") and fm["status"] not in STATUS:
            err(f"status `{fm['status']}` not in {{{','.join(sorted(STATUS))}}} "
                f"(off-schema value — pick one or extend KB_STATUS)")
        if fm.get("volatility") and fm["volatility"] not in VOLATILITY:
            err(f"volatility `{fm['volatility']}` not in {{{','.join(sorted(VOLATILITY))}}} "
                f"(dialect drift — pick one or extend KB_VOLATILITY)")

        upd = fm.get("updated", "")
        if upd and not valid_date(upd):
            err(f"updated `{upd}` is not a real YYYY-MM-DD date"
                + (" (unfilled placeholder)" if "YYYY" in upd else ""))

        for k, v in fm.items():                 # Obsidian-breaking frontmatter → run kb-fix.py
            if yaml_unsafe(v):
                err(f"field `{k}` has an unquoted value that breaks Obsidian's YAML "
                    f"({v[:48]!r}…) — run kb-fix.py")

        hay = (body + "\n" + "\n".join(f"{k}: {v}" for k, v in fm.items()))
        for p in PLACEHOLDERS:
            if p in hay:
                err(f"unfilled template placeholder present: {p!r}")

        # status/volatility/summary that contradict each other — each one misroutes the LIVE tier
        if fm.get("status") == "active" and fm.get("volatility") == "one-shot":
            warn("status `active` with volatility `one-shot` (one-shot = a closed record) — "
                 "kb-staleness never re-checks it; use decays-with-code while it's open")
        if fm.get("status") == "active" and CLOSED_WORDS.match(fm.get("live_summary", "")):
            warn("live_summary says it's closed but status is `active` — it is still listed as open "
                 "in every LIVE block")

        if MAX_LINES and body.count("\n") > MAX_LINES:
            warn(f"body is {body.count(chr(10))} lines (> {MAX_LINES}) — likely non-atomic; "
                 f"consider splitting")

    # shards the tooling can't see: frontmatter'd .md outside the collections and reference/
    known = set(COLLECTIONS) | {"reference"}
    for dp, dns, fns in os.walk(VAULT):
        dns[:] = [d for d in dns if not d.startswith(".")]
        reldir = os.path.relpath(dp, VAULT)
        top = reldir.split(os.sep)[0]
        for fn in fns:
            if not fn.endswith(".md") or (reldir == "." and fn in ROOT_FILES) or top in known:
                continue
            fm, _ = parse(os.path.join(dp, fn))
            if fm.get("name"):
                warns.append(f"{os.path.relpath(os.path.join(dp, fn), ROOT)}: shard outside the kit's "
                             f"collections — INDEX, MOCs, kb-lint and kb-staleness never see it "
                             f"(move it into {'/'.join(COLLECTIONS)}/ or reference/)")

    # log.md: the `## [YYYY-MM-DD] kind | summary` heading is what the documented finder greps for
    log = os.path.join(VAULT, "log.md")
    if os.path.exists(log):
        heads = [ln.rstrip() for ln in open(log, errors="ignore") if ln.startswith("## ")]
        bad = [h for h in heads if not LOG_HEADING.match(h)]
        if bad:
            warns.append(f"{os.path.relpath(log, ROOT)}: {len(bad)} of {len(heads)} entry heading(s) "
                         f"don't match `## [YYYY-MM-DD] kind | summary` (e.g. {bad[0][:60]!r}) — "
                         f"`grep '^## \\['` and other tooling won't find them")

    readme = os.path.join(VAULT, "README.md")
    if os.path.exists(readme):
        txt = open(readme, errors="ignore").read()
        found = [m for m in README_SMELLS if m in txt]
        h1 = README_H1.search(txt)
        project = os.environ.get("KB_PROJECT") or os.path.basename(ROOT.rstrip("/"))
        if h1 and h1.group(1) in KIT_NAMES and project not in KIT_NAMES:
            found.append(f"H1 names the kit ({h1.group(1)}), not this project — copied from the kit's dogfood vault?")
        if found:
            warns.append(f"{os.path.relpath(readme, ROOT)}: schema README still has template/kit text "
                         f"({', '.join(repr(f) for f in found)}) — fill it in from the kit's template/README.md")

    for name, locs in names_seen.items():
        if len(locs) > 1:
            errors.append(f"duplicate name `{name}` in: {', '.join(locs)} "
                          f"([[{name}]] links become ambiguous)")

    print(f"kb-lint: {n_shards} shards in {os.path.relpath(VAULT, ROOT)}")
    for e in errors:
        print(f"  ✗ ERROR  {e}")
    for w in warns:
        print(f"  ! warn   {w}")
    fail = len(errors) + (len(warns) if STRICT else 0)
    print(f"\n{len(errors)} error(s), {len(warns)} warning(s)"
          + (" — STRICT: warnings fail too" if STRICT else "")
          + (".  clean ✓" if fail == 0 else "."))
    return 1 if fail else 0


if __name__ == "__main__":
    sys.exit(main())
