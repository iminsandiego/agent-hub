# Skills

Agent Hub does not ship personal skills. Keep your own skills in a repository you
control (usually private) and let `agent-hub setup` keep each computer in step
with it. The repository's address lives only in that computer's `client.json`,
never in this repository.

## How setup uses a skills repository

1. The first interactive `agent-hub setup` asks for a skills repository: an SSH
   or HTTPS git URL, or an absolute path to a checkout you manage yourself. A
   blank answer is remembered as declined. `--skills-repo URL_OR_PATH` sets or
   changes it; `--skills-repo none` declines. Noninteractive runs and
   `--dry-run` never prompt.
2. For a URL, setup clones the repository to `skills-repo/` beside
   `client.json` on first run, then fast-forwards it (`git pull --ff-only`) on
   later runs. It never prompts for git credentials; use an SSH key or a
   credential helper that already has access. A local path is used as is and
   is not pulled.
3. Setup then runs the repository's root `install.sh` (with `--dry-run` during
   `agent-hub setup --dry-run`) and includes its output in the setup report.
4. Skills run last. A missing, unreachable or failing repository is reported
   under `skills` and makes setup exit 1, after the MCP and hook setup has
   already completed.

Setup does not read, list or validate the skills themselves; `install.sh` owns
that. Installers are POSIX shell scripts and are not run on Windows.

## What install.sh should do

Running a repository's `install.sh` runs code from that repository, so point
setup only at a repository you own. A good installer:

- links or copies each skill folder (a folder with a `SKILL.md`) into
  `~/.claude/skills/` and `~/.codex/skills/`, which T3 Code's Claude and Codex
  providers also use;
- leaves skills it does not manage alone and backs up anything it replaces;
- supports `--dry-run`;
- contains no tokens, transcripts or other secrets.

Project-specific skills belong in that project's own repository
(`.agents/skills/` for Codex, `.claude/skills/` for Claude Code), not in a
personal skills repository.

Do not store historical conversation memory in skill files. A skill describes
how to do a repeatable task; memory records what was previously said or done.
