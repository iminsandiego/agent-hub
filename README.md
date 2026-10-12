# Agent Hub

A private home for your coding agents' shared memory, with one repository for the service, computer setup, and future MCP servers, plugins, and skills.

**Status: initial implementation, version 0.1.2.** It includes an authenticated Python service, SQLite history, exact captured-record retrieval, project-scoped search, a binary summary tree, a memory browser, client capture/configuration tools, and optional bounded model enrichment. See [the implementation specification](docs/SPEC.md), [client compatibility](docs/CLIENTS.md), and [verification evidence](docs/VALIDATION.md). Deployment and native-client checks that require your computers are explicitly distinguished from tests run in development.

**Home/work separation:** deploy independent domain servers and native profiles. Version 0.1.2 adds server domain guards, strict client project allowlists, cross-project transcript checks and a local backfill planner. Read [the deployment and ingestion design](docs/DOMAINS_AND_INGESTION.md) before configuring mixed-use computers. No production histories have been imported.

## What it does

- Keep captured Codex/Claude/generic records on your server with stable source identity, deduplication, provenance, and source timestamps.
- Give each computer a separate revocable token scoped to projects such as `atlas`, `harbor`, and `personal`.
- Expose `memory_context`, `memory_search`, `memory_get`, `memory_zoom`, and `memory_note` through MCP. Native clients keep control of their own coding tools and conversations.
- Search the adapter's normalized event text using SQLite FTS5, with a labelled substring fallback when FTS5 is unavailable. Walk a deterministic summary tree back to a captured source, with explicit pages for large records.
- Keep durable memories as reviewable candidates. Activation and supersession are explicit, auditable administrative actions; a remembered claim is never proof of a passed test.
- Capture through local hooks and an independent uploader. An unavailable server must not block the coding session or erase the upload queue.
- Run without a model API key. Optional model enrichment improves summaries and proposes memories under a hard per-run call budget.
- Keep a versioned integration catalog. The initial catalog contains the memory MCP; directories and conventions are ready for your additional MCPs, plugins, and skills.

The server preserves records it has successfully accepted. Before upload, the queue contains source paths or native thread identities, so those sources must remain available. Capture does not recover deleted vendor history or copy separately stored attachments and tool-output files. Select capture roots in the client guide to recover file growth after missed hooks.

This implements the ideas useful for a multi-client service from [UniiChat (formerly OptChat)](https://gist.github.com/VictorTaelin/91837951a5ce5b38f341ec1ba1df6449), independently. It does not replace Codex/Claude/T3's harness or control their native compaction and prompt caching. [Read the upstream audit and design differences](docs/UPSTREAM_ANALYSIS.md).

**Cache correction review:** the author revised the Gist after our initial build. Version 0.1.1 updates the source comparison and fixes our optional summarizer's shortening requests to preserve the original context and source as conversation history. Our retrieval views and worker do not implement the author's complete persistent cache-view algorithm, and no cache-hit percentage has been measured for this application. See [the correction review](docs/CACHE_REVIEW.md).

## Server quick start

Requires Python 3.11 or newer. Run this on the always-on Linux host. The intended private repository is `iminsandiego/agent-hub`; publish the source using [the publication guide](docs/PUBLISH.md) before running its clone command.

```bash
git clone https://github.com/iminsandiego/agent-hub.git
cd agent-hub
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.lock
.venv/bin/python -m pip install --no-deps -e .
.venv/bin/agent-hub init-server --data-dir "$HOME/.local/share/agent-hub" --domain home --project home-garden --project home-finance --project home-lab
.venv/bin/agent-hub serve --server-config "$HOME/.local/share/agent-hub/server.json"
```

Open `http://127.0.0.1:8765` on that host. Initialization writes an administrative token to the printed private file; the token itself is not printed. Use it locally to inspect and review memories. Create separate project-scoped credentials for agent computers.

```bash
.venv/bin/agent-hub token create --data-dir "$HOME/.local/share/agent-hub" --name owner-laptop-home --project home-garden --output "$HOME/owner-laptop.token"
```

Transfer that token to its intended computer through your trusted channel. The repository must never contain the token, transcripts, memory database, or runtime configuration. Token management and [backup/restore](docs/OPERATIONS.md) are local administration commands.

For access from other computers, use HTTPS through a reverse proxy or a private-network HTTPS endpoint. Set the exact hostname and browser origins in `server.json`; localhost is the default. [Server deployment instructions](docs/SERVER_SETUP.md) include Docker Compose, systemd, reverse proxy configuration, and initial provisioning.

## New computer setup

1. Clone this repository and install the package into a virtual environment (or run `scripts/bootstrap.sh` / `scripts/bootstrap.ps1`).
2. Configure the service URL, that computer's token, and explicit project mappings.
3. Run the setup command for each installed native client, then verify with `doctor`.
4. Run the capture watcher on the actual execution host. Add it to that operating system's startup tasks using [the client guide](docs/CLIENTS.md).

The [new-computer guide](docs/CLIENTS.md) contains the exact commands, hook payload behavior, mapping examples, and native-client limitations. **T3 setup targets its underlying provider on the T3 execution host.** A phone or browser used to control that host does not need its own transcript watcher.

## Model enrichment

No external model call happens by default. The local worker can propose memories from explicit instruction/decision markers:

```bash
.venv/bin/agent-hub worker --data-dir "$HOME/.local/share/agent-hub" --project home-garden --once
```

For optional semantic summaries/extraction, set `AGENT_HUB_LLM_URL` to an OpenAI-compatible `/v1` base URL, `AGENT_HUB_LLM_MODEL` to a compatible model you choose, and `AGENT_HUB_LLM_KEY` when the endpoint requires it. Then run:

```bash
.venv/bin/agent-hub worker --data-dir "$HOME/.local/share/agent-hub" --project home-garden --llm --once --max-calls 10
```

Each attempted HTTP model request, including shortening retries, counts toward that cap. Usage returned by the provider is recorded locally. An unlimited LLM worker loop is deliberately not implemented. Inputs over the worker's 24,000-character bound are recorded as blocked; their archived records and deterministic excerpts remain available while later records and unrelated tree branches can progress. `worker-status` shows these items, and `--retry-blocked` explicitly reconsiders them after a change that can handle their size. See [operations](docs/OPERATIONS.md) for privacy, bounds, recovery, and model compatibility.

## Repository layout

```text
src/agent_hub/       Service, store, MCP, client, worker, browser, catalog
tests/              Behavioral, integration, transport and persistence checks
docs/               Tailored spec, source audit, setup, operations and evidence
deploy/             Docker, reverse proxy and systemd examples
scripts/            New-install helpers and GitHub publication helper
mcps/               Convention for future MCP integrations
plugins/            Convention for future plugin packages
skills/             Convention for future skill packages
profiles/           Examples of machine/project profiles (no credentials)
```

## Development

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[dev]'
.venv/bin/python -m pytest -q
.venv/bin/python -m build
```

`requirements.lock` records the tested transitive runtime dependency versions. The GitHub Actions workflow is configured to repeat the tests on Linux, macOS, and Windows; see the validation document for which environments have actually run. Check native Codex/Claude upgrades against `docs/CLIENTS.md` before relying on changed transcript or hook formats.

## Publishing to your account

The helper `scripts/publish-github.sh` creates a **private** repository through your authenticated GitHub CLI and pushes the committed source. It stages the intended source directories when initializing a new checkout; review the committed files and keep runtime data outside them. See [the publication guide](docs/PUBLISH.md). Until a remote push is verified, a local checkout or ZIP is not a published GitHub repository.
