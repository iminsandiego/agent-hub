# Agent Hub

A private home for your coding agents' shared memory, with one repository for the service, computer setup, and future MCP servers, plugins, and skills.

**Version 0.1.13.** An authenticated Python service with SQLite history, exact retrieval of captured records, project-scoped search, a binary summary tree, a browser memory view with password sign-in, client capture and setup tools, and optional bounded model summaries. See [the implementation specification](docs/SPEC.md), [client compatibility](docs/CLIENTS.md), and [verification evidence](docs/VALIDATION.md), which separates what was tested in development from what needs checking on your own computers.

**Home/work separation:** deploy an independent server per domain, with its own projects and tokens. Servers refuse projects outside their domain, client profiles carry strict project allowlists, and the local backfill planner checks transcripts against them. Read [the deployment and ingestion design](docs/DOMAINS_AND_INGESTION.md) before configuring a computer used for both.

## What it does

- Keep captured Codex, Claude, T3 and generic records on your server with stable source identity, deduplication, provenance and source timestamps.
- Give each computer its own revocable token scoped to projects such as `atlas`, `harbor` and `personal`. People sign in to the browser view with a password; tokens are for agents.
- Expose `memory_context`, `memory_search`, `memory_get`, `memory_zoom` and `memory_note` through MCP. Native clients keep control of their own tools and conversations.
- Start each new chat with a compact, dated context: notes, recent chats (newest first, each with its opening request), and history covering the whole project from the summary tree's roots, oldest first. `sections` picks which parts are included.
- Add matching history to a session's first prompt through a hook: the matching records, at most two per chat and each naming its chat, plus the start of that chat's latest answer. Later prompts and harness notices add nothing, and an outage adds nothing rather than delaying the prompt.
- Search conversation text with SQLite FTS5 (with a labelled substring fallback), ranking conversation ahead of injected text, tool output and derived threads. Hits and context lines carry `lo+n` references that `memory_zoom` opens, down to the exact captured source.
- Keep only content: records are classified as conversation, tool, injected, derived, title, metadata or bookkeeping. The server discards bookkeeping and approval-reviewer threads at ingest; `prune` removes those captured earlier.
- Keep durable memories as reviewable candidates. Activation and supersession are explicit, audited administrative actions; a remembered claim is never proof of a passed test.
- Capture through local hooks and an independent uploader. An unavailable server never blocks the coding session or loses the upload queue; jobs whose source never appears are set aside after a day instead of retrying forever.
- Support temporary chats and explicit forgetting, which also resets model-written summaries that may have copied from a forgotten chat. See [the user guide](docs/TEMPORARY_CHATS.md).
- Run without a model API key. Optional model summaries and memory proposals run under a hard per-run call budget.
- Keep a versioned integration catalog. It holds the memory MCP today; directories and conventions are ready for more MCPs, plugins and skills.

The server preserves records it has accepted. Until upload, the queue holds source paths or native thread identities, so those sources must still exist. Capture does not recover deleted vendor history or copy separately stored attachments and tool-output files. Select capture roots in the client guide to pick up file growth after a missed hook.

The design adopts ideas from [UniiChat (formerly OptChat)](https://github.com/VictorTaelin/UniiChat), implemented independently. It does not replace the Codex, Claude or T3 harness or control their compaction and prompt caching. See [the upstream analysis](docs/UPSTREAM_ANALYSIS.md) and [the cache correction review](docs/CACHE_REVIEW.md).

## Server quick start

Requires Python 3.11 or newer. Run this on the always-on Linux host.

```bash
git clone https://github.com/iminsandiego/agent-hub.git
cd agent-hub
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.lock
.venv/bin/python -m pip install --no-deps -e .
.venv/bin/agent-hub init-server --data-dir "$HOME/.local/share/agent-hub" --domain home --project home-garden --project home-finance --project home-lab
.venv/bin/agent-hub set-password --data-dir "$HOME/.local/share/agent-hub"
.venv/bin/agent-hub serve --server-config "$HOME/.local/share/agent-hub/server.json"
```

Open `http://127.0.0.1:8765` on that host and sign in with that password. Initialization also writes an administrative token to the private file it names (the token itself is not printed). Create separate project-scoped tokens for agent computers:

```bash
.venv/bin/agent-hub token create --data-dir "$HOME/.local/share/agent-hub" --name owner-laptop-home --project home-garden --output "$HOME/owner-laptop.token"
```

Move that token to its computer through a channel you trust. The repository must never contain tokens, transcripts, the memory database or runtime configuration. Token management and [backup and restore](docs/OPERATIONS.md) are local administration commands.

For access from other computers, use HTTPS through a reverse proxy or a private-network endpoint, or an SSH tunnel to the loopback port. Set the exact hostname and browser origins in `server.json`; localhost is the default. [Server setup](docs/SERVER_SETUP.md) covers Docker Compose, systemd, reverse proxy configuration and first provisioning.

## New computer setup

1. Clone this repository and install the package into a virtual environment (or run `scripts/bootstrap.sh` / `scripts/bootstrap.ps1`).
2. Configure the service URL, that computer's token, and explicit project mappings with `agent-hub configure`.
3. Run `agent-hub setup` to merge the MCP entry and hooks into each installed client, then check with `agent-hub doctor`.
4. Run the capture watcher (`agent-hub watch`) on the host where the agent actually runs, and add it to that system's startup tasks using [the client guide](docs/CLIENTS.md).

[The client guide](docs/CLIENTS.md) has the exact commands, hook behavior, mapping examples, parser versions and client limitations. **T3 setup targets its underlying provider on the T3 host**, and `agent-hub sync-t3` captures T3's saved history read-only, following a thread across providers. A phone or browser that only controls that host needs no watcher.

## Upgrading

On every computer, pull and reinstall, then rerun setup so new hooks are installed:

```bash
git pull
.venv/bin/python -m pip install -r requirements.lock
.venv/bin/python -m pip install --no-deps -e .
.venv/bin/agent-hub setup
.venv/bin/agent-hub doctor
```

On the server, also restart `agent-hub serve`. Some releases add a one-time maintenance step on the server; each has a report mode, and `--apply` changes data, so take a backup first:

| Command | Purpose |
| --- | --- |
| `agent-hub rebuild --project P` | Reclassify records and rebuild the tree after a classifier change |
| `agent-hub reorder --project P [--apply]` | Renumber backfilled records by source time |
| `agent-hub prune --project P [--apply]` | Remove bookkeeping captured before 0.1.12, then `VACUUM` |
| `agent-hub queue list` / `queue requeue --all` | Show or retry capture jobs set aside because their source is gone (run on the client) |

The [release notes](#release-notes) list the steps for each version.

## Model summaries

No external model call happens by default. The local worker can propose memories from explicit instruction and decision markers without a model:

```bash
.venv/bin/agent-hub worker --data-dir "$HOME/.local/share/agent-hub" --project home-garden --once
```

For model summaries and extraction, set `AGENT_HUB_LLM_URL` to an OpenAI-compatible `/v1` base URL, `AGENT_HUB_LLM_MODEL` to the model you choose, and `AGENT_HUB_LLM_KEY` if the endpoint needs one. Then run:

```bash
.venv/bin/agent-hub worker --data-dir "$HOME/.local/share/agent-hub" --project home-garden --llm --once --max-calls 10
```

Every model request, retries included, counts toward the cap, and provider usage is recorded locally; there is deliberately no unlimited loop. Replies over 512 bytes, incomplete, or not a real summary are rejected and retried once on a later run, then blocked for that item only. Inputs over 24,000 characters are blocked too; their records stay archived and searchable, and the tree above them is summarized over a labelled excerpt. `worker-status` lists blocked items and `--retry-blocked` reconsiders them. [Validation](docs/VALIDATION.md) records a model trial and a usage estimate; [operations](docs/OPERATIONS.md) covers privacy, bounds, recovery and model compatibility.

## Repository layout

```text
src/agent_hub/       Service, store, MCP, client, worker, browser, catalog
tests/              Behavioral, integration, transport and persistence checks
docs/               Spec, upstream analysis, setup, operations, release notes and evidence
deploy/             Docker, reverse proxy and systemd examples
scripts/            Install, backfill, watcher and browser smoke helpers
mcps/               Convention for future MCP integrations
plugins/            Convention for future plugin packages
skills/             Convention for future skill packages
profiles/           Example machine and project profiles (no credentials)
```

## Development

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[dev]'
.venv/bin/python -m pytest -q
.venv/bin/python -m build
```

Tests use synthetic data only. `requirements.lock` records the tested runtime dependency versions. The GitHub Actions workflow runs the tests on Linux, macOS and Windows; see the validation document for which environments have actually run. Check Codex and Claude upgrades against `docs/CLIENTS.md` before relying on changed transcript or hook formats. [The publication guide](docs/PUBLISH.md) describes how a new private copy of the repository is created.

## Release notes

| Version | Highlights |
| --- | --- |
| [0.1.13](docs/RELEASE_0.1.13.md) | First-prompt matches bring each chat's latest answer; setup keeps Codex tool approvals; harness notices don't use up the first prompt |
| [0.1.12](docs/RELEASE_0.1.12.md) | Record classes, no bookkeeping at ingest, `prune`, recent chats in the startup context, first-prompt history hook |
| [0.1.11](docs/RELEASE_0.1.11.md) | Jobs for a missing source are set aside after a day; `agent-hub queue` |
| [0.1.10](docs/RELEASE_0.1.10.md) | Foreign-key indexes so `reorder` and deletes stay fast on large projects |
| [0.1.9](docs/RELEASE_0.1.9.md) | Fixes from the UniiChat comparison, `reorder`, parser version 2, dated compact context, `lo+n` zoom, better summaries, stricter forgetting |
| [0.1.8](docs/RELEASE_0.1.8.md) | Redesigned browser view and password sign-in |
| 0.1.6 | Temporary chats and explicit forgetting ([guide](docs/TEMPORARY_CHATS.md)) |
| 0.1.5 | Read-only T3 saved-history capture ([guide](docs/CLIENTS.md#t3-saved-history-capture-015)) |
| [0.1.2](docs/RELEASE_0.1.2.md)–[0.1.4](docs/RELEASE_0.1.4.md) | Domain guards, strict project allowlists, backfill planner; Windows install and backup fixes |
