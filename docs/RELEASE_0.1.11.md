# Agent Hub 0.1.11

Capture jobs whose source does not exist stop retrying forever. No archived record, identity or normalized text changes, and the server is unchanged.

**Jobs for a missing source are set aside after a day.** Hooks queue the transcript path or Codex thread a session reports. Some sessions never save one: Claude Code subagents and non-interactive runs that write no transcript, and Codex background threads the app-server answers with "thread not loaded". Their jobs were retried every five minutes indefinitely: on the home Mac 124 jobs had over 2,000 attempts each, and `doctor` listed them as errors that hid real ones. The watcher's scan history showed none of those transcripts had ever been on disk.

A missing transcript, or a Codex "thread not loaded" answer, now marks the job's source as gone. After 24 hours with the source still gone, the job is set aside: kept in the outbox, not retried, not counted in `pending_jobs` or `errors`, and counted under `source_gone` in `doctor`. Any other failure restarts the 24 hours; new work for the same source (a changed file or another hook) brings it back. Other Codex app-server errors are reported as before. The outbox gains two columns on first open; jobs queued earlier start their 24 hours at their next attempt.

**`agent-hub queue`.** `queue list` shows set-aside jobs with their path or thread ID; `queue requeue ID…` or `queue requeue --all` returns them to the queue.
