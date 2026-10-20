# New computer setup and client compatibility

Agent Hub keeps history on your server. Each computer runs a small local client that connects its coding tools to that service and uploads explicitly mapped sessions. The same GitHub repository supplies the implementation, setup commands, and future integration catalog.

Start with the [server guide](SERVER_SETUP.md). You need its HTTPS URL and a separate, revocable project-scoped token for this computer. A local SSH tunnel to a loopback HTTP endpoint also works. Agent Hub verifies TLS; remote plain HTTP is rejected.

For mixed home/work use, review [domain setup and ingestion](DOMAINS_AND_INGESTION.md).
Strict domains and allowlists are optional; the home deployment deliberately uses
one `home` project without directory guards. Work can use an independent server
and profile. Choose the boundaries appropriate to the installation.

For retrieval without a lookup reminder, follow [automatic memory setup](AUTOMATIC_MEMORY.md).
It includes Codex/Claude instructions, Grok MCP setup, real T3 qualification and
the current temporary-chat/deletion limitations. Normal `setup` registers
Codex/Claude MCP and hooks; it does not install that global instruction policy.

## Install on a new computer

### macOS or Linux

After publishing `iminsandiego/agent-hub`, clone the private repository, replace the sample paths and project IDs, and use Python 3.11 or newer:

```bash
git clone https://github.com/iminsandiego/agent-hub.git
cd agent-hub
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.lock
.venv/bin/python -m pip install --no-deps -e .
.venv/bin/agent-hub configure \
  --url https://memory.example.com \
  --machine-id laptop-main \
  --map "$HOME/Projects/atlas=atlas" \
  --map "$HOME/Projects/harbor=harbor"
.venv/bin/agent-hub setup --clients codex claude
.venv/bin/agent-hub doctor
.venv/bin/agent-hub context --project atlas
.venv/bin/agent-hub watch
```

`configure` asks for the token using hidden terminal input when a token file or environment variable is unavailable. It saves the credential separately from `client.json`. If you transferred a token file, add `--token-file /absolute/private/machine.token`. Never put a token value in a shell argument. Select only the clients you use, for example `setup --clients codex`.

The helper performs installation, configuration, setup for Codex and Claude, and connection checks:

```bash
./scripts/bootstrap.sh \
  --url https://memory.example.com \
  --machine-id laptop-main \
  --map "$HOME/Projects/atlas=atlas" \
  --token-file "$HOME/.config/agent-hub/machine.token"
```

Keep this checkout and its virtual environment at their installed paths. Setup records the absolute Python executable and configuration path, so an app launched from the desktop does not need your shell's virtual-environment activation. After moving or reinstalling the checkout, rerun `setup`.

### Windows

Use a normal PowerShell terminal with Python 3.11 or newer installed. After cloning the repository:

```powershell
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.lock
.\.venv\Scripts\python.exe -m pip install --no-deps -e .
.\.venv\Scripts\agent-hub.exe configure --url https://memory.example.com --machine-id windows-main --map 'C:\Projects\Atlas=atlas'
.\.venv\Scripts\agent-hub.exe setup --clients codex claude
.\.venv\Scripts\agent-hub.exe doctor
.\.venv\Scripts\agent-hub.exe context --project atlas
.\.venv\Scripts\agent-hub.exe watch
```

Alternatively, run `scripts/bootstrap.ps1 -Url https://memory.example.com -Map 'C:\Projects\Atlas=atlas' -TokenFile 'C:\Private\machine.token'`. It installs the package and configures the selected clients. Its `-Clients` parameter defaults to Codex and Claude. Use your organization's normal PowerShell script policy; the helper does not alter it.

The core client and MCP gateway use Python and explicit process arguments. Native Windows lifecycle execution still needs validation on your installed client. Codex command hooks run through a native shell; setup rejects shell metacharacters in their installation/configuration paths. Codex has had Windows quoting defects, so check that a hook actually runs. If it does not, use `setup --no-hooks`, explicitly configure transcript capture paths, run the watcher, and retrieve startup context with the memory tools. Current runner behavior is visible in [Codex's command runner source](https://github.com/openai/codex/blob/main/codex-rs/hooks/src/engine/command_runner.rs).

### Final checks inside each coding client

Restart the coding client after setup. Inspect `/mcp` for `agent-hub`, review the generated handlers in `/hooks`, and complete the client's normal trust review. Ask it to call `memory_context` for a project authorized by its token. Run a harmless synthetic session in a mapped directory, end the turn, and check `agent-hub doctor` after the watcher has drained the queue. A source should then be discoverable through `memory_search`.

Registration success does not prove that native lifecycle callbacks ran. Workspace trust, managed policies, client version, and the execution host all affect availability. Setup preserves those controls.

Later examples use `agent-hub` for readability. Activate the environment with `source .venv/bin/activate` on macOS/Linux or `.\.venv\Scripts\Activate.ps1` on Windows, or keep using the full executable paths above. Activation is only for interactive terminal commands; generated native-client entries already use absolute paths.

## Configuration and project isolation

Default location: `~/.config/agent-hub/client.json`, or `$XDG_CONFIG_HOME/agent-hub/client.json`. On Windows, `~` is your user profile. A custom location is a global option placed before the subcommand:

```bash
agent-hub --config /absolute/path/client.json doctor
```

Example configuration contains references to credentials, never their values:

```json
{
  "schema_version": 1,
  "url": "https://memory.example.com",
  "token_env": "AGENT_HUB_TOKEN",
  "token_file": "/home/me/.config/agent-hub/machine.token",
  "machine_id": "laptop-main",
  "project": null,
  "mappings": [
    {"path": "/home/me/Projects/atlas", "project": "atlas"},
    {"path": "/home/me/Projects/harbor", "project": "harbor"}
  ],
  "capture_paths": [],
  "state_dir": "/home/me/.config/agent-hub/state"
}
```

Use the same project IDs on every computer, with that computer's own absolute paths. IDs start with a lowercase letter and contain at most 64 lowercase letters, digits, underscores, or hyphens. The most specific matching directory wins. Path boundaries matter: mapping `/work/atlas` does not match `/work/atlases`. Windows drive paths are normalized without case distinctions. Separate Git worktrees may require additional mappings.

An unmatched session is blocked and remains in the local queue. An explicit `--project` overrides mapping for a deliberate import. A configuration-level `--project` sets a default for every unmatched session, so use it only for an installation whose entire capture scope belongs to that project. Explicit mappings are preferable for a computer with several projects.

Re-running `configure` preserves the machine ID and existing mappings/capture paths, adding or replacing the supplied entries. Edit `client.json` to remove a mapping or capture path. Review queued jobs before remapping: a source already assigned to a project is prevented from silently changing projects.

The environment variable named by `token_env` (default `AGENT_HUB_TOKEN`) takes precedence over `token_file`. `--save-token` stores the environment value or hidden prompt input in the separate token file. Client files are created with private POSIX modes; Windows protection depends on the containing directory's ACL. Keep state, credentials, native transcripts, and backups outside the source repository. Give each installation a distinct machine ID and server token; revoke a lost computer's token on the server.

## What setup changes

`setup --dry-run` reports planned paths without writing. Normal setup parses and validates every selected configuration before making changes, preserves unrelated MCP entries and hook groups, and writes a private timestamped backup of each existing file it changes. Repeated setup with the same inputs makes no duplicate handlers. A manually changed or unrelated entry already named `agent-hub` produces a visible conflict.

| Client | MCP registration | Hook registration | Agent Hub handlers |
| --- | --- | --- | --- |
| Codex | `CODEX_HOME/config.toml`, default `~/.codex/config.toml` | `CODEX_HOME/hooks.json` | `SessionStart`, `Stop`, `SessionEnd` |
| Claude Code | User MCP file, normally `~/.claude.json` | `CLAUDE_CONFIG_DIR/settings.json`, default `~/.claude/settings.json` | `SessionStart`, `Stop`, `SessionEnd`, `SubagentStop` |
| T3 Code | Underlying Codex or Claude provider on its execution host | Underlying provider, where supported | No invented T3-specific memory hook |

Codex [documents shared CLI/IDE MCP configuration](https://developers.openai.com/codex/mcp). Claude [documents MCP scopes separately from hook settings](https://code.claude.com/docs/en/mcp). For a custom Claude profile, supply both `--claude-home` and `--claude-mcp-file` with the verified paths for that profile; Agent Hub does not guess where another account's global application state lives.

```bash
agent-hub setup --clients codex --codex-home /absolute/custom-codex-home
agent-hub setup --clients claude --claude-home /absolute/custom-claude-home --claude-mcp-file /absolute/verified-profile-mcp.json
```

Run setup with the same relevant profile environment used by the provider. If T3 creates a shadow or isolated home, configure that home explicitly. Restoring a backup or removing the `agent-hub` server and its generated hook handlers reverses registration. `--no-hooks` skips adding/updating hooks; it does not remove handlers from a previous installation.

### Default: local stdio gateway

The native client launches your installed Python executable with an argument array equivalent to:

```text
-m agent_hub.cli --config /absolute/path/client.json mcp
```

The gateway uses the official MCP Python SDK and forwards the five memory tools to the authenticated service. It reads the token locally, which also works when a desktop app does not inherit terminal environment variables. Protocol output is reserved for MCP messages.

### Optional: native HTTP connection

`agent-hub setup --transport http --clients codex claude` registers the server's `/mcp` endpoint directly. The underlying app must have the configured token environment variable (default `AGENT_HUB_TOKEN`) in its own environment; native HTTP clients cannot read Agent Hub's `token_file` setting. The generated configurations reference the variable without embedding its value.

Codex example:

```toml
[mcp_servers.agent-hub]
url = "https://memory.example.com/mcp"
bearer_token_env_var = "AGENT_HUB_TOKEN"
```

Claude user MCP example:

```json
{
  "mcpServers": {
    "agent-hub": {
      "type": "http",
      "url": "https://memory.example.com/mcp",
      "headers": {"Authorization": "Bearer ${AGENT_HUB_TOKEN}"}
    }
  }
}
```

HTTP transport does not replace local capture. Keep the hook client and watcher installed if you want new local sessions archived.

## Automatic capture and startup context

The installed `Stop` and `SessionEnd` handlers only enqueue the source path or native thread identity in a local SQLite outbox. They do not read a transcript, call a model, upload over the network, or spawn a background uploader. This keeps end-of-session work short. The independent `watch` process uploads complete records and retries failures with backoff.

A hook can name a source that is never saved: a Claude Code subagent or non-interactive run that writes no transcript, or a Codex background thread the app-server answers with "thread not loaded". Such a job is retried while its source stays missing for 24 hours, then set aside (0.1.11). It is kept, not deleted; it no longer counts as pending or as an error, and `doctor` reports the number under `source_gone`. Any other failure in between restarts the 24 hours. New work for the same source (a changed file, another hook) brings the job back. `agent-hub queue list` shows set-aside jobs with their path or thread ID, and `agent-hub queue requeue ID…` or `--all` retries them.

`SessionStart` requests live context for the mapped directory, capped at 8,000
characters and trimmed at source-line boundaries. Persistent offline memory
caches are no longer written or used; upgrade clears their old rows. An outage
produces no historical injection, so forgotten content cannot return from a
seven-day fallback. Use `agent-hub context` for a live manual lookup.

Current [Codex hook documentation](https://learn.chatgpt.com/docs/hooks) exposes startup/resume/clear/compact contexts, permits a null transcript path, and makes `SessionEnd` synchronous with a short timeout. Transcript format is explicitly unstable. End events are not a complete subagent archive. Agent Hub also captures at `Stop` to reduce dependence on final close behavior.

Current [Claude hook documentation](https://code.claude.com/docs/en/hooks) supports command hooks and an `additionalContext` response at `SessionStart`. Agent Hub uses its executable-plus-arguments form and captures a `SubagentStop` source through `agent_transcript_path`, keeping the child source distinct from its parent.

### Keep the watcher running

Run `agent-hub watch` as the same user that runs the coding provider, with access to its configuration and source files. Run one watcher per installation. `watch --once` performs one discovery/drain pass; `watch --no-scan` processes hook/manual jobs without scanning configured directories. `--poll-seconds` accepts 1–60 seconds and defaults to 5.

On a systemd Linux desktop/server, save this as `~/.config/systemd/user/agent-hub-watch.service`, replacing paths with your real absolute paths:

```ini
[Unit]
Description=Agent Hub transcript uploader
After=network-online.target

[Service]
Type=simple
ExecStart=/home/me/agent-hub/.venv/bin/python -m agent_hub.cli --config /home/me/.config/agent-hub/client.json watch
Environment=PATH=/home/me/.local/bin:/usr/local/bin:/usr/bin:/bin
Restart=on-failure
RestartSec=5

[Install]
WantedBy=default.target
```

Then run:

```bash
systemctl --user daemon-reload
systemctl --user enable --now agent-hub-watch.service
journalctl --user -u agent-hub-watch.service -n 50
```

The service's `PATH` must include the actual Codex executable for app-server capture. A custom Codex profile also needs `Environment=CODEX_HOME=/absolute/profile`. Use a token file, since a user service may not inherit your interactive shell environment. This runs while the user's systemd manager is active; an always-on host may need user lingering configured by its administrator.

On macOS, create `~/Library/LaunchAgents/com.agent-hub.watch.plist` with your actual paths:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>com.agent-hub.watch</string>
  <key>ProgramArguments</key><array>
    <string>/Users/me/agent-hub/.venv/bin/python</string>
    <string>-m</string><string>agent_hub.cli</string>
    <string>--config</string><string>/Users/me/.config/agent-hub/client.json</string>
    <string>watch</string>
  </array>
  <key>EnvironmentVariables</key><dict>
    <key>PATH</key><string>/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin</string>
  </dict>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>StandardOutPath</key><string>/Users/me/Library/Logs/agent-hub-watch.log</string>
  <key>StandardErrorPath</key><string>/Users/me/Library/Logs/agent-hub-watch-error.log</string>
</dict></plist>
```

Load it with `launchctl bootstrap "gui/$(id -u)" "$HOME/Library/LaunchAgents/com.agent-hub.watch.plist"`. After editing an already loaded job, unload it with `launchctl bootout` using the same domain/path, then load it again. Include the actual Codex binary directory and any custom `CODEX_HOME` in its environment. XML-escape special characters in paths.

On Windows, create a Task Scheduler task for your own account, triggered at logon. Set **Program/script** to the absolute `.venv\Scripts\python.exe`. Set **Add arguments** to `-m agent_hub.cli --config "C:\Users\me\.config\agent-hub\client.json" watch`. Set **Start in** to the repository directory, select restart on failure, and prevent concurrent instances. The scheduled task needs the provider's actual profile environment and Codex executable on its `PATH`. A token file avoids dependence on an interactive PowerShell environment.

## Source adapters and backfill

| Source | Implemented behavior | Fidelity boundary |
| --- | --- | --- |
| Codex native JSONL | Read complete records, derive source session/cwd, retain unknown record types | Version-dependent local format; separately stored artifacts are not fetched |
| Codex app-server v2 | Read persisted thread metadata and full paginated turns; postpone active turns | Returned API item JSON, not byte recovery of an original transcript file |
| Claude native JSONL | Read parent and child transcripts, preserve complete record strings | External images, attachments, and spilled tool-output files are not copied |
| Generic JSONL | Explicit `--client jsonl`, one JSON record per event | Requires a deliberate project assignment or source cwd mapping |
| T3 diagnostic logs | No importer | Truncated provider diagnostics are insufficient for a faithful conversation archive |

### Native JSONL

Agent Hub does not sweep all home directories by default. Hooks supply sources during normal work. To backfill or recover after missed hooks, select specific files or explicit capture roots:

```bash
agent-hub ingest /absolute/session.jsonl
agent-hub ingest /absolute/selected-history-directory --recursive --queue
agent-hub configure --capture-path "$HOME/.claude/projects"
agent-hub watch --once
```

The [Claude session documentation](https://code.claude.com/docs/en/agent-sdk/sessions) describes per-project JSONL storage under the Claude configuration directory; custom profiles and persistence settings can change availability. The [Claude directory guide](https://code.claude.com/docs/en/claude-directory) describes external artifacts and retention. Archive while source files are available. A conventional legacy Codex directory is `$CODEX_HOME/sessions`, but verify that your installed version still writes JSONL before adding it.

The watcher resolves transcript `cwd` through your mappings. Configured roots authorize discovery, while mappings decide whether a discovered session can upload. A symlink outside a configured directory root is skipped. Missing files, unsupported auto-detection, malformed complete lines, mapping failures, and upload rejections remain visible in the queue.

Each accepted complete JSONL record retains its exact decoded UTF-8 JSON text, including internal spacing, Unicode, and unknown fields. Line delimiters are not part of event `raw`. Blank separator lines affect record ordinals but do not create events. An unterminated final line is deferred while watching; use `ingest --final` only for a finished export. Malformed complete records produce a visible error and are never silently discarded. This is exact record recovery, not byte-for-byte reconstruction of the entire original file or external attachments.

### Parser versions (0.1.9)

A transcript keeps the parser version its session was first captured with, so a replay after a lost checkpoint reproduces the archived text exactly. Sessions captured before 0.1.9 stay on version 1. New sessions use version 2, which corrects roles and searchable text:

| Client | Record | Version 1 | Version 2 |
| --- | --- | --- | --- |
| Codex | `event_msg` copy of a user, assistant or reasoning message | Second copy with the same text | `system` placeholder; the `response_item` keeps the text |
| Codex | Injected `# AGENTS.md …` or `<environment_context>` user item | `user` | `system`, text kept |
| Codex | `custom_tool_call` (`apply_patch`), `local_shell_call`, `web_search_call` | Tool name only | Name plus patch, command or query |
| Claude Code | `isMeta` or `isCompactSummary` user record | `user` | `system`, text kept |
| Claude Code | Subagent (`isSidechain`) prompt | `user` | `assistant` (the parent agent wrote it) |
| Claude Code | Prompt typed while busy (`queued_command` attachment) | Unsupported `system` record | `user`, its prompt |
| Claude Code | `<local-command-stdout>`/`<bash-stdout>` output | `user` | `tool` |

Each file's version is stored in its local checkpoint. When a new file's session already exists on the server under version 1 (a lost checkpoint, or the same transcript found again), the server reports a metadata conflict and the file is read again with version 1, so every record matches as a duplicate. A moved or archived transcript (a changed `source_path`) is the same session and no longer conflicts. Temporary-chat detection reads the user's own words from these records whatever their stored role.

### Codex persisted API history

The inspected Codex CLI was `0.158.0`; its own CLI exposes `migrate-rollouts`, and its generated schemas expose paginated history. Agent Hub starts `codex app-server --stdio`, initializes the protocol, calls `thread/read` without resuming, then calls experimental `thread/turns/list` with `itemsView: full` and ascending pagination. Unsupported pagination methods can fall back to the older full-turn `thread/read` response. See [the native app-server documentation](https://developers.openai.com/codex/app-server).

```bash
agent-hub ingest --client codex-app-server --thread NATIVE_THREAD_ID --codex-bin /absolute/path/to/codex
```

A Codex hook with a null transcript path queues this export automatically using its native session ID. The watcher must find the same installed Codex executable and `CODEX_HOME` as the provider. It exports persisted completed, failed, or interrupted turns; mutable in-progress turns remain pending. No model turn, session resume, login, or subscription is requested by this adapter.

The API stream uses session identity `NATIVE_THREAD_ID:app-server-v2`, distinct from native JSONL. Both may contain the same conversation in different representations; there is no heuristic merge across those surfaces. Prefer one capture surface for a session. Tool commands, outputs, MCP names/arguments/results, and dynamic tool results are normalized for search while the complete returned item JSON is retained.

### Identity, retries, and source changes

Event IDs derive from client, machine, session, and native item identity or original record ordinal. IDs do not derive from content, so editing a previously captured record cannot masquerade as new independent evidence. The server detects conflicting content. A local prefix checksum also blocks rewritten or truncated source files.

The uploader checkpoints only acknowledged records. A lost response replays the same IDs, allowing server deduplication. Queue generations prevent an old upload completion from deleting a newly queued update. Queue/checkpoint state is separated by server URL and machine ID. Cross-machine imports remain separate provenance streams, even if someone copies an identical native transcript to another computer.

Preserve a rewritten source for review. A deliberate import with a new `--session-id` provides explicit recovery:

```bash
agent-hub ingest /absolute/reviewed-session.jsonl --session-id reviewed-generation-2 --project atlas --final
```

Moving the same native source to another path may conflict with immutable source-path metadata. Keep original paths during normal capture; use an explicit new identity for a deliberate independent import. Oversized records are rejected visibly under server limits, retained for retry, and never silently truncated to fit ingestion.

## T3 Code deployment

T3's official [Codex provider guide](https://github.com/pingdotgg/t3code/blob/main/docs/user/providers-codex.md) and [Claude provider guide](https://github.com/pingdotgg/t3code/blob/main/docs/user/providers-claude.md) describe reuse of the provider's configuration and credentials, including isolated profiles. Its [architecture guide](https://github.com/pingdotgg/t3code/blob/main/docs/internals/overview.md) places execution on the owning server.

Install Agent Hub, configure the appropriate provider home, and run its watcher **on that host**. For T3 on a remote workstation, your phone or browser is only the control surface. T3's own [`/mcp` endpoint](https://github.com/pingdotgg/t3code/blob/main/docs/user/outside-agents.md) lets outside agents control T3; it is not a memory-server registration setting for T3's providers. Provider diagnostics described in [T3 internals](https://github.com/pingdotgg/t3code/blob/main/docs/internals/providers.md) are not treated as a full native transcript.

`agent-hub setup --clients codex t3` configures Codex and reports the T3 inheritance requirement. A selection of `--clients t3` alone makes no files. Verify memory tool availability and lifecycle capture inside the actual T3 provider/profile after installation; provider inheritance is supported by its documentation, but a live T3 session was not exercised during this build.

## Troubleshooting and verification boundary

| Symptom | Check |
| --- | --- |
| Tools absent | Restart the client; inspect `/mcp`; confirm the actual provider home and absolute Python path |
| Tools connect, history never grows | Start the watcher, inspect `/hooks` trust, run `doctor`, and test a mapped synthetic session |
| HTTP 401/403 | Check the active token environment variable, token file, revocation, and server project permissions |
| Unmapped session | Add the correct cwd/worktree mapping; inspect existing project assignment before changing it |
| Codex thread cannot export | Check watcher PATH, CODEX_HOME, installed protocol version, and whether the thread is persisted |
| Jobs under `source_gone` | The source was never saved or was removed; `agent-hub queue list` shows them, `queue requeue` retries one that has returned |
| Partial final line remains pending | Let the writer finish; use `--final` only for an intentionally finished export |
| Mutation or metadata conflict | Preserve the source and review its identity; do not delete checkpoints to bypass a conflict |
| SOCKS proxy initialization error | Install the optional `socksio` transport dependency when your environment requires a SOCKS proxy; loopback service traffic bypasses external proxies |

`doctor --offline` checks local credential availability, versions on PATH, and queue status without contacting the memory service. Regular `doctor` also checks unauthenticated health and authorized projects. Error output does not print tokens or transcript contents.

Tests use synthetic Codex/Claude fixtures, append/retry/conflict scenarios, offline state, setup preservation, Unicode/Windows path cases, a synthetic app-server subprocess, and a real official-SDK stdio-to-HTTP round trip. No real personal transcript was captured during development. Native Claude lifecycle behavior, native Windows/macOS execution, and live T3 provider delivery require the installation check above. Client formats and experimental protocol fields can change; recheck them after upgrades rather than assuming every future version is compatible.

Primary client documentation and source were checked on 2026-10-07. The broader project's executed checks are recorded in [VALIDATION.md](VALIDATION.md).


## T3 saved-history capture (0.1.5)

Native Codex capture covers Codex provider transcripts, not every T3 provider or
T3-owned message/activity. Run this additional reader on the **T3 server host**:

```sh
agent-hub --config /absolute/client.json sync-t3 \
  --database /home/USER/.t3/userdata/state.sqlite \
  --checkpoint /home/USER/.config/agent-hub/t3-checkpoint.json
```

Use `--once` for an acceptance pass. The first pass imports saved thread events;
subsequent passes poll every ten seconds, up to 200 source events per pass. Use a
service supervisor with restart-on-failure. A database outage, schema mismatch,
server rejection or reset is visible and does not advance the checkpoint past
unacknowledged history. Preserve the checkpoint when diagnosing failures.

This adapter is qualified against T3 **0.0.45's v1 orchestration_events schema**.
It reads that event table through a bounded read-only SQLite snapshot, releasing
the snapshot before HTTP calls. Source event IDs, sequence, original JSON strings,
thread IDs, model/provider changes, message revisions and activities are retained.
A thread remains one logical T3 session across provider changes. It excludes auth
and runtime payloads. Privacy linking additionally extracts only native thread IDs
from the provider resume cursor. It archives persisted events, not hidden prompts,
unsaved output, or attachment binary files. Future T3 schema/event-retention
changes require adapter review; do not delete checkpoints to hide a reset.

T3 and native provider capture are separate attributed sources; the same visible
answer may appear in both. They are not falsely merged or counted as independent
facts. T3 capture covers saved Claude/Grok/Cursor events even without a native
parser for those providers. It does not install a provider or prove its inference
works. Standalone Grok and Cursor archive import are not implemented here.

`scripts/watch-local.py` supplies a changed-file watcher for Codex/Claude JSONL
roots plus the durable native hook queue. Its first pass baselines old files;
new or resumed files are captured. Configure roots belonging to the intended OS
user. Historical bulk import remains explicit. If the process is down and a
source is deleted before capture, that source cannot be recovered from a cursor.

A home profile can use one default project with `strict_scope: false`, no path
allowlist and no domain lock. This allows unrelated home projects without prompts
or directory guards. Authentication and immutable source protection still apply.
Work can use an independent server/profile. This permissive home deployment does
not automatically exclude employer files opened in local native sessions.

See [temporary chats, exclusions and historical backfill](TEMPORARY_CHATS.md).
