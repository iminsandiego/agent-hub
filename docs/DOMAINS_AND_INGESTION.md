# Home/work separation and multi-client ingestion

Release 0.1.2 · 11 October 2026 (America/Los_Angeles)

## Deployment decision

Use the same private source repository to deploy **two independent services**:

| Domain | Placement | Persistent data | Access |
| --- | --- | --- | --- |
| Home | Always-on Linux VM on your home server | Home-only database, token database, worker, backups and logs | Your personal devices over a private network and verified HTTPS |
| Work | Employer-approved workstation, VM or internal server | Work-only database, token database, worker, backups and logs | Approved work devices; approved remote access from home |

A work task stays work regardless of where you are sitting. When controlling your work computer from home through RDP, Screen Sharing, Codex remote execution or T3, install the work uploader on the **work execution host**. The home computer is a control surface. If an agent executes employer work locally at home, it needs a separate approved work profile and work endpoint; do not route it to the home service.

Separate instances avoid a shared administrator token, database, index, summaries, context cache, backup and enrichment process. Separate VMs/OS users further reduce the impact of credential mistakes. Two containers on one home host do not create an employer-approved custody boundary; the host administrator still controls both.

Recommended initial deployment: one small home VM, one service process, SQLite on local disk, loopback binding, private-network HTTPS proxy, encrypted host storage and encrypted backups. The existing systemd and Compose instructions apply independently to each instance. Never share the database volume, reverse-proxy route, worker environment or backup destination across domains. With Compose use separate project names/volumes, and different loopback ports if colocated. The default worker project in the example is legacy `atlas`; set it explicitly for every domain deployment. Do not expose the memory port publicly. An SSH tunnel to loopback is an alternative.

## Identity and scope contract

Domain is a server boundary. Project remains the existing authorization and retrieval boundary, with explicit domain-prefixed IDs:

- `home-garden`, `home-finance`, `home-lab`, `home-household`.
- `work-atlas`, `work-ccm`, `work-harbor` (choose whether related repositories belong to one project deliberately).

Device/profile identities identify provenance: for example `owner-mac-home`, `owner-workstation-work`. These names are descriptive, not authenticated device attestation. The bearer principal ID is the authenticated identity. Existing native client/machine/session/event identities and immutable raw records remain intact. The server does not bind a token to a claimed machine ID; use separate tokens, issuance records and restricted hosts, and regard client-reported machine fields as claims.

Create one revocable token per execution host/profile with only explicit projects and required permissions. Use a project-only token per agent where possible; read-only tools can use `--permissions read`, ingestion-only collectors can use `--permissions write`. A normal combined agent/uploader token defaults to read/write. No agent gets the local admin token. Admin tokens can approve memories only inside their server's domain. Tokens have revocation but no built-in expiry or SSO; rotate operationally. This is a single-owner service, not a general multi-tenant identity platform.

No global memory is automatically joined. Copy a small set of neutral preferences into each domain only after inspecting them; never copy employer transcripts or inferred work details as personal preferences. Multi-project tokens authorize deliberate access to all listed projects, so prompt-level instructions are not isolation. To isolate projects from each other use one allowed project and one project-scoped token per profile, along with native filesystem restrictions.

## Server setup

Install using `docs/SERVER_SETUP.md`, then initialize fresh instances:

```bash
agent-hub init-server --data-dir /srv/agent-hub-home --domain home \
  --project home-garden --project home-finance --project home-lab
agent-hub token create --server-config /srv/agent-hub-home/server.json \
  --name owner-mac-home-garden --project home-garden \
  --output /secure-transfer/home-garden.token
agent-hub serve --server-config /srv/agent-hub-home/server.json
```

On the approved work host, use `--domain work`, a separate data directory and work-prefixed projects. Domain configuration is persisted in `server.json`. All REST and MCP project access, project creation and ingestion enforce that prefix. Startup refuses an existing database containing projects from another domain. Local filesystem administrators can change settings or databases, so this is defense in depth, not protection against a compromised host administrator.

Pass `--server-config` to local project/token administration so domain checks apply; `--data-dir` alone uses default settings rather than inferring `server.json`. The worker uses an explicitly selected project and local database; run it only against the matching domain data with its matching model policy. It is not a network principal and local disk access is administrative authority.

## Native profiles on mixed-use computers

Use separate OS accounts when feasible. Otherwise keep separate native homes, Agent Hub configuration files, token variables, token files, state directories and watcher services. Keep only the matching profile's MCP and hooks in each native home. Do not install both domains into one shared native profile. Pinned chats and account names do not establish scope. Starting an old mixed chat in a new profile does not remove its history.

```bash
agent-hub --config /absolute/private/home-garden/client.json configure \
  --url https://memory-home.example.com --machine-id owner-mac-home \
  --domain home --strict-scope --allow-project home-garden \
  --token-env AGENT_HUB_HOME_TOKEN \
  --token-file /absolute/private/home-garden/machine.token \
  --state-dir /absolute/private/home-garden/state \
  --map /absolute/personal/garden=home-garden

agent-hub --config /absolute/private/home-garden/client.json setup \
  --clients codex --codex-home /absolute/private/codex-home
agent-hub --config /absolute/private/home-garden/client.json doctor
agent-hub --config /absolute/private/home-garden/client.json watch
```

Use a separate command and configuration for work with `--domain work`, work allowlist and work endpoint. `--allow-project` replaces the existing allowlist when supplied; repeat it for each intended project. `--strict-scope` persists once enabled; deliberate removal requires editing the local config. Strict profiles reject fallback defaults, require a nonempty project allowlist and require working-directory evidence. Mappings, explicit CLI project arguments and stdio memory tools cannot bypass the profile's domain/allowlist. Native direct HTTP tools bypass this local defense, but the server/token boundary still applies; prefer the stdio gateway.

Run Codex with the corresponding `CODEX_HOME`. For Claude, use separate `CLAUDE_CONFIG_DIR` values and configure both `--claude-home` and the verified profile-specific `--claude-mcp-file` location. Verify with `claude mcp list` in that exact environment; do not assume a global MCP file becomes profile-local. Provider accounts and managed rules stay under their native security controls. A separate config directory alone does not prevent access to other files by the same OS user.

T3's official Codex guide says shadow homes share sessions and configuration. **Do not use a shadow home for home/work isolation.** Use completely separate CODEX_HOME paths with no shadow home. Claude instances also need separate config directories. Separate T3 environments/OS accounts are stronger than multiple provider entries inside one T3 environment, whose own orchestration history may contain both domains. Configure and verify the actual executing host, not merely the controlling browser.

## Automatic capture

| Client/surface | Implementation | Acceptance required |
| --- | --- | --- |
| Local Codex | SessionStart bounded context; Stop/SessionEnd queue; watcher reads native JSONL or read-only app-server persisted history | Hook trust, installed protocol, actual native test and correct provider home |
| Claude Code | SessionStart bounded context; Stop/SessionEnd and SubagentStop queue; watcher reads JSONL | Native lifecycle and custom profile MCP location |
| T3 Codex/Claude providers | Matching underlying provider configuration and host watcher | Live provider inheritance, hooks and capture; no T3-specific importer is claimed |
| Cloud conversations | Explicit supported export/import | Local command hooks are not generally supported by cloud orchestration; no automatic ChatGPT Library sweep |

Teardown hooks enqueue paths/identities quickly, not uploads. Watchers retry with backoff and checkpoint only acknowledged events. Queue entries are not complete local transcript snapshots: deleted/expired source files cannot be recovered from queued paths. Add **selected** capture roots to recover missed hooks and archive before native retention removes sources. No model call is needed for ingestion/search. Startup context costs prompt tokens. A seven-day timestamped offline cache is implemented; revocation cannot erase caches while a machine is offline. Work profiles with sensitive history should run on encrypted, access-controlled devices; delete/expire local caches under the employer's retention policy.

Strict capture scans native cwd metadata across the entire available transcript (including Codex session/turn metadata, Claude record cwd, and API commandExecution cwd). It refuses mixed, unmapped or out-of-allowlist source directories before uploading that snapshot. An explicit `--project` does not override the scan. Command directories in build/temp locations may need explicit same-project mappings. Existing accepted prefixes remain preserved if a later appended record makes a session mixed; the new scan blocks further upload, but cannot retrospectively remove a prior upload.

Cwd evidence is a guardrail, not content classification: a user can paste employer data into a home session without changing directories. Shell commands may mention or enter another directory without native metadata reflecting it. Native APIs can omit context fields. Prevent that at the session, OS, filesystem and employer-policy layers. Do not claim the collector is DLP or that it sanitizes transcripts.

## Historical backfill

1. Preserve original vendor history and select its execution-host/profile roots. Do not copy work history to the home server to classify it. Keep source files read-only for the inventory stage.
2. Run a local inventory with the intended strict configuration:

   ```bash
   agent-hub --config /absolute/private/home-garden/client.json plan-import \
     /absolute/selected-history --output /absolute/private/home-garden/backfill-plan.json
   ```

   This reads source files and returns paths, native session IDs, hashes, counts, projects, pending tails and blocked reasons. It needs no token, makes no network call and creates no queue/checkpoints. The report contains sensitive paths/identifiers, so it is private and belongs outside Git. It never includes conversation text. A `ready` status proves routing/format checks, not employer approval or content safety. API-only Codex history needs an explicit persisted API export; the new planner accepts JSONL only.
3. Review unknown/mixed/projectless sources locally. Do not infer domain from the current computer, a pinned thread, account name, title or a text keyword. Map verified worktree aliases explicitly. Split a mixed export only as a reviewed derivative: retain its original hash, parent identity, selected record ranges, reviewer and derivation manifest. There is no automatic splitting/redaction implementation in 0.1.2.
4. Pilot a few **selected, reviewed files** using `ingest ... --queue`, run `watch --once`, and inspect exact source retrieval plus queue errors. Directory-wide queueing includes blocked files; prefer explicit reviewed files initially. Never use a broad default project to force an unknown history import through.
5. Expand in bounded batches. Retries deduplicate by native stable identity; source rewrite/truncation raises a conflict. Codex JSONL and app-server representations are separate streams and can duplicate the conversation semantically; select one surface per source. Cross-machine copying also creates separate provenance. Do not reset checkpoints to bypass conflicts.
6. Enable deterministic candidates first. Model enrichment remains opt-in, bounded per run and subject to the domain's provider policy. Inspect candidates before activating them. Timestamp and authoritative source verification remain separate from usefulness review.

The importer retains exact accepted UTF-8 JSON record strings and stable IDs; line delimiters and external attachments are not archived. Original-file byte hashes are in the backfill inventory, not a claim that the archive reconstructs every original file byte. Normalizers preserve unknown records but may not index every raw field. Large transcripts are currently parsed in memory and re-read during scans; inventory/pilot first, measure resource use, then consider a streaming adapter before very large backfills.

## Security and employer custody

Do not put employer transcripts on the personal home server without explicit organizational approval covering storage, remote access, backups, retention and any model-provider processing. A private GitHub repository or VPN does not establish approval. Keep this repository restricted to generic application code, synthetic tests and setup documentation; no employer code, conversations, tokens or database backups belong in it.

Prefer employer-controlled storage and model credentials, access logs, encrypted backups and a tested restore procedure. Define retention/deletion responsibilities before ingesting work: the append-only archive has no implemented selective purge/retention lifecycle, and derived summaries, caches, raw records and backups all need coordinated removal. Native transcripts can contain passwords, tokens, customer data, source code and tool output. This release does not encrypt SQLite itself, implement full audit/compliance controls, attest devices, automatically redact secrets, or make provider disclosure safe. Raw originals and redacted derivatives must have distinct identities if a redaction workflow is added.

Retrieved conversations and summaries remain untrusted attributed data, including prompt injections. They cannot grant permissions, change requirements or prove a test passed. Generated memories remain candidates until an explicit local administrator reviews them. The home and work workers must never share model credentials or an unapproved external model endpoint.

## Future MCPs, plugins and skills

The existing catalog and `mcps/`, `plugins/`, `skills/`, `profiles/` structure remain the expansion points. Add packages with upstream source/version/license, checksum, supported clients, domain suitability, capabilities, network destinations, credential references, trust review, validation and removal instructions. Code availability is not permission to install or access data. Do not synchronize entire native homes, account credentials or personal skills into a work environment. A future catalog domain field should fail closed; no domain-aware catalog installer is implemented in this release.

## Current documentation checked

- [OpenAI lifecycle hooks](https://learn.chatgpt.com/docs/hooks): trust review, short synchronous SessionEnd, nullable/unstable transcript surface, and cloud orchestration limitations.
- [Claude lifecycle hooks](https://code.claude.com/docs/en/hooks): command hook input/output and profile/settings scopes.
- [T3 Codex providers](https://github.com/pingdotgg/t3code/blob/main/docs/user/providers-codex.md): shared shadow state versus completely separate homes.
- [T3 Claude providers](https://github.com/pingdotgg/t3code/blob/main/docs/user/providers-claude.md): separate config directories and remote-host placement.

Checked 11 October 2026. Documentation support is distinct from a live installed-client test; see `VALIDATION.md`.
