# Machine profiles

Profiles describe the desired set of integrations and project mappings for a class of computer. They are templates, not runtime credentials. The initial bootstrap/configure flow accepts explicit mappings and capture paths; automatic profile application is not yet implemented.

For example, a test-bench Windows profile could map several product/test repositories to `atlas`, enable the memory MCP in Codex and Claude Code, and later include separately reviewed GUI-test/robot/device integrations. A personal laptop can receive only `personal` and `harbor` scopes. The server token remains the authorization boundary.

Never put a token or transcript inside a profile. Refer to token environment-variable names or private files supplied during that computer's setup.

The home/work example JSON files are templates only. Replace every sample path and hostname, provision a matching token, and install them into separate native profiles. Neither example is an installed configuration. See [domain setup](../docs/DOMAINS_AND_INGESTION.md).
