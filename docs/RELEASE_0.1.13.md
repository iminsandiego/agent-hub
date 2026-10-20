# Agent Hub 0.1.13

Small follow-ups to 0.1.12. No archived record, identity or normalized text changes.

**A matching chat brings its latest answer.** The first-prompt matches now list each matching chat's records together, followed by the start of that chat's latest assistant message, which is usually where the work ended up. On 20 broad questions about two weeks of the home archive ("where did we land on…", "what is still open…"), answered by Sonnet 5.5 from the injected text only, the share of key points covered rose from 15.8% to 23.5%; fact recall on the 25-question set stayed 24/25.

**Setup keeps Codex tool approvals.** `agent-hub setup` compares and updates only the launch keys it manages in an existing `agent-hub` MCP entry (`command`, `args`, `env_vars`, `url`, `bearer_token_env_var`, `type`, `headers`). Codex's per-tool `approval_mode` entries and other settings are kept; a changed launch command is still a conflict.

**Harness notices are not the first prompt.** A turn the harness submits for itself (a background-task notification, a system reminder) gets no matching history and does not use up the session's first prompt.

**Quoted control tags.** The summary worker rejects an answer that is only a control tag, not a summary that quotes one from the records it summarizes.
