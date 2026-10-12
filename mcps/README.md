# Additional MCP services

Keep future in-repository implementations under `mcps/<service>/` with their own dependencies, tests, and setup guide. Add one reviewed entry to `src/agent_hub/catalog.json`. External integrations should name their upstream source and a pinned version or commit.

Each integration should document its execution host, required credentials, allowed projects, read/write capabilities, and uninstall procedure. Device-access tools run where the device can actually be reached. Register them directly in the intended native client; do not route their ordinary tool traffic through the memory service.

Adding an inventory entry does not install code or grant access. The initial setup command installs only the built-in memory integration.
