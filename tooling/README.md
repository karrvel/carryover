# tooling

Portable scripts (stdlib Python 3 only — no deps). Copy the ones you use into your project's `_meta/`.

## The maintenance loop (run in this order after editing shards)
```bash
python3 _meta/kb-sync.py       # 1. regenerate MOCs + INDEX + MEMORY.md + CLAUDE.md LIVE blocks
python3 _meta/kb-fix.py        # 2. make frontmatter Obsidian-safe (quote hazardous values)
python3 _meta/kb-lint.py       # 3. gate: schema valid? (exit 1 on error)  — CI / pre-commit
python3 _meta/kb-links.py      # 4. gate: broken [[wikilinks]] / dead file refs? — CI / pre-commit
python3 _meta/kb-staleness.py  # 5. what volatile knowledge is overdue for re-verification?
```
`kb-lint` and `kb-links` are the two *blocking* gates you want in a pre-commit hook (`kb-fix` runs
first but never blocks); the shipped hook adds `kb-sync --check` as an advisory fourth stage — see
below. `kb-staleness`
is the one you want in a pre-session / weekly nudge — it surfaces the `decays-with-code` backlog
everyone skips. **Measuring impact** (does the KB change what the agent does): see `kb-eval/`.

### Pre-commit hook (git vaults)
A ready hook lives at `hooks/pre-commit`. It fires only when markdown files under the vault dir
(`$KB_VAULT`, default `_knowledge/`) are staged, at any depth, then runs exactly
four stages: kb-fix (auto-quotes Obsidian-breakers + re-stages), kb-lint (blocks on schema errors),
kb-links (blocks on broken internal links), and kb-sync `--check` (advisory — warns, never blocks,
when the generated nav/MOCs/INDEX have drifted from the shards, or a platform file has been
orphaned). Note `kb-sync --check` does **not**
check the `CLAUDE.md` LIVE blocks. It also emits a non-blocking nudge when paths listed in
`KB_CODE_PATHS` are staged without a vault change. There is no install script — installation is manual
(one-time, per clone); always clone into a fresh dir, never a fixed `/tmp` path, or a stale clone
silently installs a stale kit:
```bash
KIT=$(mktemp -d) && git clone --depth 1 https://github.com/karrvel/carryover.git "$KIT"
mkdir -p /path/to/project/_meta
cp "$KIT"/tooling/*.py "$KIT"/tooling/*.sh /path/to/project/_meta/
mkdir -p /path/to/project/.githooks
cp "$KIT"/tooling/hooks/pre-commit /path/to/project/.githooks/
chmod +x /path/to/project/.githooks/pre-commit
git -C /path/to/project config core.hooksPath .githooks   # ← see the warning below if the repo has hooks
```
The hook reads scripts from `_meta/` and finds the repo root itself, so it's project-agnostic.
Bypass a single commit with `git commit --no-verify`. (Needs a git repo — a plain-folder vault has
no commit to gate; run the loop manually there.) Two of those steps are **per clone**: `_meta/` is
gitignored and `core.hooksPath` is local config, so a teammate who clones the project gets neither
the scripts nor the gate (`.githooks/` itself is tracked, so the hook file arrives with the clone —
don't re-copy it over a customized one). Every contributor re-runs just the `_meta/` copy and the
`core.hooksPath` line once, or their ungated commits can land an invalid shard that blocks everyone
else's commits.

> **`core.hooksPath` replaces `.git/hooks` entirely**, disabling every hook the project already had.
> If the repo already has hooks, keep them and *chain* the KB gate from the existing
> `.git/hooks/pre-commit` instead by appending
> `. "$(git rev-parse --show-toplevel)"/.githooks/pre-commit` to it. Until one of these two wirings
> is in place, the KB gate is **not** running.

**Advisory variant** (`hooks/pre-commit-advisory`): for a vault with pre-existing rot you haven't
cleaned yet, this auto-fixes Obsidian frontmatter but only *reports* lint/link counts — it never
blocks. Install it in place of the hard hook (from the same `$KIT` clone as above) — note it must
land under the name git invokes, `pre-commit`, or it never runs:
```bash
cp "$KIT"/tooling/hooks/pre-commit-advisory /path/to/project/.githooks/pre-commit
chmod +x /path/to/project/.githooks/pre-commit
```
Swap in the hard `pre-commit` once the vault is clean. It sources `.githooks/kb.env` if
present, so per-repo settings live there — e.g. `export KB_VOLATILITY="durable,decays-with-code,decays-with-prs,one-shot"`
for a non-standard dialect, or `KB_SKIP_LINT=1` for a vault that predates this frontmatter schema.

> **The Python scripts read `kb.env` themselves** (since 0.6), so a manual
> `python3 _meta/kb-sync.py` sees the same settings as the hook. They *parse* it — they never execute
> it: only `KB_NAME=value` / `export KB_NAME="value"` lines count, with no `$VAR` expansion, and
> anything already set in the environment wins. `KB_ROOT` is the one key they ignore there, because
> it is what locates `kb.env` in the first place. The hook still sources the file into its own shell
> for the vars only it reads (`KB_SKIP_LINT`, `KB_CODE_PATHS`, `KB_META`); `export`ing everything
> remains the habit that works for both.

**Versioning only the vault** (workspace has nested git repos or secrets in `_meta/`): `git init` at
the workspace root, then drop in the ready whitelist — it tracks the vault, its wiring, and the
generated agent-context files, and nothing else:
```bash
cp "$KIT"/setup/workspace.gitignore /path/to/workspace/.gitignore
```
[`setup/workspace.gitignore`](../setup/workspace.gitignore) is the canonical list — it isn't
restated here so the two can't drift. This keeps `_meta/` (secret backups), `repos/` (nested repos),
and heavy dirs untracked while versioning the knowledge. Verify with `git diff --cached --name-only`
that nothing sensitive is staged before the first commit.

---

## prefilter.py — transcripts → digests
Distills Codex + Claude Code JSONL transcripts into compact, provenance-tagged per-session digests
(strips ~95–98% tool-call noise). Handles both schemas; buckets by cwd.
```bash
python3 prefilter.py --match <project-keyword> --out ./digests
# optional: --buckets "backend=api,web=frontend"  --codex ~/.codex/sessions  --claude ~/.claude/projects
```

## kb-sync.py — shards → navigation + memory
Regenerates the MOC index files, `INDEX.md`, the always-loaded `MEMORY.md`, the `CLAUDE.md`
LIVE sync blocks, and the per-platform context files (see `KB_PLATFORMS`), from shard frontmatter.
Idempotent.
```bash
python3 kb-sync.py
KB_ROOT=/path/to/project KB_PROJECT=myproj KB_TODAY=2026-07-05 python3 kb-sync.py
```
Env: `KB_ROOT`, `KB_VAULT`, `KB_MEMORY_DIR`, `KB_PROJECT`, `KB_TODAY`, `KB_AREAS`, `KB_PLATFORMS`,
`KB_LIVE_MAX` (default 30 — a normal run warns when the LIVE tier lists more items than this, or
when a LIVE line runs past 300 chars; it never fails).
`KB_PLATFORMS` (comma-separated; default `claude,codex,gemini,cursor`; whitespace around items is
tolerated) picks which context files get generated — `claude` → `MEMORY.md` **and** the `CLAUDE.md`
LIVE blocks · `codex` → `AGENTS.md` (also read by Antigravity) · `gemini` → `GEMINI.md` ·
`cursor` → `.cursor/rules/kb-context.mdc`. It is read from the **environment of the kb-sync run**, so
set it per repo in `.githooks/kb.env` (read by every run, manual or hook), or per run —
`KB_PLATFORMS=claude,gemini python3 _meta/kb-sync.py`; the environment wins over `kb.env`. The `CLAUDE.md`
LIVE blocks need the two `<!-- BEGIN:sync:live-security -->…` / `open-work` marker pairs in the
project-root `CLAUDE.md`; if there's no `CLAUDE.md` at all, kb-sync **warns** and moves on (exit 0)
— the blocks are simply not wired until you create it with the two marker pairs.

**Collision guard.** For the three project-root files it generates — `AGENTS.md`, `GEMINI.md`,
`.cursor/rules/kb-context.mdc` — kb-sync refuses to overwrite a file that already exists but was
**not** generated by it. Ownership is detected by an HTML-comment marker anchored at the start of a
line within the file's first 10 lines, so a doc that merely mentions the marker in prose is *not*
treated as owned. On a collision it prints a warning naming the file, skips it, and continues with
the rest (exit code stays 0). The remedy is to **rename or move your file**, or drop that platform
from `KB_PLATFORMS`. Do **not** paste the generated block into your own file: the block carries the
ownership marker, so kb-sync would then consider the file its own and overwrite it on the next run.
A hand-written `AGENTS.md` is never clobbered. `MEMORY.md`, `INDEX.md`, and the MOCs are *not*
covered by the guard — kb-sync always rewrites those.

**Orphan detection.** The mirror image of a collision: for the same three project-root files,
kb-sync reports one that it *did* generate but no longer maintains, because that platform has since
been dropped from `KB_PLATFORMS`. Such a file just sits there — frozen at the LIVE security findings
and open work of the last run, still committed, still read by every agent. kb-sync names the file and
the platform on a normal run and under `--check` (so the hook's advisory stage surfaces it), and
states the fix: delete the file, or put the platform back in `KB_PLATFORMS`. It **never** deletes or
modifies the file — it may be tracked by your git. Only kb-sync-owned files count, decided by the
same anchored-marker test as the collision guard: a same-named file you wrote yourself is a collision,
not an orphan, and is not reported here. `MEMORY.md` and `CLAUDE.md` are out of scope — `CLAUDE.md`
belongs to you and kb-sync only splices between its markers. An orphan is a warning, not an error —
a normal run still exits 0, and under `--check` it is reported as drift like any stale generated file.

## kb-lint.py — enforce the schema (so a vault can't drift into dialects)
Validates every shard's frontmatter: required fields present; `type`/`status`/`volatility` values
canonical (catches `decays-with-prs` vs `decays-with-code`, off-schema `done`/`complete`); dates
well-formed; names unique + kebab-case; no unfilled template placeholders; **and no unquoted values
that break Obsidian's YAML** (see `kb-fix`). Exit 1 on any ERROR — wire into pre-commit / CI.

It also **warns** (never fails, unless `KB_STRICT=1`) about things that misroute the tooling: a
shard with frontmatter outside the collections and `reference/` (e.g. an `ops/` folder — INDEX, MOCs,
lint and staleness never see it); `status: active` with `volatility: one-shot`; an active shard
whose `live_summary` opens with resolved/superseded/fixed/done/closed; `log.md` headings that don't
match `## [YYYY-MM-DD] kind | summary`; and a vault `README.md` that still holds template text or was
copied from the kit's own dogfood vault. A vault running `KB_STRICT=1` will start failing on these
after an upgrade — that is the point, but fix or relax before you update.
```bash
python3 kb-lint.py                                            # report + gate
KB_STRICT=1 python3 kb-lint.py                                # warnings fail too
KB_VOLATILITY=durable,decays-with-code,decays-with-prs,one-shot python3 kb-lint.py   # allow a dialect
```
Env: `KB_ROOT`, `KB_VAULT`, `KB_VOLATILITY`, `KB_STATUS`, `KB_TYPES`, `KB_MAX_LINES`, `KB_STRICT`.

## kb-fix.py — repair Obsidian-breaking frontmatter
Obsidian's Properties parser is strict YAML; it errors ("mapping values are not allowed here") when a
value is an **unquoted scalar containing `: `, a leading reserved char (`@ ! & * ? | > % # , [ {` `` ` ``),
or ` #`** — which creep in constantly via `provenance:`/`title:` (`Path: /Users/...`, `Trigger #2`,
`title: Repo: orgn`). This double-quotes exactly those values (escaped), leaving everything else
byte-for-byte. Idempotent; run it after `kb-sync` / on save.
```bash
python3 kb-fix.py                # repair in place
python3 kb-fix.py --dry-run      # preview, write nothing
python3 kb-fix.py --check        # exit 1 if anything needs fixing (CI / pre-commit)
```
Env: `KB_ROOT`, `KB_VAULT`.

## kb-links.py — link-rot checker
The non-LLM doc-health signal that has no off-the-shelf tool for a markdown vault. Flags broken
`[[wikilinks]]` (a shard linking to a target that doesn't exist — classic forward-ref rot),
dead local file references, and optionally dead external URLs. Resolves wikilinks the Obsidian way
(by basename; `[[dir/foo]]`, `[[foo.md]]`, `[[foo|alias]]`, `[[foo#anchor]]` all → `foo`). Exit 1 on
broken internal links → pre-commit / CI.
```bash
python3 kb-links.py            # internal links only (fast, offline)
python3 kb-links.py --urls     # also HEAD-check external URLs (slow, network; advisory-only)
KB_LINKS_IGNORE='^/[A-Z]+/issues/' python3 kb-links.py   # skip targets matching a regex
```
Env: `KB_ROOT`, `KB_VAULT`, `KB_LINKS_IGNORE` (a regex; markdown-link targets it matches aren't
checked as local files — for tracker-relative links pasted from an issue tracker, which would
otherwise fail the hard gate forever).

## kb-staleness.py — the re-verify queue
Surfaces the one discipline every vault skips: volatile (`decays-*`) shards whose `updated:` is older
than the threshold (they must be re-checked against code before an agent trusts them), plus
backtick-quoted source paths that no longer exist under the code root (code that moved out from
under a shard). Read-only. It reads the five collections, `reference/` and `architecture.md`. The
code root is `KB_REPOS`, else `repos/` when it exists (workspace layout), else the project root
(embedded layout — before 0.6 the anchor check silently skipped every embedded vault). `./x.sh` and
`x.sh` are the same anchor; a bare extension like `.d.ts` is not one.
```bash
python3 kb-staleness.py                          # report the backlog, newest-overdue last
KB_STALE_DAYS=7 python3 kb-staleness.py --fail-on-stale   # gate a pre-session hook
python3 kb-staleness.py --age-only               # skip the anchor check
```
Env: `KB_ROOT`, `KB_VAULT`, `KB_REPOS` (default: `repos/` if present, else the root), `KB_STALE_DAYS`,
`KB_TODAY`. A project with a GitHub-PR
convention can layer a `gh pr view` drift check on top in its own `_meta/`.

## kb-session-start.sh — the cold-start orientation print
POSIX `sh`: first runs `kb-doctor.py --brief` when it's next to it (prints nothing for a healthy
vault; needs `python3`), then prints every **active** gotcha (`[[name]] — title`, skipping `resolved` /
`superseded`) plus the open tasks, so a fresh session sees the traps before it touches code. Cheap
enough to run every session.
```bash
sh _meta/kb-session-start.sh                       # run it
KB_VAULT=/path/to/_knowledge sh _meta/kb-session-start.sh
```
Env: `KB_VAULT` (default `$repo-root/_knowledge`). Install it alongside the Python scripts — the
`cp` above copies `tooling/*.sh` too — then wire it wherever your agent reads a first action (a
`SessionStart` hook, or a "First action every session" line in `CLAUDE.md` / `AGENTS.md`).
`kb-update.py` refreshes it along with the `*.py` scripts (since 0.6).

## kb-doctor.py — is the vault actually protected?
The content gates (kb-lint, kb-links, kb-sync --check) all pass on a vault that was never committed,
has no gate wired, or was just rolled back by an editor — and the gate itself only runs on commit.
kb-doctor checks that operational layer, read-only: git repo / HEAD / vault tracked / uncommitted
vault work and its age / remote; `core.hooksPath` **and** a hook file behind it; `_meta/` ignored;
`.githooks/kb.env` not swallowed by a `*.env` ignore; CLAUDE.md markers; MEMORY.md at the derived
memory dir; and a rollback heuristic (net vault deletion ≥200 lines and >3× the additions vs HEAD, or
any shard whose `updated:` is older than at HEAD).
```bash
python3 _meta/kb-doctor.py           # full report
python3 _meta/kb-doctor.py --brief   # problems only, silent when healthy (kb-session-start.sh uses this)
python3 _meta/kb-doctor.py --fail    # exit 1 on any problem — for CI or a wrapper script
```
Env: `KB_ROOT`, `KB_VAULT`, `KB_MEMORY_DIR`, `KB_PLATFORMS` (as kb-sync; also read from `kb.env`).

## pii-scan.py — mechanical private-context guard (for a repo that goes public)
A fixed list of codified regexes — session URLs, `/Users/…` home paths, emails, private keys, AWS /
GitHub / OpenAI-style tokens, secret assignments — over tracked file **contents**, the **staged**
diff, or a commit **range** (messages, lines added anywhere in it, and the **author/committer
identities** `git log` publishes). Exits 1 on any match, so it can gate a push. Project-specific
literals belong in a gitignored local denylist (`.pii-denylist.local` at the repo root, or
`--denylist` / `$PII_DENYLIST`); project-specific false positives in a gitignored
`.pii-allowlist.local` (one safe substring per line) — both survive kit updates, unlike edits to
`ALLOW` in the script. It prints how many tracked files it scanned and treats **0** as a failure
(a repo with nothing committed has nothing to vouch for). `generic-secret-assign` matches
`UPPER_SNAKE_SECRET=` env lines, and needs a quoted literal or a digit-bearing ≥12-char value, so
type annotations and `x = os.environ.get(...)` don't trip it.
```bash
python3 tooling/pii-scan.py                             # all tracked files
python3 tooling/pii-scan.py --staged                    # staged additions (pre-commit)
python3 tooling/pii-scan.py --range origin/main..HEAD   # + messages, added lines, identities you're about to push
```
Exit 0 = clean, 1 = matches, 2 = aborted because a `git` command failed (e.g. an invalid `--range`)
— it fails closed, so a 2 is never "clean". `hooks/pre-push` runs it automatically over the tree
*and* the commits being pushed (history is permanent once public). In a clone of this kit:
```bash
git config core.hooksPath tooling/hooks      # per clone; bypass once with git push --no-verify
```
To use it in a project that already points `core.hooksPath` at `.githooks/`, copy `hooks/pre-push`
there (`chmod +x`) alongside the KB `pre-commit`. It looks for the scanner at
`<repo-root>/tooling/pii-scan.py`, then `${KB_META:-<repo-root>/_meta}/pii-scan.py`, and **blocks the
push** if neither exists — a guard that can't run must not look like one that passed.

## kb-update.py — pull new kit versions

Updates the top-level `tooling/*.py` scripts copied into `_meta/` to the **newest release tag** of the
public repo (or whatever ref you ask for — see below), plus the `*.sh` helpers and — when the
project has one — `.githooks/pre-commit` (matched to the hard or advisory variant you installed;
never installed if absent). **Not** `kb-eval/`, and never `_knowledge/`. The installed version is
read from `kb-sync.py`'s own `VERSION`; the `kb.version` pin is only a fallback, written **only**
when every offered file was applied, and **never** by `--check`. A target **older** than the
installed version is refused (exit 2, nothing written) unless you named it with `--ref`.

```bash
python3 kb-update.py            # interactive — colored diff per file, [y]es/[n]o/[a]ll/[q]uit
python3 kb-update.py --yes      # silent (-y) — prints warning + 8-second countdown, then overwrites
python3 kb-update.py --check    # dry-run (--dry-run / -n) — show what would change, write nothing
python3 kb-update.py --main     # use the default branch tip instead of a release tag
python3 kb-update.py --ref REF  # pin to an explicit tag, branch or sha (takes the next argument)
python3 kb-update.py --help     # usage (-h)
```
Exit codes: `0` ok · `1` updates exist (`--check`) or aborted · `2` usage error, clone failure, or
`git ls-remote` failure · `3` interactive run with no tty.

**Which ref gets cloned.** With no ref flag, kb-update asks the remote for its tags
(`git ls-remote --tags --refs`) and keeps only the ones shaped like a version — an optional leading
`v` then a dotted numeric version (`v0.5`, `0.5`, `v1.2.3`). Those are ordered by **numeric tuple**,
never lexically, so `v0.10` sorts above `v0.9`; anything else (`-rc1`, `-beta`, arbitrary tag names)
is ignored. The highest one wins and is cloned shallowly at that tag. `--main` takes the default
branch tip instead — the older behaviour, for people tracking development — and `--ref <REF>`
pins to exactly what you name (it consumes the next argument, so a value like `v0.5` is never
mistaken for an unknown flag; the two ref flags are mutually exclusive, exit 2). The run header says
which it used, e.g. `target: v0.5 (newest release)`.

Two edge cases, deliberately different: a remote with **no usable tags** is not an error — kb-update
prints a one-line note and falls back to the default branch. A **failing `git ls-remote`** (network,
auth) *is*: it prints the error and exits 2, the same as a failed clone, rather than silently
updating you from an unintended ref.

> **Silent mode warning.** New scripts can change how secrets and paths are handled. Run
> interactive at least once on a new version before using `--yes` in automation.
