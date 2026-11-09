---
title: Research — agent memory design (index)
updated: 2026-07-05
status: durable
---

# Research: how to design agent memory (portable)

Project-agnostic findings from a deep, fact-checked research pass (2026-07-05: 98 agents, 80
falsifiable claims, 3-vote adversarial verification, 21 sources). This is the *why* behind the
`template/` + `tooling/` in this repo. Reuse it for any project's knowledge base.

## Read in this order
1. [[agent-memory-landscape]] — the synthesis + the one-paragraph answer + the design decision.
2. [[karpathy-llm-wiki]] — the "compile, don't re-derive" pattern (primary, verbatim).
3. [[memgpt-letta-tiered-memory]] — the two-tier core/archival model + OS analogy.
4. [[plain-markdown-vs-vector-rag]] — **when you actually need embeddings** (the scale ceiling).
5. [[mempalace-and-what-not-to-adopt]] — the spatial/method-of-loci contrast we reject, and why.
6. [[claims-verified]] — the raw verified-claim corpus (audit trail) + the 7 refuted claims.
7. [[sources]] — every source, primaries first.

Companion page (added 2026-08-27), on the *other* half of the problem — in-session context rather than durable memory:

8. [[agent-context-management]] — offload-plus-pointer, usage-anchored token accounting, cache hygiene on auxiliary calls, pluggable summarization, and a compaction-budget arithmetic trap that silently disables compaction on small-context models.

A convention page (added 2026-11-09) for projects the full git-based kit doesn't fit:

9. [[non-git-design-projects]] — design-tool workspaces with no git: Claude Code memory format, API-gotcha focus, node-ID verification on read, no `log.md` or hook, and naming the active project at session start.

## The takeaway in three lines
- **Build:** a two-tier, plain-markdown, git-versioned, agent-maintained wiki (Karpathy + MemGPT).
- **Skip:** vector/graph/spatial RAG until you exceed ~150–200 pages / ~50–100k tokens.
- **Discipline:** tiny always-loaded core (≤~30 items), everything else browse-on-demand; compile
  once and file answers back; append, don't re-derive.
