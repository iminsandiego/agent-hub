# Agent Hub 0.1.14

Optional private skills repository for `agent-hub setup`. No server, archive, identity or normalized text changes; the server needs no restart.

**Setup can install your skills.** The first interactive `agent-hub setup` asks for a skills repository (SSH or HTTPS git URL, or an absolute local path) and saves the answer as `skills_repo` in `client.json`; a blank answer is saved as declined and is not asked again. `--skills-repo URL_OR_PATH` sets it and `--skills-repo none` declines. For a URL, setup clones it beside `client.json` (`skills-repo/`) or fast-forwards an existing clone, then runs the repository's root `install.sh` (`--dry-run` during a dry run). Git never prompts for credentials. Option-like, `ext::` and `file://` sources are rejected.

**Skills never block client setup.** The skills step runs after the MCP and hook setup. A missing, unreachable or failing repository is reported under `skills` in the setup output and makes setup exit 1. Noninteractive runs and dry runs never prompt. Installers are not run on Windows.

`agent-hub configure` keeps an existing `skills_repo`. See `skills/README.md` for what a repository's `install.sh` should do.
