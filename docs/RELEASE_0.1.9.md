# Agent Hub 0.1.9

Bug fixes found by comparing Agent Hub with the source of UniiChat (github.com/VictorTaelin/UniiChat, commit 0500bf6, read on 19 October 2026). No archived record, identity or normalized text changes.

**Startup context covers all history.** The context pack used a fixed 32-node view written newest first until the budget ran out, so at the 8,000-character startup size it held only the last ~15 records of a 1,000-record project. It now starts from the tree's roots (every record covered once) and adds detail for recent spans while it fits. It also stays under 140,000 UTF-8 bytes, so multi-byte text can no longer make the call fail.

**The summary worker cannot stall.** One record whose answer was always rejected (over 512 bytes after shortening, an incomplete or empty reply, unusable extraction JSON) stopped every later summary or extraction on every run while spending calls. A rejected answer is now retried once on a later run; a second rejection blocks only that item. Extraction JSON wrapped in a Markdown code fence is accepted. Provider and network failures still stop the run for a later retry.

**Oversized records no longer freeze the tree above them.** A record over the 24,000-character worker input kept every ancestor as a head-and-tail excerpt forever. A blocked node now keeps its labelled excerpt as final and its ancestors are summarized over it, with that part marked as an excerpt. Preceding context is trimmed to fit (keeping the newest part) instead of blocking a record that fits on its own. Provider usage is recorded even when an answer is rejected.

**Excerpts show both ends.** Deterministic excerpts kept only the beginning of each half, so a span never showed its last record and a long tool output never showed its result. They now keep the start of the first part and the end of the last. Existing excerpts change only after `agent-hub rebuild`.

**`[temp]` while Claude Code is busy.** A prompt typed during a running turn is saved as a queued-command attachment, which the temporary-chat check did not read. It now does, on both the client and the server.

**Backfill order.** Upload jobs ran in hash order, so a backfill entered old sessions in random order. Jobs now run in the order queued, and discovered transcripts are queued oldest first.

**Put history in time order.** `agent-hub reorder --project P` reports, and `--apply` performs, a renumbering of a project's records by source time (carried forward within each session, so no session's own order changes), closing forgotten-chat gaps and rebuilding the tree. IDs, raw records, notes and search are unchanged; worker checkpoints are translated. Use it once after a backfill.

**Dated, compact context.** The context pack is one line per record: `note <id> | kind | sources | statement`, or `lo+n | dates | text` for a span, history oldest first, so an agent sees when each part happened. Line breaks inside records are flattened, so captured text cannot start a line and pose as a note or instruction. About twice as much history fits. Query matches may use at most half of the remaining budget.

**Zoom by `lo+n`.** `memory_zoom` accepts span references such as `1024+512` (or `37+1` for one record); search hits and context lines carry them, so an agent can move from a hit to the history around it. A malformed reference is refused with the tree's top references.

**Better summaries.** A merge also receives finer lines for its own records (`SPAN DETAIL`), not only its two halves. The prompt, adapted from UniiChat's, ranks what to keep (the user's words first, tool steps last), asks for exact names, ids, paths and errors, and shows a 512-character ruler; a too-long answer is shown exactly where the limit cuts it.

**Capture parser version 2 for new sessions.** Codex's duplicate event copies of messages become placeholders; injected `AGENTS.md`/environment blocks are no longer tagged as the user's words; `apply_patch` inputs, shell commands and search queries become searchable; Claude Code meta and compaction summaries become `system`, subagent prompts `assistant`, queued prompts `user` and command output `tool`. Sessions captured earlier keep version 1, and a lost checkpoint falls back to it automatically, so archived records never conflict. A moved or archived transcript no longer conflicts on its path.

**Stricter forgetting.** Forgetting a chat also resets model-written summaries of later records that were written while it was archived (they may have copied a detail from it through their context); they are summarized again by later worker runs. With the worker never enabled this changes nothing.

**Docs.** The spec no longer describes the offline context cache removed in 0.1.6.
