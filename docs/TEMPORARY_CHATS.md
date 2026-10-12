# Temporary chats and forgetting history (0.1.6)

For a new temporary chat, start your first user message with **`[temp]`** or
**`[temporary]`**, followed by a space and your question. For example:

> [temp] Why is the sky blue?

This works through native Codex/Claude and saved VM T3 events, including Grok.
It does not depend on a model obeying an instruction. The client preflights native
files for the explicit user-message prefix; the server independently checks it.
Assistant replies, quoted examples, tool results and chat titles cannot opt out.
The chat can still look up existing memory; its conversation is not archived.
Once excluded, later messages stay excluded even without the marker. A marker
added later also removes material already captured from that chat. Start with it
for a chat whose question/answer should never enter Agent Hub. T3 may create a
metadata-only thread record before the first user message; it is removed when
that message establishes the exclusion.

To remove a saved chat, open Agent Hub's **Captured sessions**, choose **Inspect
session**, then **Forget this chat**. Connect with your private administrator
credential to see this action. Confirm the displayed client, computer and source
session ID. **Make temporary** is also available for an already captured chat.
Both remove the live copy and permanently suppress capture of those identities.
There is no undo switch in this release; forgetting cannot be downgraded to
ordinary or temporary capture. Native harnesses do not receive administrator
credentials or an automatically approved deletion tool.

## What gets removed and what remains

Forgetting removes the session metadata, original events, raw record strings,
search entries and every note citing one of those events. It rebuilds the whole
project's summary tree so summaries that used earlier context do not retain the
removed content. Surviving event IDs and sequence positions are unchanged;
content-free gap markers preserve the tree's navigation. Stale model-worker
summary/extraction completions are rejected using a privacy revision.

A separate private SQLite exclusion ledger stores hashed session identities,
project, mode and proven relationships, without chat text, titles or prompts.
The server records policy durably before purging. The ledger survives an archive
restore and is replayed before the service opens. Lost upload acknowledgements,
queue retries, deleted checkpoints and historical backfill cannot bypass it.
Persistent offline memory caches are cleared and no longer used. When the memory
service is unavailable, startup hooks inject no cached historical content.

Native Codex JSONL and its app-server export are linked by their native ID.
On the T3 execution host, configure `t3_database` (or `configure --t3-database`)
to link T3 and native provider IDs. The adapter reads only `thread_id`,
`provider_name`, and `resume_cursor_json`'s `threadId` from T3 0.0.45's
`provider_session_runtime`. It never imports the rest of that cursor, runtime
payloads, auth tables or credentials. Missing/changed identity schema retains
linked uploads for retry instead of silently dropping this protection.

Relationships stay separate from immutable archived provenance. Matching text
or timestamps never links chats. Known child sessions inherit a parent's
exclusion; forgetting a child does not forget its parent or siblings. Supported
parent identities are Claude native subagent metadata and Codex JSONL
`session_meta.parent_thread_id`. Earlier provider sessions whose IDs T3 has
already discarded cannot be guessed; independently imported copies with a new
computer/session identity require their own explicit exclusion. A provider's
external artifacts or an unknown child format are not a complete subagent archive.

Agent Hub does not delete native Codex/Claude/T3 files, model conversations already
loaded into a harness, manually copied notes without source links, or old backups.
SQLite secure deletion and FTS merging are used, but this is not a claim of
forensic erasure from disks, snapshots or provider infrastructure. Older backup
bytes remain until a separate, explicitly chosen retention/removal operation.

## Backup and restore

Every new archive backup includes a `.privacy.sqlite3` companion. Preserve the
**current** live exclusion ledger separately from older archives. Restore requires
`--privacy-ledger` pointing to the current ledger, even when restoring an older
archive. Never roll the ledger back to the date of that archive. For example:

```sh
agent-hub restore --data-dir /private/new-empty-server \
  --source /private/backups/old-memory.sqlite3 \
  --privacy-ledger /private/current/memory.sqlite3.privacy.sqlite3
```

Restore copies the selected current ledger and applies exclusions before reporting
success. It refuses an existing server/data directory or existing target ledger.
Then initialize fresh credentials, as described in the server guide. Loss of all
current ledger copies also loses knowledge of newer exclusions; an old backup
alone cannot reconstruct later user choices.

## Historical backfill

Old unchanged files may have been baselined by `scripts/watch-local.py` without
being imported. A successful memory lookup is not proof that an older chat was
captured. Explicitly queue the configured Codex and Claude roots to backfill them.
The same privacy checks apply to live capture and backfill. Files over 16 MB are
preflighted and uploaded in bounded chunks, preserving original raw strings,
global line ordinals and event IDs. Resume checkpoints use acknowledged prefix
hashes; malformed, changed and unsupported files remain visible for review.

The event contract accepts up to 64 MiB of raw text per record. The home server
uses a 64 MiB HTTP body cap to accommodate existing image-bearing records; other
servers keep their configured cap. Larger records or requests fail visibly and
are never silently truncated. Raw image bytes embedded in native JSON are kept;
external attachment files are not copied. Backfill can require substantial disk
space and make subsequent full backups larger.

For full backfill, run `scripts/backfill-local.py` with your private client profile
and explicit native roots. It queues all selected files in the durable outbox;
the existing watcher drains them. `--prioritize-session` lets one missing chat go
first. On a Codex desktop host, configure `codex_database` to its verified local
state SQLite file. After native capture, names are indexed as a separate
attributed metadata stream with an exact pointer to the archived native session.
The name stream belongs to that native session's exclusion group; a temporary
or forgotten chat cannot leak through a title import. This reads only the
`threads` projection's id, name, title and rollout path, not credentials or
provider runtime data. Database schema changes stop the name update visibly.
