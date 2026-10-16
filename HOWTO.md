# HOWTO — build a knowledge base for any project

The step-by-step method used to build a real project vault (~130 shards distilled from ~1.1 GB of
agent transcripts). Reusable for any project. The *why* is in `research/`; this is the *how*.

## 0. Decide it's the right tool (30 seconds)
Plain-markdown two-tier wiki is the right call when the KB is **single-curator** and fits in
**≲ 150–200 pages / ≲ 50–100k tokens**. Larger / multi-tenant / heavily time-varying → still build
the wiki, but plan to add vector or graph retrieval *on top* later. See
`research/plain-markdown-vs-vector-rag.md`.

## 1. Scaffold the vault

First, choose your setup model (see the [README](README.md#choose-your-setup) for the full comparison):

- **Option A — Workspace**: a standalone wrapper directory whose git tracks only `_knowledge/`.
  Best for multiple related repos. Copy `setup/workspace.gitignore` → root `.gitignore`.
- **Option B — Embedded**: vault lives inside an existing project repo, tracked alongside source.
  Best for a single project. Append `setup/embedded.gitignore` → existing `.gitignore`.

Then scaffold:
```bash
# clone into a fresh dir — never a fixed /tmp path, a stale clone silently installs a stale kit
KIT=$(mktemp -d) && git clone --depth 1 https://github.com/karrvel/carryover.git "$KIT"

# copy vault scaffold
cp -R "$KIT/template" <your-root>/_knowledge

# copy the scripts — both the Python tools and the shell helpers
mkdir -p <your-root>/_meta && cp "$KIT"/tooling/*.py "$KIT"/tooling/*.sh <your-root>/_meta/

# copy gitignore for your chosen option (A or B)
cp "$KIT/setup/workspace.gitignore" <your-root>/.gitignore     # Option A
# — OR —
cat "$KIT/setup/embedded.gitignore" >> <your-root>/.gitignore  # Option B
```
Edit `_knowledge/README.md`: replace `{PROJECT}` and `TODO`. Add the two LIVE sync-block markers to
your project-root `CLAUDE.md` (see step 6).

## 2. Gather the raw sources (Karpathy layer 1)
Three kinds, in priority order:

- **Git commit history — do this first.** Free, instant, zero LLM tokens. `fix`/`bug`/`revert`/
  `workaround` in commit subjects → gotcha candidates. `decision`/`choose`/`switch`/`instead of` →
  decision candidates. Large incident-response or refactor commits → architecture/security candidates.
  ```bash
  git log --oneline | head -100
  git log --format="%ad %h %s%n%b" --date=short --since="6 months ago"
  git log --pretty=format: --name-only | grep -v '^$' | sort | uniq -c | sort -rn | head -30
  ```

- **Already-distilled docs** — PRDs, architecture docs, prior codebase analyses. Copy into
  `_knowledge/reference/`. **These are the skeleton backbone** — far higher signal-per-token than raw
  transcripts. Build the skeleton from these before mining transcripts.

- **Agent transcripts** — Codex (`~/.codex/sessions`) + Claude Code (`~/.claude/projects`). These
  *fill gaps* (gotchas, decisions, security findings, remaining work) the docs and git history don't have.

## 3. Pre-filter the transcripts (cheap, no LLM tokens)
```bash
python3 _meta/prefilter.py --match <project-keyword> --out ./_kb-digests
```
Strips ~95–98% tool-call noise → provenance-tagged per-session digests, bucketed by cwd. Prints a
size table. **Measure before you fan out.** Keep the `--out ./_kb-digests` flag: digests are distilled
transcript content you don't want committed, and `_kb-digests/` is the name `setup/embedded.gitignore`
excludes by default (the script's own default, `./digests`, is *not* ignored). The workspace model
already ignores it via its whitelist.

## 4. Distill — skeleton first, then gap-fill (fan-out)
- **Skeleton (from `reference/`):** one agent per repo/component writes a `repos/<name>.md` shard;
  one writes `architecture.md`; one seeds `security/` + `decisions/` + `tasks/`. **Have agents
  verify against current code and correct stale doc claims.**
- **Gap-fill (from digests):** chunk the digests (~300–400 KB each), fan out one extractor agent per
  chunk returning structured items `{type, area, title, body, volatility, provenance, confidence}`,
  then one synthesis agent per collection dedupes/merges and writes atomic shards — **reading the
  existing skeleton shards first so it doesn't duplicate them.**
- **Recency-weight.** Fully distill recent sessions; skip/sample old analysis runs whose output is
  already in `reference/`. **Log what you skip — no silent caps.**
- Use cheaper models (e.g. Sonnet, not the frontier tier) for the fan-out — it's the token-dominant
  part. Reserve the strong model for hard verify/judge stages.

## 5. Verify the load-bearing claims (don't enshrine fiction)
Spot-check the striking findings against current code (a claimed backdoor, a "system of record", a
port). The distillation *will* surface real, non-obvious things — but confirm before they land in
the always-loaded tier.

## 6. Wire the two tiers + generate navigation
Add to your project-root `CLAUDE.md`:
```markdown
### 🔴 LIVE — open security findings
<!-- BEGIN:sync:live-security -->
<!-- END:sync:live-security -->
### 🟠 LIVE — open work
<!-- BEGIN:sync:open-work -->
<!-- END:sync:open-work -->
```
Then:
```bash
python3 _meta/kb-sync.py     # generates MOCs + INDEX.md + MEMORY.md + fills the CLAUDE.md blocks
```

### Install the hook (required once per clone)
```bash
# reusing $KIT from step 1 — in a new shell, re-run the clone line there first
mkdir -p /path/to/project/.githooks
cp "$KIT/tooling/hooks/pre-commit" /path/to/project/.githooks/pre-commit
chmod +x /path/to/project/.githooks/pre-commit
git -C /path/to/project config core.hooksPath .githooks   # ← not in a repo that already has hooks; see below
```
The hook fires whenever files under the vault dir are staged, and runs exactly four stages:
kb-fix (auto-fix, never blocks) → kb-lint (blocks) → kb-links (blocks) → kb-sync --check
(advisory, warns only). It also emits a non-blocking nudge when paths listed in `KB_CODE_PATHS` are
staged. Run the four commands above manually after each fresh clone — there is no install script.

> ⚠️ `core.hooksPath` **replaces** `.git/hooks` wholesale — every hook the project already had
> (husky, lefthook, lint-staged, a `commit-msg` gate…) stops firing. If the repo has hooks already,
> either move them into `.githooks/` too, or skip `core.hooksPath` and install this one without
> clobbering what's there:
> ```bash
> # while core.hooksPath is set, .git/hooks/ is ignored entirely — undo it first
> # (a pre-existing value someone else set, e.g. husky's .husky, is left alone):
> [ "$(git config core.hooksPath)" = .githooks ] && git config --unset core.hooksPath
> # install only if nothing is there; never overwrite an existing hook
> [ -e .git/hooks/pre-commit ] \
>   && echo "pre-commit hook exists — chain the KB gate from it instead (see below)" \
>   || ln -sf ../../.githooks/pre-commit .git/hooks/pre-commit
> ```
> (the target is relative to `.git/hooks/`, so `../../.githooks/pre-commit` resolves from the repo root).
>
> If a hook is already there, **chain** the KB gate from it — append this line to the existing
> `.git/hooks/pre-commit`:
> ```bash
> . "$(git rev-parse --show-toplevel)"/.githooks/pre-commit
> ```
> Until one of these three is done — `core.hooksPath`, the symlink, or the chain line — **the KB
> gate is not running** and commits go through unchecked. And if `git config core.hooksPath` already
> prints some other path, a symlink under `.git/hooks/` never runs: put the gate in that directory instead.

### Make the first commit — then check the setup
The gate runs on `git commit`, and nothing else in the kit looks at git state: lint, links and
`kb-sync --check` all pass on a vault that has **never been committed**, which is the commonest way
a vault is lost. Commit it now (check `.gitignore` covers `_meta/` and any secrets or raw evidence
first), then run the doctor:
```bash
git -C /path/to/project add -A && git -C /path/to/project commit -m "kb: initial vault"
python3 /path/to/project/_meta/kb-doctor.py     # read-only; '0 problem(s). healthy ✓' is the goal
```
`kb-doctor` checks what the content gates can't: is it a git repo, does HEAD exist, how much vault
work is uncommitted and how old, is there a remote, is the gate wired (hooksPath set *and* a hook
there), is `_meta/` ignored, is `kb.env` swallowed by a `*.env` rule, are the CLAUDE.md markers and
MEMORY.md where they belong — and whether the working tree looks **rolled back** (far more vault text
deleted than added vs HEAD, or shards whose `updated:` went backwards — an editor or agent restoring
an old snapshot; recover that *before* running kb-sync, which would bake it into MEMORY.md).
`kb-session-start.sh` runs it in `--brief` mode, so problems surface at the start of every session.

### Multi-platform support {#multi-platform}

kb-sync.py generates context files for multiple agent platforms from the same vault. Control which
files are generated with the `KB_PLATFORMS` env var — comma-separated, default
`claude,codex,gemini,cursor`, whitespace around items tolerated. It must be **exported in the
environment of the kb-sync run itself**, since that is the only thing kb-sync reads:

```sh
python3 _meta/kb-sync.py                              # default — all four platforms
KB_PLATFORMS=claude,gemini python3 _meta/kb-sync.py   # one run, Claude + Gemini only
export KB_PLATFORMS="claude,codex"                    # or set it for the whole shell / profile
```

For a per-repo setting, put `export KB_PLATFORMS="claude,codex"` in `.githooks/kb.env`. Since 0.6
every script reads that file itself (parsed, never executed), so manual runs and the hook's
`--check` agree. A value in the environment still wins over the file.

| Platform | File generated | Notes |
|---|---|---|
| `claude` | `~/.claude/projects/…/MEMORY.md` **and** the `CLAUDE.md` LIVE blocks | Claude Code auto-load tier — both halves are one platform, so dropping `claude` also stops the LIVE blocks being filled |
| `codex` | `AGENTS.md` | OpenAI Codex CLI; also read by Antigravity ≥ v1.20.3 |
| `gemini` | `GEMINI.md` | Google Antigravity native; takes priority over `AGENTS.md` within Antigravity |
| `cursor` | `.cursor/rules/kb-context.mdc` | Cursor rules (frontmatter: `alwaysApply: true`) |

All generated files share the same content (cold-start instruction, vault location, LIVE security
findings, open work). They are regenerated by `kb-sync.py` — do not hand-edit them.

**Collision guard.** For the three project-root files (`AGENTS.md`, `GEMINI.md`,
`.cursor/rules/kb-context.mdc`) kb-sync refuses to overwrite a file that already exists but carries no
kb-sync generated-by marker — i.e. one *you* wrote. It prints a warning naming the file, tells you to
rename/move it or drop that platform from `KB_PLATFORMS`, skips it and continues (exit code stays 0).
So a project with its own hand-written `AGENTS.md` keeps it — and those two are the whole remedy:
**never paste the generated block into your own file.** The block starts with the ownership marker,
so the merged file counts as kb-sync's from then on and the next run overwrites everything you wrote.
Ownership is detected from that marker only — an HTML comment at the start of a line within the first
10 lines — so a doc that merely *mentions* the marker in prose is not treated as owned.
`MEMORY.md`, `INDEX.md` and the MOCs are not covered by the guard — they are kb-sync's own files and
are always rewritten. If no project-root `CLAUDE.md` exists at all, kb-sync warns that the LIVE
blocks were not wired and continues (exit 0) — they stay unwired until you create it with the two
marker pairs.

**Orphan guard.** Dropping a platform from `KB_PLATFORMS` stops kb-sync *writing* its file — it does
not remove one already written. A generated `AGENTS.md` / `GEMINI.md` / `.cursor/rules/kb-context.mdc`
left behind that way is frozen at whatever LIVE security findings and open work it held on the last
run, and it is usually still committed — so every agent reading it is fed stale content forever, with
nothing to say so. kb-sync names such a file on a normal run *and* under `--check` (so the hook's
advisory stage surfaces it too), with the two fixes: **delete the file**, or **re-enable that platform
in `KB_PLATFORMS`**. It never deletes or edits the file itself — it may be tracked by your git. Only
files kb-sync generated are reported; a same-named file *you* wrote is the collision case above and
stays silent here. `MEMORY.md` and `CLAUDE.md` are out of scope (`CLAUDE.md` is your file — kb-sync
only splices between the markers). An orphan is a warning, not an error — a normal run still exits 0;
under `--check` it counts as drift, exactly like any other out-of-date generated file.

Commit `AGENTS.md`, `GEMINI.md`, and `.cursor/rules/kb-context.mdc` to the repo. `MEMORY.md` lives
outside the repo (in the Claude Code project-memory dir) and is never committed.

### Loading semantics (verified against Claude Code docs) {#loading-semantics}
- **`CLAUDE.md` loads hierarchically** — from cwd *up* the tree. A workspace-root `CLAUDE.md` loads
  even when you start a session inside a subdir/repo. → the LIVE sync blocks reach per-repo work.
- **Auto-memory (`MEMORY.md`) is git-repo-keyed**, shared across a repo's subdirs/worktrees but
  **not** across sibling repos. So a workspace-root `MEMORY.md` auto-loads only for root sessions;
  the `CLAUDE.md` LIVE blocks are what reach the individual repos. (This is why we mirror the LIVE
  tier into `CLAUDE.md`, not only `MEMORY.md`.)
- HTML comments (`<!-- … -->`) are stripped from `CLAUDE.md` before it enters context, so the
  `BEGIN/END:sync` markers cost nothing and the content between two markers still loads.

## 7. Maintain
The loop after editing shards (see `tooling/README.md`):
```bash
python3 _meta/kb-sync.py       # regenerate MOCs + INDEX + MEMORY.md + CLAUDE.md LIVE blocks
python3 _meta/kb-fix.py        # quote frontmatter values that break Obsidian's strict YAML
python3 _meta/kb-lint.py       # gate: schema valid + no dialect drift + no Obsidian-breakers
python3 _meta/kb-links.py      # gate: broken [[wikilinks]] / dead file refs
python3 _meta/kb-staleness.py  # the re-verify queue: volatile shards overdue for a code re-check
python3 _meta/kb-doctor.py     # is the vault committed, gated and wired? (read-only)
git add _knowledge && git commit -m "kb: <what changed>"   # an uncommitted vault is an unprotected one
```
Append to `log.md` per session. Cap the always-loaded core (~30 items). Keep the taxonomy flat.
**The rule everyone skips is `decays-with-code` re-verification — so `kb-staleness.py` exists to make
that backlog visible; wire it into a pre-session or weekly nudge, and `kb-fix` + `kb-lint` +
`kb-links` + `kb-sync.py --check` into a pre-commit hook.** Put the volatility discipline on a timer, not on willpower.

**Browse it as a database:** the scaffold ships `knowledge-map.base` — open the vault in Obsidian
(1.7+) for filtered table views per `type`. It's purely additive: Obsidian users get the view layer,
everyone else ignores one file, and the plain-markdown core stays greppable/diff-able.

## 8. Update the kit scripts

When a new version of carryover ships, pull updated scripts into `_meta/` without re-scaffolding:

```bash
python3 _meta/kb-update.py          # interactive — shows diff, prompts before each file
python3 _meta/kb-update.py --yes    # silent — 8-second countdown + warning, then overwrites
python3 _meta/kb-update.py --check  # dry-run — shows what would change, exit 1 if updates exist
python3 _meta/kb-update.py --main       # the default branch tip — for tracking development
python3 _meta/kb-update.py --ref v0.5   # pin to an explicit tag, branch or sha
```

**Which ref you get.** By default kb-update pulls the **newest release tag**, not the tip of the
default branch: it lists the remote's tags, keeps the ones shaped like a version (`v0.5`, `0.5`,
`v1.2.3`), and orders them *numerically* — so `v0.10` outranks `v0.9` — then clones that tag. Tags
that aren't plain versions (`-rc1`, `-beta`, anything else) are ignored. If the remote has no
usable tags at all it prints a one-line note and falls back to the default branch rather than
failing. Either way the run header names the ref in use (`target: v0.5 (newest release)`).

Besides the `*.py` scripts it offers the `*.sh` helpers and your `.githooks/pre-commit` (hard or
advisory, whichever you installed), each as a diff. It refuses to move you to an **older** version
than the installed `kb-sync.py` reports, unless you name that ref with `--ref`.

It updates only the top-level `tooling/*.py` scripts copied into `_meta/` — not `hooks/`, not
`kb-eval/`, not the `*.sh` helpers. Your `_knowledge/` vault is never touched. The `kb.version` pin
in `_meta/` is written **only when every offered script was applied** — a partial or declined run
leaves the old pin, and `--check` never writes it at all. See the
[README](README.md#updating-the-kit) for the silent-mode warning.

## Drift smells to avoid (harvested from 5 real vaults)
- **Never hand-write counts or totals** in INDEX/CLAUDE.md — `kb-sync.py` owns them. Hand-written
  "173 shards" goes stale the next commit. `kb-sync.py --check` (wired into the hook, advisory only)
  warns when the files it generates drift from the shards — it does *not* check the `CLAUDE.md` LIVE
  blocks, so re-run a plain `kb-sync.py` to refresh those.
- **Don't leave `updated:` unset** — the kit stamps today's date by default; only override `KB_TODAY`
  for reproducible builds. An `updated: unset` INDEX is a young-vault tell that kills the freshness signal.
- **`KB_SKIP_LINT=1` invites dialect drift** — once the schema gate is off, frontmatter forks into
  incompatible dialects (as one mature vault did). Keep lint on unless you've deliberately left the
  template schema.
- **For `decays-with-code`, git-anchor provenance** — `verified vs main@<sha> DATE` — so re-verification
  can diff against the exact code state, not just a date.

## Gotchas from building a real vault (from ~1.1 GB of transcripts)
- **UUIDv7 session ids share date-ordered prefixes** — hash the *source path* for digest filenames,
  not `id[:8]`, or ~half your sessions silently overwrite each other.
- **Codex and Claude Code JSONL schemas differ** — Codex: `response_item.payload.message`; Claude:
  top-level `type:user/assistant`, `message.content[]`. `prefilter.py` handles both.
- **The giant transcripts are often codebase-analysis runs** whose output already exists as
  distillates — detect (they open with an `AGENTS.md`/analysis preamble) and skip them.
- **A workflow can die mid-synthesis** and only journal some return values — check the on-disk
  result (shard counts, dedup ratios) before assuming it failed or re-running (re-running can
  duplicate).
