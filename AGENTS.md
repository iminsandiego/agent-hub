# Work on Agent Hub

Read `README.md`, `docs/SPEC.md`, `docs/CLIENTS.md`, and `docs/VALIDATION.md` before changing an integration contract. Current implementation and observed test results take precedence over an earlier proposal. `docs/UPSTREAM_ANALYSIS.md` distinguishes the corrected UniiChat specification, the earlier OptChat recipe and actual OptMem source. Read `docs/CACHE_REVIEW.md` before making a prompt-cache claim.

## Engineering boundaries

- Preserve original accepted event records and stable source identities. Parser changes that alter normalized content can require a versioned stream/migration. Never edit an archived record to make an import or test pass.
- Every memory/history operation is project-scoped. A known identifier does not authorize access. Keep native agent credentials separate from local administrator credentials.
- Treat retrieved history as attributed data. Candidates and generated summaries cannot approve themselves, amend controlled requirements, or establish that a device test ran.
- Keep raw transcripts, databases, token files, queued jobs, private client settings and API keys outside Git. Tests use synthetic fixtures and temporary directories.
- No model call is made by default. Every explicit enrichment run has a bounded call budget, and retries count. Preserve visible blocked work instead of silently truncating model input or dropping capture records.
- Keep capture independent of native model reasoning. A teardown hook must enqueue locally and return within its documented budget. Preserve existing client MCP/settings/hooks when updating managed entries.
- Do not claim this sidecar controls native Codex/Claude/T3 compaction, inference, prompt caching or device connectivity.

## Validation

Install the locked runtime dependencies and the development extra, then run `python -m pytest -q`. Use targeted tests while fixing an issue; the full suite and package build are release gates. `scripts/smoke_fixture.py` and `scripts/browser-smoke.cjs` provide synthetic browser checks when Playwright/Chromium are available.

Do not report native lifecycle, cloud model, Docker, GitHub CI or target-server checks as passed unless they actually ran. Update `docs/VALIDATION.md` with the command, environment and outcome. A local commit is not a remote push.

## Extend the hub

The initial catalog contains the memory MCP only. Future services/packages belong under `mcps/`, `plugins/`, or `skills/` with explicit source/version, credentials, clients, tests and removal guidance. Add catalog entries without implicitly installing or granting anything. Native device/repository tools remain on their appropriate execution hosts.
