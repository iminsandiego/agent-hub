# Operate and extend Agent Hub

For a native Python installation, run the commands below with its virtual environment active (`source "$HOME/agent-hub/.venv/bin/activate"` on Linux/macOS), or use the absolute path to that environment's `agent-hub` executable. For Docker, replace the leading `agent-hub` with `docker compose -f deploy/compose.yaml exec memory agent-hub` and use `/data` for the server data directory. Backup source/output paths must also refer to accessible container paths. See [server setup](SERVER_SETUP.md).

## Storage to protect

The server data directory holds `memory.sqlite3` (captured originals, search index, summaries, memory records and review history), `auth.sqlite3` (credential digests/scopes/revocation), and `worker.sqlite3` (enrichment checkpoints and call observations). Runtime JSON settings and token files are outside the repository. SQLite WAL files can exist while processes are running.

Use a local persistent disk. Do not place the live SQLite database on SMB/NFS or synchronize it through Git/Dropbox-style file replication. Multiple computers use the authenticated service API. The app does not encrypt the database itself; disk and backup protection are host responsibilities.

The watcher has a separate local queue/checkpoint database on each execution host; the same local state also holds startup context cached by successful hook or `context` requests. The watcher does not refresh that cache. Losing local state can require replay of selected sources; stable identities deduplicate identical records. Losing the original local transcript before it is uploaded cannot be repaired by a queue containing only its path or thread ID. Keep the watcher running and monitor errors.

## Status and review

The browser provides project statistics, bounded startup context, source search, sessions, tree navigation, and note review. Source content is rendered as text. A candidate can be activated or rejected with an administrative credential; it can explicitly supersede a previous active note. Normal agent tokens cannot review notes.

Equivalent local operations:

```bash
agent-hub project list --data-dir "$HOME/.local/share/agent-hub"
agent-hub review --data-dir "$HOME/.local/share/agent-hub" --project atlas --id MEMORY_ID --status active
agent-hub review --data-dir "$HOME/.local/share/agent-hub" --project atlas --id REPLACEMENT_MEMORY_ID --status active --supersedes OLD_MEMORY_ID
agent-hub review --data-dir "$HOME/.local/share/agent-hub" --project atlas --id MEMORY_ID --status rejected
```

`MEMORY_ID` means the actual identifier returned by a note/search/detail operation. No example implies a real requirement or executed test. Superseded notes are retained as historical records, but they no longer populate the current active-note section. A historical source may still describe an earlier, now-rejected approach.

## Backups and restoration

Create a memory snapshot with the SQLite online backup API:

```bash
agent-hub backup --data-dir "$HOME/.local/share/agent-hub" --output "$HOME/backups/agent-hub-2026-10-07.sqlite3"
```

The command refuses an existing destination through the CLI, writes a temporary snapshot, verifies it, and replaces the intended new destination atomically. Original events, FTS data, notes, evidence relationships, reviews, and summary nodes are included. Do not copy only the live main database file while ignoring an active WAL.

For a first restore test, use a new directory:

```bash
agent-hub restore --source "$HOME/backups/agent-hub-2026-10-07.sqlite3" --data-dir "$HOME/.local/share/agent-hub-restore-test"
agent-hub init-server --data-dir "$HOME/.local/share/agent-hub-restore-test" --project atlas
agent-hub project list --data-dir "$HOME/.local/share/agent-hub-restore-test"
```

The restore retains all archived projects; `init-server` adds any explicitly requested missing project and provisions fresh credentials. It does not replace existing memory. The target must not contain a memory/auth database, `server.json`, or `admin.token`; use a new directory to avoid mixing unrelated runtime state. Start a restore-test instance on a different port if the original is running.

This command backs up memory only. To recover tokens/settings/worker state as well, perform a protected filesystem snapshot of the entire data directory with the services stopped, or back up each SQLite database with its backup API. A memory-only restore intentionally requires fresh credentials; raw token files should not be casually distributed with backups.

## Token lifecycle

```bash
agent-hub token list --data-dir "$HOME/.local/share/agent-hub"
agent-hub token revoke --data-dir "$HOME/.local/share/agent-hub" --id TOKEN_IDENTIFIER
```

Listing returns identifiers, names, scopes and lifecycle metadata, never secrets. Revocation takes effect on the next request. Issue a new scoped credential and update only the intended computer to rotate it. If a computer can access both personal and work projects, assign that intentionally; retrieval never adds an implicit global project.

## Capture failures and recovery

| Condition | Behavior | Action |
| --- | --- | --- |
| Service unavailable | Upload remains pending with retry state | Restore connectivity and let the watcher retry |
| Missing project mapping | No broad fallback upload | Add the intended mapping or explicitly assign the import |
| Partial last JSONL line | Wait for completion | Leave the growing file intact; use the documented final-import flag only for a completed source |
| Malformed complete line | Report exact parsing failure; do not advance past it | Preserve original; repair through an explicit copy/import decision |
| Source truncated or prefix rewritten | Checksum conflict; no silent replacement | Investigate native migration/rotation; use an explicit new stream identity when appropriate |
| Same event ID has different normalized/raw content | Entire server batch rejected | Check adapter version, source format and identity; do not edit the archived row |
| Unknown vendor record type | Raw record preserved; normalization limitation visible | Extend the versioned adapter using a captured fixture |
| Record exceeds ingest/request bound | Rejected without silent truncation | Preserve source; add explicit chunk/blob support before importing that item |
| Nullable/missing native transcript path | Requires supported provider export | Use the documented app-server route if supported by the installed Codex version |

Running a watcher does not by itself discover every local conversation. It drains hook/manual jobs and scans only configured capture roots. Configure the native JSONL roots you intend to capture if file growth must be recovered after a missed hook. App-server capture requires a queued or explicitly supplied thread ID; this release does not enumerate every historical Codex thread automatically.

Capture adapters are versioned data contracts. A future parser that normalizes the same raw record differently can collide with the archived payload fingerprint. Upgrade through a deliberate source-stream version or derived-index migration; do not silently re-import a new interpretation as if nothing changed.

## Optional model enrichment

The default tree and lexical search need no model. The deterministic worker creates candidates only from explicit user markers, and should not be described as a complete semantic memory extractor.

For model summaries and extraction, configure an endpoint you intend to receive this project's content:

```bash
export AGENT_HUB_LLM_URL="https://YOUR_PROVIDER/v1"
export AGENT_HUB_LLM_MODEL="YOUR_COMPATIBLE_MODEL"
```

Supply `AGENT_HUB_LLM_KEY` through your normal secret manager/environment if required. Do not paste a real key into the repository or a saved setup script. A local model can use a loopback URL such as `http://127.0.0.1:11434/v1`. Ollama documents an [OpenAI-compatible API subset](https://docs.ollama.com/api/openai-compatibility); exact model support must be checked on your installation.

```bash
agent-hub worker --data-dir "$HOME/.local/share/agent-hub" --project atlas --llm --once --max-calls 10
agent-hub worker-status --data-dir "$HOME/.local/share/agent-hub" --project atlas
```

`--mode summaries` or `--mode memories` directs the whole budget to that stage; `both` initially allocates half to extraction, rounded down but with at least one available extraction call, and spends the remainder on summaries. With a one-call budget and pending extraction work, no summary call remains. Every attempted provider request and shortening retry consumes a call. A call records start/receipt/failure and provider-reported usage. The ledger cannot know a provider's actual bill after a lost response, and does not invent an exact cost.

The current compatible request shape is chat completions with string messages and `max_tokens`. A provider/model that requires a different request shape needs an adapter; selecting an incompatible model is an error, not a fallback to another paid provider. Redirects are disabled, and the worker does not inherit proxy environment settings. It sends only the selected bounded record/context, not the entire database.

Each request has a 45-second HTTP timeout, a 24,000-character bound across all of its message content, including system text, source/context and shortening history, and a requested maximum of 1,200 output tokens. Preceding context is separately capped at 12,000 characters. The 512-byte summary bound is enforced after response. Up to two shortening requests can follow, still within the run's total budget. Each retains the original system/source and every earlier retry message, then appends the prior response and correction. If that full input would exceed the character bound, no further HTTP request is made and the fallback remains available. Failure leaves the existing labelled fallback available. An unchanged retry prefix is not a measured cache hit. Distinct-node context is still recomputed; the worker does not yet implement the corrected Gist's persistent batched cache view or provider-specific cache controls. See [the cache review](CACHE_REVIEW.md). The worker does not call the native client's subscribed model implicitly; API billing and local inference costs are separate from a coding-app subscription.

Inputs too large for the worker are marked blocked with a reason and retained in the archive. Later extraction records and unrelated tree branches can progress; parents of an unprocessed child retain their fallback. Inspect these items with `worker-status`. After a change that can handle them, explicitly use `--retry-blocked`; this clears the project's blocked entries and rewinds extraction to before the earliest blocked event. Identical proposals are deduplicated; a revised extraction can still create different candidates. Changing only the endpoint or model does not raise the current 24,000-character bound, so an unchanged oversized input becomes blocked again.

```bash
agent-hub worker --data-dir "$HOME/.local/share/agent-hub" --project atlas --llm --once --max-calls 10 --retry-blocked
```

Periodic model work should schedule bounded invocations with a chosen frequency and budget. This delivery does not create a schedule or authorize recurring provider spending. Ordinary startup and ingestion do not call a model.

## Rebuild and upgrades

```bash
agent-hub rebuild --data-dir "$HOME/.local/share/agent-hub" --project atlas
```

Rebuild is an explicit cache reset. It preserves original events and durable memory records but replaces semantic summaries with deterministic defaults. Worker checkpoints, call observations and blocked-item records remain in their separate database. Recreating semantic content can cost model calls again. Back up first when preserving that cache matters.

Stop the service, take a backup, update the Git checkout to a reviewed commit, install its locked dependencies, run its migrations if supplied, and restart. Version 1 refuses a newer database schema; a code downgrade is not necessarily a valid data downgrade. Use a tested backup if a migration cannot be reversed.

## Add future integrations

The executable memory integration is listed in `src/agent_hub/catalog.json`. Validate changes with:

```bash
agent-hub catalog validate
agent-hub catalog list
```

The `mcps/`, `plugins/`, `skills/`, and `profiles/` guides establish storage and review conventions. This first release inventories these future additions; it does not install unknown third-party code or translate every client's plugin format. Add one concrete integration at a time with its source/version, execution host, credential requirements, supported clients, tests and removal instructions.
