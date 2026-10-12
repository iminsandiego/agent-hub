#!/usr/bin/env bash
# Run from any directory after cloning your own Agent Hub repository.
set -euo pipefail
agent_hub_repo="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
agent_hub_python="${AGENT_HUB_PYTHON:-python3}"
"$agent_hub_python" -c 'import sys; assert sys.version_info >= (3, 11), "Python 3.11+ is required"'
if [[ ! -x "$agent_hub_repo/.venv/bin/python" ]]; then
  "$agent_hub_python" -m venv "$agent_hub_repo/.venv"
fi
"$agent_hub_repo/.venv/bin/python" -m pip install -r "$agent_hub_repo/requirements.lock"
"$agent_hub_repo/.venv/bin/python" -m pip install --no-deps -e "$agent_hub_repo"
"$agent_hub_repo/.venv/bin/python" -m agent_hub.cli configure "$@"
"$agent_hub_repo/.venv/bin/python" -m agent_hub.cli setup --clients codex claude
"$agent_hub_repo/.venv/bin/python" -m agent_hub.cli doctor
echo "Setup complete. Start capture with: $agent_hub_repo/.venv/bin/agent-hub watch"
