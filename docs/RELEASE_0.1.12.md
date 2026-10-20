# Agent Hub 0.1.12

What a new chat learns from its history. Archived conversation records are unchanged; the server stops archiving records that have no content of their own, and `agent-hub prune` removes those captured earlier (a report first, `--apply` after a backup).

**The archive was mostly bookkeeping.** In the home archive (501,895 records, 5.9 GB of record text and raw source), conversation was 16,796 records and 196 MB. Bookkeeping (Codex status events and their copies of every item, compaction snapshots, Claude Code request copies, UI state, empty records) was 3.4 GB, and Codex's approval-reviewer ("guardian") threads, 782 of them, repeated the conversation in another 0.7 GB. The 8,000-character startup context a new chat received was almost entirely event markers, token counts and tool output.

**Record classes.** `classify.py` sorts records into conversation, tool, injected, derived, title, metadata and bookkeeping, from the stored role, text and raw source; `agent-hub rebuild` applies it to an existing archive. Only the conversation appears in the tree's excerpts and the history view. Search excludes bookkeeping and metadata, ranks injected text and derived threads after the conversation, weights tool records slightly down, drops common words from a query and centers each excerpt on its match.

**No more noise at ingest.** The server discards bookkeeping records and does not archive approval-reviewer threads; an excluded thread is remembered, so its later batches and a replay after a lost checkpoint stay out. Records of a type no parser reads yet are still archived for a future parser. `agent-hub prune` removes both from an earlier archive, unless a note cites them, renumbers positions as `reorder` does, rebuilds the tree and runs `VACUUM` (home archive: 341,570 records and 4.2 GB removed; 8.1 GB to 2.55 GB).

**Startup context names the recent chats.** The pack gains a recent-chats section, newest first: each line starts at the chat's opening request and gives its dates, client and title (Claude Code's own or Codex's thread name) or request. `sections` selects notes, matches, chats and history.

**The first prompt brings matching history.** A `UserPromptSubmit` hook searches the first prompt of each session and adds up to 9,500 characters of matching records, at most two per chat, each naming its chat (0.1–0.3 s on the home archive). Later prompts add nothing; an outage adds nothing rather than delaying the prompt. Run `agent-hub setup` again to install it.

**Hook limits, measured.** Claude Code delivers at most 10,000 characters of one hook's context; Codex counts `additionalContextLimit` in tokens (about 2,500 by default, keeping both ends past it). Startup and first-prompt context are each capped at 9,500 characters, and setup gives Codex a 4,000-token limit (it was 2,500).

**Summary worker.** A summary that fits the byte limit but is mostly punctuation, contains the length ruler or a control tag is rejected (seen from a small model in a trial). The worker remains off by default; see VALIDATION.md for the model trial and a dry-run usage estimate.

Upgrade: install, restart the server, run `agent-hub rebuild --project P`, then `agent-hub setup` on each computer; back up and run `agent-hub prune --project P` to see what would be removed before `--apply`.
