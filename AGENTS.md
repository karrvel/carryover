# AGENTS.md — for an agent working inside carryover

This repo is a **kit**, not a project to build. It gives *other* projects a durable, agent-maintained
knowledge base (plain-markdown, git-versioned, two-tier memory). Two jobs bring you here:

## Job A — initialize this kit into a target project
The user wants a knowledge base set up in some *other* project. Follow the
**[initialization prompt in README.md](README.md#agent-initialization)** verbatim — it handles
empty/fresh and brownfield projects. In short: copy `template/` → the project's `_knowledge/`,
`tooling/*.py` **and** `tooling/*.sh` → its `_meta/`, wire the `CLAUDE.md` LIVE markers, mine all
three raw sources below (skeleton-first, verify against code), then run
`kb-sync → kb-fix → kb-lint → kb-links`.

If the target project already has its own root `AGENTS.md` (or `GEMINI.md` / `.cursor/rules/kb-context.mdc`),
`kb-sync.py` will **not** clobber it: any such file it didn't write itself is reported with a warning
and skipped, and the run continues normally (exit 0). Handle it deliberately — **rename or move the
existing file, or drop that platform from `KB_PLATFORMS`** — then re-run. **Never paste the
generated block into the existing file:** the block opens with kb-sync's ownership marker, so the
next run would consider the file its own and overwrite it wholesale. (Ownership is that marker
alone — an HTML comment at the start of a line within the file's first 10 lines; prose that merely
*mentions* the marker does not make a file owned.) Also make sure a project-root `CLAUDE.md` exists
before the first `kb-sync` run, or it warns that the LIVE blocks aren't wired and continues (exit 0).

### Raw sources to mine at init (in priority order)

**1. Git commit history — do this first, it's free and fast.**
Run these in the target project's repo root before touching agent transcripts:
```bash
# overview — scope and cadence
git log --oneline | head -100

# detailed recent history — decisions, gotchas, incident responses
git log --format="%ad %h %s%n%b" --date=short --since="6 months ago"

# most-frequently-modified files — the hot spots worth documenting first
git log --pretty=format: --name-only | grep -v '^$' | sort | uniq -c | sort -rn | head -30

# per-commit churn, newest first — scan for the outsized ones (rewrite or incident fix)
git log --shortstat --since="1 year ago" | grep -E "files? changed"
```
Look specifically for: commit messages mentioning "fix", "bug", "revert", "hotfix", "do not",
"workaround", "broken" → these are gotcha candidates. Messages mentioning "decision", "choose",
"switch", "replace", "instead of" → decision candidates. Subjects describing a refactor or
incident response → architecture/security candidates. Write each finding as its own shard with
`provenance: git:<short-hash> <date>`.

**2. Agent transcripts — highest-value for off-code tribal knowledge.**
`prefilter.py` against `~/.claude/projects/<encoded-cwd>/` + `~/.codex/sessions/` — strips ~95–98%
tool-call noise. Mine after the git pass so you don't duplicate what commits already say.

**3. Reference docs — PRDs, architecture docs, prior analyses.**
Copy into `_knowledge/reference/`. These are the skeleton backbone; distill them before gap-filling
from transcripts.

## Job B — improve the kit itself
You're editing the template, tooling, or research here. Rules:
- **Tooling is stdlib-only Python 3** (no deps) and idempotent. Keep it that way. Each script derives
  `KB_ROOT` as two dirs up from itself and honors `KB_*` env overrides.
- **The scripts are the contract.** Frontmatter schema lives in `template/_SHARD_TEMPLATE.md` +
  `template/README.md`; `kb-lint.py` enforces it; `kb-sync.py` reads it to generate navigation. Change
  one, change all three consistently.
- **Never commit secrets or real project data.** `tooling/kb-eval/traps.jsonl` is a *redacted example*;
  real traps live in the git-ignored `traps.local.jsonl`, and `tooling/kb-eval/results/` is git-ignored.
  Before committing, scan for prod identifiers, tokens, and absolute user paths.
- **This repo is public — a mechanical PII guard enforces it.** `tooling/pii-scan.py` (codified
  regexes: Claude session URLs, `/Users/…` paths, tokens, emails) blocks pushes via a **pre-push**
  hook. Enable per-clone: `ln -sf ../../tooling/hooks/pre-push .git/hooks/pre-push` (or
  `git config core.hooksPath tooling/hooks`). User/project-specific literals (other private repo
  names, personal emails) go in a **git-ignored** `.pii-denylist.local` at the repo root — never
  commit it. Run manually anytime: `python3 tooling/pii-scan.py [--range origin/main..HEAD]`.
  False positive? Add the safe substring to a gitignored `.pii-allowlist.local` at the repo root (or to
  `ALLOW` in `pii-scan.py` if it is generic to every user).
- **The research is fact-checked, and `research/` is published.** Claims here were adversarially
  verified: don't add one without a primary source, and preserve the "hedges / refuted claims"
  honesty. Everything in `research/` must also be **project-agnostic and PII-free** — it ships to
  a public repo. If a finding came out of work on a specific codebase, distil the portable,
  scrubbed conclusion and leave the raw write-up (prod names, paths, internal URLs, session
  transcripts) wherever it originated. Never paste an unredacted audit in wholesale; the pre-push
  PII guard catches the mechanical patterns, not a paragraph naming someone's internal service.
- After changing `template/`, validate it by pointing the vault at the template (the scripts default
  `KB_VAULT` to `$KIT/_knowledge`, which doesn't exist in the kit — you must override it):
  `KB_VAULT="$PWD/template" python3 tooling/kb-lint.py && KB_VAULT="$PWD/template" python3 tooling/kb-links.py`.
  Both must exit 0. The unfilled `architecture.md` scaffold warns (fill-or-delete) rather than errors.

## Layout
`research/` = why · `template/` = the vault scaffold · `tooling/` = the scripts · `HOWTO.md` = the
build playbook. `README.md` is the human+agent entry point.
