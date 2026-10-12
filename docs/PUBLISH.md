# Publish the repository to GitHub

Target: a new **private** repository named `agent-hub` in the verified GitHub account `iminsandiego`. The name is a working default and can be changed at publication. The runtime data directory stays on your server, outside Git.

## With the GitHub CLI

Install Git and the official [GitHub CLI](https://cli.github.com/), authenticate to the account that should own the repository, and verify that account before publication:

```bash
gh auth status
gh api user --jq .login
```

From the repository root:

```bash
bash scripts/publish-github.sh agent-hub
```

The helper uses the authenticated personal account, refuses an existing origin/repository, creates the remote privately, and pushes without force. It uses existing committed history when present; a downloaded source archive is initialized with only the known application paths. It refuses a dirty checkout after initialization so unreviewed edits are not silently committed during publication.

On Windows, use Git Bash for that helper or run the equivalent commands in PowerShell after initializing/committing the source checkout:

```powershell
$account = gh api user --jq .login
gh repo create "$account/agent-hub" --private --source . --remote origin --push
gh repo view "$account/agent-hub" --json url,visibility
```

Verify `visibility` is `PRIVATE`, check that the remote branch matches the local commit, and inspect the CI run. The supplied CI workflow is not a recorded pass until GitHub executes it. For a different existing repository, set the correct remote and use an ordinary non-forced push after inspecting its history; the create helper intentionally refuses to guess.

## What to keep out of Git

Token files, native client settings, raw transcripts, archive/worker/auth databases, upload queues, cached contexts, model API keys, and host-specific settings are runtime data. The ignore rules and publication helper protect the known paths, but reviewing `git status` and the committed file list remains part of publishing any repository.

## Reproducible new installs

The installation commands target `iminsandiego/agent-hub`. If publishing under another account or name, update those clone URLs to match the verified remote. New computers clone that same repository, install the locked package, receive a scoped credential, and run the documented client setup. Existing computers update through ordinary reviewed Git commits and package upgrades; memory remains on the server.
