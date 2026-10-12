# Agent Hub 0.1.8

Version 0.1.7 was not released; this follows 0.1.6.

**Memory browser redesign.** A project home, search with highlighted matches, session transcripts, a record and note inspector, an agent-context preview, a summary-tree timeline and setup steps for connecting another computer. Captured content is still rendered as text and no third-party code is loaded.

**Password sign-in for the browser.** Run `agent-hub set-password` on the server once, then sign in with that password. The browser stays signed in for 30 days through an `HttpOnly`, `SameSite=Strict` session cookie that reaches the REST API only, never MCP. Wrong passwords are throttled; changing the password or `--disable` signs out every browser. Agent tokens are unchanged, and pasting a token still works.

**Tunnel ports.** A page opened through an SSH tunnel on any local port can make changes: the service accepts a browser `Origin` naming the same allowed host and port as the request. `/health` reports the server domain and whether password sign-in is set up. Session lists include a short preview of the first typed request and the source time span.

Upgrade: install the new version, restart the service, then run `agent-hub set-password`. The authentication database gains two tables on first start; existing tokens, archives and identities are unchanged.
