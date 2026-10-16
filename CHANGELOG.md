# Changelog

All notable changes to carryover. Versions track `VERSION` in `tooling/kb-sync.py`.

Update an existing install with `python3 _meta/kb-update.py` (see
[Updating the kit](README.md#updating-the-kit)).

## 0.6 — 2026-10-16

Most of this release comes from a health audit of 26 real vaults built with this kit: their
*content* held up well against the code, but the operational layer around it did not — vaults
never committed, gates never wired, a LIVE tier that misreported open work, and a PII guard that
missed the most common leak. `kb-lint` passed on all 26 of them.

**Upgrade notes.**
- After updating, the next `kb-sync` run **changes tracked generated files**: `AGENTS.md`,
  `GEMINI.md`, `.cursor/rules/kb-context.mdc` and `INDEX.md` no longer embed absolute home paths,
  and every MOC/INDEX footer names `python3 _meta/kb-sync.py`. `MEMORY.md` is unaffected. Commit
  that diff.
- `kb.env` is now read by every script. If yours drops platforms (`KB_PLATFORMS=claude,codex`),
  manual runs stop regenerating the dropped files, and `kb-sync` reports any file left behind as an
  orphan — delete it or re-enable the platform.
- `kb-lint` has new **warnings**. They never fail a commit unless you run `KB_STRICT=1`.
- `hooks/pre-push` now **blocks** when it can't find `pii-scan.py` (it used to exit 0 silently).

### Added
- **`tooling/kb-doctor.py`** — checks that a vault is actually *protected*, which no content gate
  does: git repo, HEAD exists, vault tracked, age of uncommitted vault work, remote; gate wired
  (`core.hooksPath` **and** a hook behind it); `_meta/` ignored; `kb.env` not swallowed by a
  `*.env` rule; CLAUDE.md markers; MEMORY.md where Claude Code loads it; and a **rollback**
  heuristic (large net vault deletion vs HEAD, or shards whose `updated:` went backwards — the
  signature of an editor or agent restoring an old snapshot, which a `kb-sync` run would then bake
  into MEMORY.md). `--brief` prints problems only; `kb-session-start.sh` runs it at session start.
  HOWTO gains an explicit *make the first commit, then run the doctor* step.
- **`pii-scan.py` scans commit identities.** A `--range` scan now covers author/committer names and
  emails — what `git log` publishes with every commit, and the usual way a personal address reaches
  a public repo. `@users.noreply.github.com` is allowed.
- **`.pii-allowlist.local`** — project-specific false positives, gitignored, surviving kit updates.
- **`KB_LINKS_IGNORE`** (kb-links) — a regex for link targets that aren't local files, e.g.
  tracker-relative links pasted from an issue tracker, which used to fail the hard gate for good.
- **`KB_LIVE_MAX`** (kb-sync, default 30) — a normal run warns when the LIVE tier outgrows its
  budget, or a LIVE line passes 300 chars.
- **Orphaned-platform-file detection in `kb-sync.py`** — the mirror image of 0.5's collision guard.
  Dropping a platform from `KB_PLATFORMS` stopped kb-sync *writing* its `AGENTS.md` / `GEMINI.md` /
  `.cursor/rules/kb-context.mdc`, but left the file on disk — and, in both supported layouts,
  committed — frozen at the LIVE security findings and open work of the last run. Every agent kept
  reading it, and nothing anywhere said it was stale. kb-sync now names such a file and its platform
  on a normal run **and** under `--check`, so the pre-commit hook's advisory stage surfaces it, with
  the two fixes: delete the file, or re-enable the platform in `KB_PLATFORMS`. It never deletes or
  modifies the file — your git may track it, and deleting a tracked file out from under someone is
  exactly the harm this kit keeps fixing. Ownership reuses the existing anchored-marker test, so a
  same-named file *you* wrote is still a collision, not an orphan, and stays unreported here.
  `MEMORY.md` and `CLAUDE.md` are out of scope. Exit code on a normal run stays 0.

### Changed
- **Every script reads `.githooks/kb.env`** — parsed, never executed; `KB_*` keys only; the
  environment still wins; `KB_ROOT` is ignored there. Before, only the hook sourced it, so manual
  runs ignored `KB_PLATFORMS` and friends.
- **`kb-sync --check` reports three classes** — *stale* (content differs), *missing* (never
  generated) and *older version marker only*. The last is informational and no longer fails: after
  a kit upgrade every generated file used to read "stale" purely because the marker's version
  changed, which buried the real drift.
- **`kb-update`** reads the installed version from `kb-sync.py`'s `VERSION` (the `kb.version` pin is
  only a fallback — pins went stale whenever scripts were copied by hand); **refuses to downgrade**
  to an older release unless you name it with `--ref`; and now also offers the `*.sh` helpers and
  the project's `.githooks/pre-commit` (hard or advisory, whichever is installed), each as a diff.
- **`kb-staleness`** falls back to the project root for anchors when there is no `repos/` (every
  embedded vault was silently skipped), ages `decays-*` shards in `reference/` too, and treats
  `./x.sh` as `x.sh` and a bare `.d.ts` as no anchor at all.
- **`kb-lint` warns** on: shards outside the collections (an `ops/` folder nothing indexes);
  `active` + `one-shot`; an active shard whose `live_summary` says it's resolved; `log.md`
  headings the documented grep can't find; a vault README with unfilled template text or copied
  from the kit's own dogfood vault.
- **`pii-scan`**: `generic-secret-assign` now catches `UPPER_SNAKE_SECRET=` env lines (`\b` never
  fired after `_`) and no longer fires on type annotations or `x = os.environ.get(...)`; a scan of
  **0 tracked files** fails instead of reporting clean; `--full-name` fixes scans from a
  subdirectory, which read the wrong files; the banner no longer asserts the repo is public.
- **`hooks/pre-push`** finds the scanner in `${KB_META:-_meta}/` as well as `tooling/`, and blocks
  the push when neither exists. A push with no new commits (a tag, or a branch at an
  already-pushed commit) is no longer rescanned from the root: with identities now scanned, any
  old leak in history blocked every tag push.
- Generated `AGENTS.md`, `GEMINI.md`, the Cursor rules and `INDEX.md` use root-relative or
  `~`-collapsed paths instead of absolute home paths (they are tracked files; the kit's own
  pii-scan flagged its own output), and generated footers name the real `_meta/kb-sync.py` path.
- `kb-sync.py` `VERSION` is `0.6`.
- `template/` points at the public research note instead of a `../research/` path that only
  resolves inside the kit; `setup/embedded.gitignore` keeps `.githooks/kb.env` tracked under a
  `*.env` rule and ignores `.pii-allowlist.local`.
- **`kb-update.py` updates to the newest *release tag*, not the tip of the default branch.** Once
  v0.5 was tagged, the old clone-the-tip behaviour handed users unreleased mid-development scripts
  while both sides still printed "0.5". It now discovers tags with `git ls-remote --tags --refs`,
  keeps only version-shaped names (an optional leading `v`, then a dotted numeric version), orders
  them by **numeric tuple** — so `v0.10` ranks above `v0.9`, never a lexical sort — and clones that
  tag; `-rc`/`-beta`/arbitrary tags are ignored. `--main` restores the old behaviour for people
  tracking development, and `--ref <REF>` pins to an explicit tag, branch or sha. A remote with no
  usable tags falls back to the default branch with a one-line note (not an error); a failing
  `git ls-remote` prints the error and exits 2 rather than silently updating you from an unintended
  ref. The run header names the ref in use. Exit codes, `--check`'s read-only guarantee, and the
  "pin written only when every offered script was applied" rule are unchanged.
- **Renamed: `kb-template` → `carryover`.** `kb-template` implied GitHub's *template repository*
  feature ("Use this template"), which this repo is not — you copy directories out of it. The new
  name is what the kit actually does: carry knowledge over between agent sessions.
  GitHub redirects both former names, and `git clone` **and** `git ls-remote` were verified through
  the redirect, so `kb-update.py` in an existing `_meta/` keeps working without any action. Update
  it at your leisure and `REPO_URL` moves to the new address.

### Fixed
- **`kb-sync.py --help` regenerated everything.** kb-sync ignored unknown arguments, so `--help` (or
  any typo) ran a full write; run outside a project it scaffolded MOCs, platform files and a Claude
  memory dir out of nothing. Unknown flags now exit 2, `--help` prints usage, and a missing vault
  exits 2 — nothing written in any of those cases.

## 0.5 — 2026-08-27

First tagged release, and the first since the kit went public under MIT.

### Added
- **`tooling/kb-update.py`** — pull new kit versions into an existing `_meta/` without
  re-scaffolding. Interactive by default (per-file diff, `[y]es/[n]o/[a]ll/[q]uit`), `--yes`
  for silent apply, `--check` for a read-only dry run. Writes a `kb.version` pin.
- **`setup/`** — ready `.gitignore` files for the two supported layouts:
  `workspace.gitignore` (one vault, many repos under `repos/`) and `embedded.gitignore`
  (vault inside an existing project repo).
- **Collision guard in `kb-sync.py`** — `AGENTS.md`, `GEMINI.md` and
  `.cursor/rules/kb-context.mdc` are no longer overwritten when they exist but were not
  generated by kb-sync. It warns, skips the file, and continues. A hand-written root
  `AGENTS.md` is safe.
- **Missing-`CLAUDE.md` warning** — `kb-sync.py` used to return silently when no
  `CLAUDE.md` existed, so the always-loaded LIVE tier was never wired while every gate
  still printed green. It now says so.
- **Git commit history as a first-class init source** — `AGENTS.md` and `HOWTO.md` now mine
  commit history before transcripts (free, no LLM tokens), with the commit-message patterns
  that map to gotcha / decision / architecture shards.
- `CHANGELOG.md` (this file).

### Changed
- `VERSION` 0.4 → 0.5. The generated-file marker embeds the version, so the first `kb-sync`
  run after updating rewrites generated navigation. This is expected; `kb-sync --check` will
  report drift until you re-run it once.
- **Behaviour change — the `CLAUDE.md` LIVE blocks are now gated on the `claude` platform.**
  `MEMORY.md` was already gated by `KB_PLATFORMS`, but the `<!-- BEGIN:sync:* -->` blocks were
  filled in unconditionally, so a `KB_PLATFORMS=cursor` run still rewrote `CLAUDE.md` — a file the
  user had told the tool not to touch. Both halves of the `claude` platform now move together. If
  you dropped `claude` from `KB_PLATFORMS` and still relied on the LIVE blocks being filled in,
  add it back.

### Fixed
- **A resolved security finding was reported as OPEN in the always-loaded tier — and a genuinely
  open one could be hidden.** The `🔴 LIVE — open security findings` block (in `MEMORY.md`, the
  `CLAUDE.md` LIVE block, `AGENTS.md`, `GEMINI.md` and the Cursor rules) filtered on `volatility`
  alone, so any `decays-with-code` shard appeared under it regardless of `status`. Every agent
  reading the core tier at session start was told a patched vulnerability was live. An open finding
  now requires **both** `status: active` **and** `volatility: decays-with-code`; standing rules
  (`durable`) stay out of the LIVE block, which is what keeps the core tier small. The `security/`
  MOC still groups by volatility — its heading says `(decays-with-code)` rather than claiming
  "open". Tagging guidance added to `template/README.md`.
  *Correction (0.6): this fix landed after the `v0.5` tag was cut, so the tagged 0.5 release does
  not contain it — install 0.6, or `kb-update.py --main` until it is tagged.*
- **kb-sync's two `CLAUDE.md` warnings pointed at "HOWTO §6", a file no install path puts in a
  user's project.** They now link to the published Quick start.
- **The collision guard clobbered a hand-written file that merely mentioned the marker.**
  Ownership was a plain substring test, so a contributor guide with the words *generated by
  kb-sync.py* in prose counted as kb-sync's own output and was overwritten. Ownership is now an
  anchored HTML comment at the start of a line within the first 10 lines (the deepest real marker
  sits at line 8, behind the `.mdc` frontmatter); an unreadable file is treated as the user's and
  skipped.
- **`KB_PLATFORMS` / `KB_AREAS` now tolerate whitespace.** `KB_PLATFORMS="claude, gemini"` was
  split on commas only, so `" gemini"` never matched and `GEMINI.md` was silently never written —
  while the closing `Platforms:` line still listed gemini as active. Items are now stripped and
  empty ones dropped.
- **`Ctrl+C` during `kb-update.py`** raised a `KeyboardInterrupt` traceback out of a tool that had
  been overwriting executable scripts. It now reports how many scripts were applied and what the
  version pin was left at, and exits 1.
- **`MEMORY.md` shown as a `../../../..` chain.** It lives outside the project root, so the
  relative path kb-sync printed (and `--check` reported) read like a path-traversal bug. Paths
  outside the root are now shown `~`-collapsed, or absolute when they also fall outside `$HOME`.
- **Hand-merge advice for a collision-guard skip removed — it destroyed data.** The docs told
  users to paste the generated block into their own `AGENTS.md`/`GEMINI.md` by hand. The block
  starts with the ownership marker, so pasting it in makes kb-sync consider the file its own and
  overwrite it on the next run. The documented remedy everywhere is now: rename or move your file,
  or drop that platform from `KB_PLATFORMS`.
- **The hook-install symlink is guarded.** The bare `ln -sf … .git/hooks/pre-commit` offered as the
  "safe alternative" to `core.hooksPath` silently destroyed whatever pre-commit hook the project
  already had. The documented form now refuses to clobber, and where a hook already exists the
  docs say to *chain* the KB gate from it instead.
- **Install commands unified** across `README.md`, `HOWTO.md` and `tooling/README.md`: always clone
  into a fresh `$(mktemp -d)`, `mkdir -p` the `_meta/` dir first, and copy both `tooling/*.py` and
  `tooling/*.sh`. HOWTO still used a fixed `/tmp/kb-template` — one clone plus five paths derived
  from it.
- **The collaborator install was undocumented.** `_meta/` is gitignored and `core.hooksPath` is
  per-clone local config, so a teammate who clones a project with an embedded KB gets no tooling
  and no gate — and their ungated commits can land an invalid shard that then blocks everyone
  else's commits. The one-time per-contributor install is now written down.
- `kb-update.py` crashed with an unhandled `EOFError` on non-tty stdin *after* partially
  overwriting scripts. It now refuses to start without a terminal (exit 3) and points at
  `--yes` / `--check`.
- `kb-update.py --check`, documented as a dry run, wrote `kb.version`. It is now strictly
  read-only.
- `kb-update.py` silently ignored unknown flags, so `--dry-run` ran a real interactive apply.
  Unknown flags now exit 2 with usage; `--dry-run` / `-n` are aliases for `--check`.
- `kb-update.py` wrote the full remote version to `kb.version` after a partial apply, so the
  pin described a state the directory was not in. The pin is now written only when every
  offered script was applied.
- `setup/embedded.gitignore` — the kb-eval results pattern used a `..` path that git never
  matches, so eval output was not ignored at all; it also omitted `_knowledge/.obsidian/`,
  committing per-machine Obsidian UI state. Both fixed, and the file now starts with a blank
  line so the documented `cat … >> .gitignore` can't fuse onto a last rule lacking a newline.
- `setup/workspace.gitignore` — the `/*` whitelist ignored `AGENTS.md`, `GEMINI.md` and
  `.cursor/`, the exact files HOWTO says to commit. They are now tracked; `.cursor/mcp.json`
  stays ignored since it can hold API tokens.
- **`export` trap** — `tooling/README.md` documented `KB_VOLATILITY="…"` in `kb.env` without
  `export`. The hook sources `kb.env` and then runs the scripts as child processes, so a
  non-exported var never reaches them and the gate rejected the exact value the config
  permitted. Documented correctly, with the full list of vars that must be exported.
- `KB_PLATFORMS` was documented as configurable via `.githooks/kb.env`, which never affected
  a writing `kb-sync` run. Docs now describe what actually works.
- The README quick start never created `CLAUDE.md`, so the LIVE tier was never wired. It now
  does, idempotently.
- `git config core.hooksPath .githooks` silently disables every hook a project already had.
  Both README and HOWTO now warn about it.
- The documented `git clone … /tmp/kb-template` failed on any machine where that path
  existed and then silently installed the stale clone. Docs now clone into `$(mktemp -d)`.
- `AGENTS.md` linked to a README anchor removed in the previous docs rewrite.
- The AGENTS.md git-mining command labelled "files that change together" computed no such
  thing and emitted a blank top row. Relabelled as hot-spot frequency and the blank line
  filtered.
- HOWTO's `prefilter.py` invocation used a path that does not exist in a user project and an
  output directory name that was not gitignored.
- `tooling/README.md` described the pre-commit hook as three stages; it runs four (the fourth
  being the advisory `kb-sync --check`). `pii-scan.py` and `kb-session-start.sh` were shipped
  but undocumented and, for the `.sh`, uninstallable by any documented path.
- `tooling/kb-eval/` quoted a cost for a trap count matching neither the shipped file nor the
  published result.
- Leftover proprietary-era wording in `tooling/kb-eval/sample-report.md` that the MIT flip
  missed.

## 0.4 — 2026-08-12

### Added
- Multi-platform context generation from one vault, controlled by `KB_PLATFORMS`: adds
  `GEMINI.md` (Antigravity) and `.cursor/rules/kb-context.mdc` (Cursor) alongside the `AGENTS.md`
  that shipped in 0.3 and the Claude Code `MEMORY.md` + `CLAUDE.md` LIVE blocks. The three
  non-Claude files share one body builder, so they carry identical LIVE content.

## 0.3 — 2026-08-12

### Added
- **`AGENTS.md` generation** — a project-root agent quick-start carrying the same LIVE content as
  `MEMORY.md`, for the tools that read `AGENTS.md` instead of Claude Code's memory dir.
- `tooling/kb-session-start.sh` — SessionStart hook printing active gotchas and open tasks.
- `live_summary:` frontmatter field, used in LIVE blocks in place of `title:` when present.
- `verify:` frontmatter field.
- Pre-commit code-path nudge via `KB_CODE_PATHS` — reminds about a `log.md` entry when
  watched code paths change, without blocking.

### Fixed
- Off-by-one in the shard count (the architecture page was omitted).
- `kb-fix` re-staging swept unrelated unstaged hunks of `git add -p`'d files into the commit.
- Startup integrity check for phantom tooling paths referenced by `MEMORY.md`.

## 0.2

- Obsidian-safe frontmatter repair (`kb-fix.py`), schema gate (`kb-lint.py`), link-rot gate
  (`kb-links.py`), staleness queue (`kb-staleness.py`), transcript prefilter, impact eval.
