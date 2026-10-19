# Agent Hub 0.1.9

Bug fixes found by comparing Agent Hub with the source of UniiChat (github.com/VictorTaelin/UniiChat, commit 0500bf6, read on 19 October 2026). No archived record, identity or normalized text changes.

**Startup context covers all history.** The context pack used a fixed 32-node view written newest first until the budget ran out, so at the 8,000-character startup size it held only the last ~15 records of a 1,000-record project. It now starts from the tree's roots (every record covered once) and adds detail for recent spans while it fits. It also stays under 140,000 UTF-8 bytes, so multi-byte text can no longer make the call fail.

**The summary worker cannot stall.** One record whose answer was always rejected (over 512 bytes after shortening, an incomplete or empty reply, unusable extraction JSON) stopped every later summary or extraction on every run while spending calls. A rejected answer is now retried once on a later run; a second rejection blocks only that item. Extraction JSON wrapped in a Markdown code fence is accepted. Provider and network failures still stop the run for a later retry.

**Oversized records no longer freeze the tree above them.** A record over the 24,000-character worker input kept every ancestor as a head-and-tail excerpt forever. A blocked node now keeps its labelled excerpt as final and its ancestors are summarized over it, with that part marked as an excerpt. Preceding context is trimmed to fit (keeping the newest part) instead of blocking a record that fits on its own. Provider usage is recorded even when an answer is rejected.

**Excerpts show both ends.** Deterministic excerpts kept only the beginning of each half, so a span never showed its last record and a long tool output never showed its result. They now keep the start of the first part and the end of the last. Existing excerpts change only after `agent-hub rebuild`.

**`[temp]` while Claude Code is busy.** A prompt typed during a running turn is saved as a queued-command attachment, which the temporary-chat check did not read. It now does, on both the client and the server.

**Backfill order.** Upload jobs ran in hash order, so a backfill entered old sessions in random order. Jobs now run in the order queued, and discovered transcripts are queued oldest first.

**Docs.** The forgetting guide now states that a model summary of a later record may have copied a detail from a forgotten chat via its context, and how to remove that. The spec no longer describes the offline context cache removed in 0.1.6.
