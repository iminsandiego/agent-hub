For new home/work deployments, first read [domain separation](DOMAINS_AND_INGESTION.md). Deploy this guide independently in each approved domain; do not share data volumes, credentials or backups.

# Install the memory server

The server runs once on your always-on host. Every agent computer connects to this same service; do not give each computer a separate copy of the memory database.

## Option A: Python on Linux

Start with Python 3.11+ and a checkout at `$HOME/agent-hub`. The tested runtime uses Python 3.12; see `VALIDATION.md` for actual platform coverage.

```bash
cd "$HOME/agent-hub"
python3 -m venv .venv
.venv/bin/python -m pip install --require-hashes -r requirements.lock
.venv/bin/python -m pip install --no-deps -e .
.venv/bin/agent-hub init-server --data-dir "$HOME/.local/share/agent-hub" --project atlas --project harbor --project personal
```

Initialization writes `server.json` and `admin.token` into the data directory and creates the requested projects. It prints paths and a token identifier, not the secret. If you initialize again, existing data and credentials are preserved and the command refuses to replace them.

Start the service:

```bash
.venv/bin/agent-hub serve --server-config "$HOME/.local/share/agent-hub/server.json"
```

Visit `http://127.0.0.1:8765` on the server, or establish an SSH tunnel from your computer:

```bash
ssh -L 8765:127.0.0.1:8765 YOUR_SERVER
```

The browser at `http://127.0.0.1:8765` will then reach the service through SSH. Any free local port works, for example `ssh -L 18765:127.0.0.1:8765 YOUR_SERVER` and `http://127.0.0.1:18765`: the service accepts a browser `Origin` that names the same allowed host and port the request was sent to, so tunnelled pages can review notes and forget chats without listing every local port. The sign-in screen shows the server version and domain behind the address.

Set the browser password once on the server (it prompts twice and never echoes):

```bash
.venv/bin/agent-hub set-password --server-config "$HOME/.local/share/agent-hub/server.json"
```

Then sign in at the browser with that password; you stay signed in on that browser for 30 days or until you sign out. Run the command again to change a forgotten password, which also signs out every browser, or pass `--disable` to turn password sign-in off. With Docker Compose, run `docker compose exec memory agent-hub set-password --data-dir /data`. A pasted token still works as a fallback (choose **Use an access token instead**); obtain one from its private file on the server using your normal trusted administrative channel. An SSH tunnel also provides a simple initial client endpoint without publishing an HTTP service to the LAN.

### Keep the service running

The sample user service assumes the checkout is at `$HOME/agent-hub`. Adjust `WorkingDirectory` and `ExecStart` if it is elsewhere.

```bash
mkdir -p "$HOME/.config/systemd/user"
cp deploy/agent-hub.service deploy/agent-hub-worker@.service "$HOME/.config/systemd/user/"
systemctl --user daemon-reload
systemctl --user enable --now agent-hub.service
systemctl --user status agent-hub.service
```

For a user service to run while you are logged out, an administrator can enable lingering for that user with `loginctl enable-linger USERNAME`. A dedicated system service is also possible; adapt the same command and private data directory rather than running as root.

Enable local candidate extraction separately for each project:

```bash
systemctl --user enable --now agent-hub-worker@atlas.service
systemctl --user enable --now agent-hub-worker@harbor.service
systemctl --user enable --now agent-hub-worker@personal.service
```

These workers do not call an external model. The binary excerpt tree is already updated transactionally during ingestion; workers add candidate notes from explicit user markers.

## Option B: Docker Compose

The container runs as UID/GID 10001 and stores state in a named volume. It publishes only a host-loopback port. Container bind address `0.0.0.0` is internal to Docker; the Compose host port remains `127.0.0.1:8765`.

```bash
cd "$HOME/agent-hub"
docker compose -f deploy/compose.yaml build
docker compose -f deploy/compose.yaml run --rm memory init-server --data-dir /data --project atlas --project harbor --project personal
docker compose -f deploy/compose.yaml up -d memory
docker compose -f deploy/compose.yaml ps
```

Administrative commands run in the same image and volume:

```bash
docker compose -f deploy/compose.yaml exec memory agent-hub project list --data-dir /data
docker compose -f deploy/compose.yaml exec memory agent-hub token create --data-dir /data --name owner-mac --project atlas --project harbor --output /data/owner-mac.token
```

Retrieve that machine's token through your trusted local administration path, keep it out of terminal transcripts you plan to archive, and place it on the intended computer. Do not use the server administrative token for normal agent access.

The optional Compose worker profile starts one deterministic worker. It defaults to `atlas`; `AGENT_HUB_WORKER_PROJECT` selects another existing project. For several projects, use separate named worker services with the same volume and one explicit project each, or the systemd template on a native installation.

```bash
docker compose -f deploy/compose.yaml --profile worker up -d
```

Docker build/run must be verified on your target host. The validation report says whether a local Docker daemon was available during development; the included CI job is not evidence until it actually runs.

## Add remote HTTPS access

Choose a hostname you control, such as `memory.example.com`, backed by your server's private network or existing reverse proxy. The packaged `deploy/Caddyfile.example` is a starting configuration, not a deployed domain or certificate.

Update these fields in the private `server.json` before restarting:

```json
{
  "allowed_hosts": ["127.0.0.1", "localhost", "[::1]", "memory.example.com"],
  "allowed_origins": ["http://127.0.0.1:8765", "http://localhost:8765", "https://memory.example.com"]
}
```

Preserve the other existing fields, particularly `data_dir`. This is a partial example to merge, not a replacement for the full settings file. Native clients usually send no `Origin`; when a browser does, it must match the explicit allowlist or be the same origin as the allowed `Host` it was sent to. The HTTP `Host` must always match. Do not set wildcard origins or disable TLS verification.

Proxy HTTPS traffic to `127.0.0.1:8765`. The service still needs bearer authentication. A VPN/private-network route protects reachability; it does not replace per-computer authorization. If you use a private CA, install its trust through your operating system or client's supported CA mechanism. For Agent Hub's own client (hooks, `watch`, `ingest` and the stdio MCP gateway), `agent-hub configure --ca-file /path/to/hub-ca.crt` saves `ca_file` in `client.json`; the client then trusts that CA alone for the service URL, without changing the process's other TLS or setting `SSL_CERT_FILE`. Native HTTP MCP clients need the CA in their own mechanism (for Claude Code, `NODE_EXTRA_CA_CERTS`). The app does not accept `verify=false` as an installation shortcut.

The native client integration defaults to a local stdio gateway. Its connection to this server is HTTPS REST, avoiding clients that insist on a complete OAuth discovery flow for remote MCP. The service also exposes direct Streamable HTTP `/mcp` for clients that support explicit bearer credentials.

## Issue credentials and connect a computer

Create only the scopes that computer needs:

```bash
.venv/bin/agent-hub token create --data-dir "$HOME/.local/share/agent-hub" --name owner-windows-lab --project atlas --output "$HOME/owner-windows-lab.token"
.venv/bin/agent-hub token create --data-dir "$HOME/.local/share/agent-hub" --name owner-personal-laptop --project personal --project harbor --output "$HOME/owner-personal-laptop.token"
```

Each credential can be revoked independently. Normal client-token creation refuses `*` and does not issue administrative permission. Continue with the exact [new-computer instructions](CLIENTS.md).

## Deployment acceptance

Before considering your server deployment complete, verify from an actual agent computer:

1. HTTPS and authentication work; `agent-hub doctor` reports the expected project list.
2. An unprivileged token cannot access a different project or activate a candidate.
3. A synthetic session uploads, searches correctly, and survives a service restart.
4. The intended native client lists all five memory tools and can retrieve that synthetic event.
5. Supported hooks enqueue after a turn; the watcher process and queue status are visible; disconnect/reconnect recovers the pending upload while its source remains available.
6. A backup restores on a separate empty data directory and original source text matches.

These are target-host checks. Development tests do not substitute for running them against your installed clients and server.

Restore now requires the **current** `--privacy-ledger`; see [restore and forgetting](TEMPORARY_CHATS.md).
