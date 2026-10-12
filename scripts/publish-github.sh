#!/usr/bin/env bash
set -euo pipefail
repo_name="${1:-agent-hub}"
if [[ ! "$repo_name" =~ ^[A-Za-z0-9][A-Za-z0-9._-]*$ ]]; then
  echo "Repository name must be a single GitHub repository name." >&2
  exit 2
fi
command -v gh >/dev/null || { echo "Install the GitHub CLI first: https://cli.github.com/" >&2; exit 2; }
command -v git >/dev/null || { echo "Install Git first." >&2; exit 2; }
repo_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"
account="$(gh api user --jq .login)"
[[ -n "$account" ]] || { echo "GitHub account could not be resolved." >&2; exit 2; }
if gh repo view "$account/$repo_name" --json nameWithOwner >/dev/null 2>&1; then
  echo "Repository already exists: $account/$repo_name. No changes were pushed." >&2
  exit 2
fi
if [[ ! -d .git ]]; then
  git init -b main
  git add README.md NOTICE.md AGENTS.md CLAUDE.md MANIFEST.in pyproject.toml requirements.lock .gitignore .gitattributes .dockerignore .github src tests docs deploy scripts mcps plugins skills profiles
  git -c user.name="Agent Hub Build" -c user.email="agent-hub@localhost" commit -m "Build initial shared agent memory service"
fi
if git remote get-url origin >/dev/null 2>&1; then
  echo "This checkout already has an origin. Inspect it and push through the normal Git workflow." >&2
  exit 2
fi
if [[ -n "$(git status --porcelain)" ]]; then
  echo "The checkout has uncommitted changes. Review and commit them before publication." >&2
  exit 2
fi
gh repo create "$account/$repo_name" --private --source "$repo_root" --remote origin --push
gh repo view "$account/$repo_name" --json url,visibility
git ls-remote origin HEAD
