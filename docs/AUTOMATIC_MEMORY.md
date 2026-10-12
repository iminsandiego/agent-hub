# Automatic memory across native clients and T3

Verified October 12, 2026 with Agent Hub 0.1.5 and T3 0.0.45. The home deployment
uses one project, `home`, without strict domain or directory guards. Separate
work storage remains a separate installation, not a content classifier.

## Capture and retrieval are separate

Run native watchers on the machines that own Codex and Claude transcripts, and
`sync-t3` on the machine that owns T3's database. T3's saved events cover providers
and provider changes that native Codex history alone cannot cover. Native and T3
copies retain their source identities; repeated text is not independent evidence.
The home installation captures Mac/VM native Codex/Claude plus VM T3. It does not
capture the Mac's T3 or Cursor stores or connect to the work computer.

Retrieval requires an Agent Hub MCP server in each provider's actual execution
profile and instructions to use it. T3 launches providers on the selected
environment; setting up the Mac does not configure the VM. MCP registration does
not prove tool execution. Retain T3's normal approval mode for other actions.

## Install instructions without replacing existing guidance

After the normal [client setup](CLIENTS.md), merge the block from
[the instruction template](../templates/AUTOMATIC_MEMORY.md) into these files on
the provider's execution host, preserving all existing guidance:

| Provider | User instructions |
|---|---|
| Codex | `~/.codex/AGENTS.md`; respect an existing `AGENTS.override.md` |
| Claude Code | `~/.claude/CLAUDE.md` |
| Grok Build | `~/.grok/AGENTS.md` |

Replace `home` with the project authorized by that profile. Custom provider homes
require their actual equivalent paths. Back up changed files privately and
restart or begin a new provider chat so the instructions are loaded. Existing
chat context may retain older instructions. This is instruction-driven retrieval,
not guaranteed injection of all history into every prompt.

Allow only Agent Hub's four read tools without repeated approval. For the server
name `agent-hub`, merge Codex's per-tool `approval_mode = "auto"` entries under
`mcp_servers.agent-hub.tools.memory_context`, `memory_search`, `memory_get` and
`memory_zoom`. Claude's existing `permissions.allow` list receives the four exact
names `mcp__agent-hub__memory_context`, `mcp__agent-hub__memory_search`,
`mcp__agent-hub__memory_get` and `mcp__agent-hub__memory_zoom`.
Do not automatically approve `memory_note`, administrative reviews or unrelated
tools. Keep provider tokens and original configuration backups outside Git.

## Grok Build on T3 0.0.45

Grok 1.0.50 supports `~/.grok/config.toml` with a stdio MCP server:

```toml
[mcp_servers.agent-hub]
command = "/absolute/agent-hub/venv/bin/python"
args = ["-m", "agent_hub.cli", "--config", "/absolute/private/client.json", "mcp"]
enabled = true
```

On the home VM, T3's Grok binary path points to a small executable wrapper:

```sh
#!/bin/sh
exec /absolute/path/to/grok \
  --allow 'MCPTool(agent-hub__memory_context)' \
  --allow 'MCPTool(agent-hub__memory_search)' \
  --allow 'MCPTool(agent-hub__memory_get)' \
  --allow 'MCPTool(agent-hub__memory_zoom)' "$@"
```

This preserves arguments supplied by T3, including Supervised mode. Verify the
installed Grok version's syntax before reusing it. The home VM's existing Grok
login refreshed through native inference; credentials were not copied to the Mac.
Standalone Grok transcripts are not watched by this deployment; VM T3 events are.

## Qualification and gaps

Three fresh, real VM T3 chats using Codex GPT 6.1 Sol, Claude Sonnet 5.5 and Grok
4.7 recalled a synthetic value present only in Agent Hub. The ordinary question
did not contain the answer or a reminder to use memory. Saved tool activities and
assistant messages were verified, with Supervised mode retained. A subsequent
Claude T3 chat retrieved decisions and newer status from the active Mac Codex
conversation. An initial lookup quoted an older status; the follow-up found newer
evidence. Instructions now explicitly call for newer dated evidence when status
changes. Retrieval remains fallible and history is not live service proof.

Cursor, OpenCode and Antigravity are disabled/unqualified here. The Mac has no
Grok CLI. T3 provider switching, generic agent delegation and live Cursor
inference are not qualified by these tests. Later Windows/work Cursor imports
need version-specific, source-preserving adapters.

## Temporary chats and deletion

Version 0.1.5 has no per-chat temporary mode or selective purge. Rejecting a
candidate note does not erase its underlying transcript. Deleting a native/T3
chat does not delete Agent Hub's archived copy. Watchers can import resumed files;
backups and local caches may retain older copies.

Recommended future controls are a temporary chat that may retrieve memory but
does not ingest, and an explicit Forget this chat action. Exclusion must cover
both T3 and native copies before capture. Forgetting must remove raw and indexed
records, derived summaries/notes and caches, preserve a minimal non-content
tombstone to prevent re-import, and define backup expiration/restore behavior.
This design is not implemented or enabled. Do not assume a title, a request in
chat or deleting the source creates a temporary chat. No history was deleted.
