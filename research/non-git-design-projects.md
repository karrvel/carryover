---
title: Non-git design projects — a minimal knowledge convention
updated: 2026-11-09
provenance: derived from the kit's health audit of real vaults, where a design-tool workspace forced into the full git convention went stale and some of its shards ended up describing a different codebase; memory keying as documented in HOWTO.md (loading semantics). A convention, not a benchmark.
status: durable
---

# Non-git design projects — a minimal convention

The kit's full convention leans on git at every step: commits anchor staleness (`verified vs main@<sha>`), `log.md` entries pair with PRs, a pre-commit hook gates every shard, and init starts by mining `git log`. A project whose source of truth is a design tool — Figma, Miro, Pencil `.pen` files, a whiteboard — has none of that. There is no commit to anchor to and no PR to log against, and often no repo at all. Forcing the full ceremony on it produces a vault nobody maintains, which then drifts into fiction.

This is the smaller convention that holds up there. Use it when the agent works *through the tool* (reading frames, nodes and components via an API or MCP server) rather than editing files in a repo. If part of the project is a git repo — a design-system package, a front-end — use the full kit for that part and this convention only for the design-tool side.

## The four rules

**1. Claude Code memory format, not a vault.** Use the agent's own memory directory: a `MEMORY.md` index with one line per note (`- [Title](file.md) — one-line hook`) and one small markdown file per fact. Give each note a short frontmatter (`name`, `description`, `type`) and a body that states the rule first, then *why* and *how to apply it*. No `_knowledge/` tree, no INDEX or MOCs, no kb-sync. Agents other than Claude Code get the same shape in any folder they read at session start. If the project later gains a git repo, each note promotes cleanly into a shard.

**2. Write down the tool, not the design.** The design is already the source of truth, and the agent can read it live. Copying colours, copy text or layout into memory only creates a second, staler copy. What the agent *cannot* re-derive is how the tool behaves, so that is what memory is for: which API calls are read-only and which mutate, rate limits, auth scopes, what happens to node IDs on duplicate or copy-paste, export settings that silently differ from the UI, and plugin or MCP quirks. Most notes in a healthy design-project memory are API gotchas.

**3. Verify node IDs on read; never trust them from memory.** A note that names a specific frame, component or node is a pointer, and pointers rot: nodes get deleted, duplicated, re-parented, or the file is branched. Store the node's **name and type next to its ID**, and before acting on a remembered ID, fetch it and check that both still match. If the ID doesn't resolve or the name differs, the note is stale: find the node by name, then fix or delete the note. This replaces git-anchored staleness, so verification happens on every read instead of on a schedule.

**4. No `log.md` ceremony, no hook.** There is no commit to gate and no PR to pair a log entry with, so skip `log.md`, the pre-commit hook, kb-lint and kb-staleness. Date-stamp a note when you verify it (`verified 2026-03-24 against <file name>`). Delete a note that fails verification instead of keeping its history.

## Name the active project

Memory follows the repo root (or the folder the agent starts in), not the file you have open — see HOWTO.md, *Loading semantics*. A design workspace often holds several projects in one folder, so one memory directory serves all of them, and facts about project A surface while you work on project B. No tooling can re-key this. So:

- **Say which project you are on at session start.** For example: "working on the onboarding redesign; ignore notes about other projects".
- **Prefix note filenames with a project slug** (`onboarding-…`, `billing-…`), so mixed memory is at least visibly mixed.
- **Give each project its own folder when you can.** That is the only real fix.

## What you give up

- **No staleness clock.** Verification on read only catches drift in what you actually read. A note nobody reads can rot unseen, so keep memory small.
- **No review trail.** A memory directory outside any repo isn't committed, so back it up the way you back up the design files.
- **No schema gate.** Nothing lints the notes; keep the format simple enough not to need it.

When the project gains a git repo, move to the full kit: copy the notes into `_knowledge/` as shards (mostly `type: gotcha`) and start the normal maintenance loop.
