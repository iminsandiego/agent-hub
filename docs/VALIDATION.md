# Validation evidence

## Version 0.1.1 correction review · 8 October 2026 UTC

The cache correction release was checked with **CPython 3.12.14 on Linux x86_64**, using a newly created environment and the unchanged hash-locked runtime dependency set. The complete revised suite passed **236 tests**, with one existing upstream deprecation warning, in **5.44 seconds**. The focused worker/admin run passed **53 tests in 0.81 seconds**.

```bash
PYTHONPATH=src ../.venv-cache-review/bin/python -m pytest tests/test_worker.py tests/test_admin.py -q
PYTHONPATH=src ../.venv-cache-review/bin/python -m pytest -q
git diff --check
```

The new and strengthened regressions exercise the real provider request builder through `httpx.MockTransport`. They establish that the initial request and both shortening retries contain two, four and six messages; the original system/source/context and every preceding message remain an identical prefix; one-, two- and three-call budgets hold; and cumulative history that exceeds the 24,000-character limit is rejected before another HTTP call or counted request. Original events and fallback summaries survive that rejection. The limit counts message-content characters, not tokens or JSON framing.

These checks validate the shortening patch described in [CACHE_REVIEW.md](CACHE_REVIEW.md). They do not measure a provider cache-hit rate, verify the author's simulation, or establish that Agent Hub implements the corrected persisted-view algorithm. No paid model endpoint was called.

The warning remains the Starlette test client's deprecation notice about `httpx`; there were no failing tests. Browser assets, native-client integration code and deployment configuration did not change in this release, so the browser evidence below remains the recorded **0.1.0 run**, not a newly repeated browser test. Native-client, real-provider, remote CI and permanent-host checks listed at the end remain pending.

### Version 0.1.1 package verification

The standard isolated build produced `agent_hub-0.1.1.tar.gz` and `agent_hub-0.1.1-py3-none-any.whl`. A second new virtual environment received the runtime dependencies from `requirements.lock` with hash checking, then the wheel without dependency resolution. `pip check` reported **No broken requirements found**; the installed CLI help succeeded; catalog validation returned **valid: true, entries: 1**.

```bash
../.venv-cache-review/bin/python -m build
uv venv --seed ../.venv-cache-wheel
uv pip install --python ../.venv-cache-wheel/bin/python --require-hashes -r requirements.lock
uv pip install --python ../.venv-cache-wheel/bin/python --no-deps dist/agent_hub-0.1.1-py3-none-any.whl
../.venv-cache-wheel/bin/python -m pip check
../.venv-cache-wheel/bin/agent-hub catalog validate
../.venv-cache-wheel/bin/agent-hub --help
```

A smoke program imported the module from that environment's `site-packages`, confirmed package metadata and `__version__` both equal `0.1.1`, and read the packaged HTML, JavaScript, CSS and catalog. It then exercised the installed `LLMProvider` through `httpx.MockTransport` and verified an exact four-message request containing the original system/source plus the appended assistant/correction pair. This establishes that the checked wheel contains the fix without making an external model call. Final documentation is included in the release packaging rebuild; no application behavior changed after the 236-test run.

## Version 0.1.0 original delivery · checked 7 October 2026

The completed development run used **CPython 3.12.14 on Linux x86_64**. The complete Python suite passed **233 tests**, with one upstream deprecation warning, in **5.30 seconds**. A separate real browser run passed 13 checks against the running application with synthetic data. These results establish the behavior exercised below; they do not establish deployment on the owner's permanent server or certification of every native client installation.

## Executed checks

| Check | Result | Scope |
| --- | --- | --- |
| Complete Python test suite | **233 passed; 1 warning** | All six test modules in this checkout |
| Python syntax compilation | **22 files passed** | Source, tests and Python helper scripts compiled in memory |
| Bash syntax | **Passed** | `scripts/bootstrap.sh`, `scripts/publish-github.sh` |
| JavaScript syntax | **Passed** | Browser application and Playwright smoke script |
| Integration catalog | **Valid; 1 entry** | Packaged catalog parses and passes its schema checks |
| Real browser smoke | **13 checks passed** | Headless Chromium 153, desktop and mobile viewports |
| Release package build/install | **Passed** | Wheel and source distribution built; wheel installed in an independent environment with locked runtime dependencies; actual CLI and HTTP service exercised |

The single Python-suite warning was `StarletteDeprecationWarning`: the installed Starlette test client warns about its use of `httpx`. It was a warning, not a failing test. The runtime dependency set remains recorded in `requirements.lock`.

### Commands executed

These commands ran from the repository root. In the development workspace, its interpreter was in the sibling environment at `../.venv/bin/python`. A new installation should substitute the path to its own virtual environment.

```bash
../.venv/bin/python -m pytest -q
../.venv/bin/python -m agent_hub.cli catalog validate
bash -n scripts/bootstrap.sh scripts/publish-github.sh
node --check src/agent_hub/static/app.js
node --check scripts/browser-smoke.cjs
```

The full-suite terminal result was:

```text
233 passed, 1 warning in 5.30s
```

Python syntax was checked without writing compiled files:

```bash
../.venv/bin/python -c 'from pathlib import Path; paths = sorted(set(Path("src").rglob("*.py")) | set(Path("tests").rglob("*.py")) | set(Path("scripts").rglob("*.py"))); [compile(path.read_bytes(), str(path), "exec") for path in paths]; print(f"Compiled {len(paths)} Python files in memory; no syntax errors")'
```

Result: `Compiled 22 Python files in memory; no syntax errors`.

## What the Python tests exercise

The suite contains behavioral and transport tests, not only import or configuration checks:

- **Archive and tree:** exact captured-record retrieval, Unicode, source timestamps, idempotent replay, conflicting-content rollback, contiguous project sequences, concurrent writers, dyadic coverage, zoom, rebuild and semantic completion fingerprints.
- **Authorization and evidence:** project filtering and identifier isolation, token revocation, simultaneous request identities, denied ingestion/review, cross-project source rejection, explicit administrative review, hostile historical text as quoted data, request bounds, and the actual official-SDK Streamable HTTP handler.
- **Retrieval limits:** event text/raw pagination, session and leaf previews, source downloads, context budgets, continuation information and logical-result size guards.
- **Client capture and setup:** Codex/Claude fixtures, incomplete and malformed JSONL, unknown record types, append checkpoints and rewrite conflicts, offline queues and stale drainers, cache scope/expiry, credential preservation, mapping boundaries, setup idempotence, settings preservation and Windows path cases.
- **Client transports:** a synthetic app-server subprocess, an official-SDK stdio-to-HTTP round trip, and the client against the authenticated application service for incremental capture, context, search, paging and project denial.
- **Administration and enrichment:** initialization, scoped credentials, backup/restore, private files, deterministic extraction, no model calls by default, bounded provider calls, invalid outputs, fabricated references, blocked oversized inputs, restartable checkpoints and retained fallbacks. Model-provider responses are test doubles; no paid provider validation is implied.

The relevant files are `tests/test_store.py`, `tests/test_tree.py`, `tests/test_security.py`, `tests/test_clients.py`, `tests/test_admin.py` and `tests/test_worker.py`. [IMPLEMENTATION_REVIEW.md](IMPLEMENTATION_REVIEW.md) records the concrete issues found and resolved during development.

## Real browser evidence

The browser runner exercised the actual application using `scripts/smoke_fixture.py` and `scripts/browser-smoke.cjs`. The temporary fixture contained 12 synthetic records, an active note, a candidate, and a separate empty project. No personal transcript or production credential was used.

The recorded run used **headless Chromium 153**, with a **1440 × 1000 desktop viewport** and a **390 × 844 mobile viewport**. Its result is recorded in [evidence/browser-smoke.json](evidence/browser-smoke.json), with the screenshot directory made relative for distribution. This is a desktop browser resized to a mobile viewport, not a run on a physical phone or in Mobile Safari.

All 13 recorded checks passed:

| Interaction or assertion | Result |
| --- | --- |
| Connect using a fixture token | Passed |
| Overview statistics match fixture data | Passed |
| Search returns source results | Passed |
| Open and close source details | Passed |
| Inspect a captured session | Passed |
| Hostile HTML remains literal content and does not execute | Passed |
| Activate a candidate and find the active note | Passed |
| Open the integration catalog | Passed |
| Switch projects and observe the empty scope | Passed |
| Mobile viewport has no horizontal overflow | Passed |
| Disconnect returns to the connection form | Passed |
| No credentials retained in local/session browser storage | Passed |
| No browser page exceptions | Passed |

The run also produced [welcome](evidence/welcome.png), [overview](evidence/overview.png), [search](evidence/search.png) and [mobile](evidence/mobile.png) screenshots. All four were visually inspected; the layouts were readable and the mobile navigation scrolls within its own row. The checked-in smoke scripts permit a later repeat with a temporary fixture; Playwright and a compatible Chromium executable must be available in the browser-test environment. Those browser-test dependencies are not installed as application runtime dependencies.

## Package and clean-install evidence

The build completed with `agent_hub-0.1.0.tar.gz` and `agent_hub-0.1.0-py3-none-any.whl`. The separate `install-check` virtual environment had been created independently and its runtime dependencies installed from `requirements.lock` with hash checking. The release wheel was reinstalled without dependency resolution:

```bash
../.venv/bin/python -m build
../install-check/bin/python -m pip install --no-deps --force-reinstall dist/agent_hub-0.1.0-py3-none-any.whl
../install-check/bin/python -m pip check
../install-check/bin/agent-hub catalog validate
```

`pip check` reported `No broken requirements found`; catalog validation returned `valid: true, entries: 1`. Inspection confirmed the wheel contains the browser HTML/CSS/JavaScript and catalog, and the source distribution contains the specification, client/server guides, validation report, dependency lock, bootstrap helper, Dockerfile and maintainer instructions.

A separate smoke program used only that installed package to initialize a temporary `verify` project through the real CLI, launch `agent-hub serve` as a subprocess, and call the HTTP service on a temporary loopback port. The health endpoint, browser root and JavaScript asset returned 200. The project API returned 401 without credentials and 200 with its synthetic administrative token; its project list included `verify`. The process was terminated and temporary data removed afterward. This is a real packaged-service startup, not a deployment to the permanent host. The final documentation and bundled browser evidence were included in a subsequent packaging rebuild; application behavior did not change after the tests and clean-install run (the remaining changes were documentation, packaging metadata and trailing whitespace).

## Checks still required on the target installations

Only Linux Python 3.12 execution is established here. The repository's GitHub Actions matrix is configured for Python 3.11/3.12 on Linux, macOS and Windows, but **GitHub CI has not run**. Passing tests that manipulate Windows path strings is not native Windows execution.

The following remain unexecuted or pending:

- Native Windows and macOS package/setup execution, PowerShell helper execution, and their background watcher service configuration.
- Actual Codex or Claude Code lifecycle delivery, hook trust, desktop environment inheritance, and a live T3 provider/profile session. Protocol and hook fixtures do not prove these native integrations ran.
- Docker image build/run and Compose operation on the intended host.
- A configured real model provider, including its response shape, reported usage and billing behavior.
- Deployment to the permanent server, its DNS/HTTPS/private-network routing, restart behavior and restoration from that installation's backup.
- GitHub repository creation/push and a successful remote CI run. The connection verified `iminsandiego`, but returned no accessible repositories/installations and exposed no repository-creation action. The exact target lookup returned 404; it does not establish whether an inaccessible private repository exists. Browser creation and diagnostic attempts timed out. Publication is blocked; no successful remote push is claimed.

No actual personal logs were imported during these checks. Follow the target-host acceptance steps in [SERVER_SETUP.md](SERVER_SETUP.md) and the native-client checks in [CLIENTS.md](CLIENTS.md) before relying on capture from a particular computer. The executed results support an initial tested implementation, not a blanket production-readiness claim.
