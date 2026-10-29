## Cut-off Codex records (unreleased), October 28, 2026

Windows 11, CPython 3.12.10: `python -m pytest -q` ran 445 tests, 421 passed and 24 skipped (the POSIX-only skills tests). New in `tests/test_streaming.py`: a synthetic rollout whose compaction record is cut off and then written in full on the next line parses with that line skipped and the later lines' ordinals unchanged; while the full copy is still unterminated, the cut-off line waits; a cut-off record that the next line does not rewrite (a different ordinal) still fails as malformed. Through the streaming path, with the chunk budget reached on the cut-off line, the archived records and checkpoint match the in-memory parse. Each half is needed: without the parser change both tests fail, and without the streaming change (a chunk may end on the cut-off line) the streaming test fails.

On the owner's Windows work computer, the one Codex subagent rollout that the compressed-rollout backfill refused (`Malformed complete transcript records: line 245`) was parsed locally: line 245 is a `compacted` record cut off at exactly 2,097,152 bytes, line 246 is the same ordinal written in full, and a second zstd decoder gives the same bytes. With this change the file parses to 693 records in memory and the same 693 when streamed. Backfill totals before this change: 1,137 of the 1,138 non-reviewer threads under `~/.codex/sessions` were on the server.

---

## Compressed Codex rollouts (unreleased), October 28, 2026

Windows 11, CPython 3.12.10: `python -m pytest -q` ran 443 tests, 419 passed and 24 skipped (the POSIX-only skills tests). New in `tests/test_clients.py`: a two-frame `rollout.jsonl.zst` is discovered beside a plain file, captured with the same raw records as its decompressed JSONL, checkpointed at the decompressed length with the compressed file's size, not queued again by the next scan, and a file that is not zstd raises `ZstdError`. New in `tests/test_streaming.py`: a many-frame compressed file through the streaming path gives the same events and checkpoint as the plain fixture, and after the plain file was captured adds no record, only duplicates (bounding the read by the first frame's declared size captured 2 of 26 records and failed the test); the Codex title lookup matches a compressed rollout to the `.jsonl` path Codex recorded. `zstandard==0.25.0` is a new dependency; its `requirements.lock` hashes are PyPI's for all 99 release files.

Survey of the owner's Windows work computer (file names, sizes and Codex's own thread index only): Codex had moved 2,815 of 2,830 threads to paginated history and compressed their rollouts, 6.8 GB compressed and 18.3 GB of JSONL (largest 2.4 GB); every frame declared its size. Before this change the client saw only the 15 uncompressed rollouts. Not yet run: capturing the compressed rollouts against the server.

---

## 0.1.15 note deletion and filter, October 23, 2026

New tests: `tests/test_store.py` deletes a rejected note that had superseded an active one and checks its statement, sources, keys, reviews (its own and the one naming it) and search entry are gone, the earlier note keeps its status without the link, its source event stays, candidate and active notes are refused, another project gets "not found", and the statement can be proposed afresh; the list filter matches every word case-insensitively, treats `%` and `_` as text, folds non-ASCII on both sides alike, and refuses more than eight words. `tests/test_security.py` checks the delete route needs authentication and an administrator, refuses a candidate (409), and returns 404 once the note is gone.

`scripts/browser-smoke.cjs` gained two checks, 29 in all, run in headless Chromium against `scripts/smoke_fixture.py` (synthetic data): filtering the Active tab to one note, an empty result and its message, the filter following a tab change; retiring that note and deleting it from the Rejected tab through the confirmation dialog. All 29 passed.

Linux, CPython 3.13: `PYTHONPATH=src python -m pytest -q` ran 408 tests; 407 passed. The failure, `test_client_against_real_authenticated_service_contract`, is the known one in this environment (its httpx mock transport) and also fails on 0.1.13. Not tested: the deployed server.

After merging `main` (0.1.14 skills repository, Cursor client, client `ca_file`) and renumbering this release 0.1.15: Windows 11, CPython 3.12.10, `python -m pytest -q` ran 441 tests, 417 passed and 24 skipped (the POSIX-only skills tests). The browser smoke checks were not rerun after the merge.

---

## Client `ca_file` for a private-CA server (unreleased), October 27, 2026

Windows 11, CPython 3.12.10: `python -m pytest -q` ran 437 tests, 413 passed and 24 skipped (the POSIX-only skills tests). New in `tests/test_clients.py`: `configure --ca-file` saves the resolved path, keeps it on a later `configure`, refuses a missing file and clears with `none`; a relative `ca_file` is rejected; against a local HTTPS server whose certificate a freshly generated synthetic CA signs, the client without `ca_file` fails verification and with it succeeds, and an unreadable `ca_file` is a `ClientError`.

Live check on the owner's Windows work computer against the team server's HTTPS endpoint (private CA, `SSL_CERT_FILE` and `SSL_CERT_DIR` unset): `context` and `search` returned results, a `UserPromptSubmit` hook payload returned matches, and `watch --once` uploaded the queued chats (one job still refused with the known 409 for a Cursor chat ID present in two workspace folders). Not run: macOS or Linux clients, the stdio MCP gateway inside Codex.

---

## Cursor client (unreleased), October 26, 2026

Windows 11, CPython 3.12.10: `python -m pytest -q` ran 435 tests, 411 passed and 24 skipped; `python -m build` built the sdist and wheel. New in `tests/test_clients.py`: detection and rendering (text, tool calls, `turn_ended`); an unterminated Cursor record kept only once its file has settled, a half-written one never; a partial first Codex or Claude record still raises and leaves no checkpoint; generic `{role, message}` exports are not taken for Cursor; subagent identity, including a Windows path and an explicit `--session-id`; a settled tail resent as a duplicate when the chat grows; `<user_query>` prompts classified as the user's words, `[temp]` inside it detected, `turn_ended` as bookkeeping; `setup --clients cursor` merging only `mcp.json`, idempotently, and refusing HTTP. `CLASSIFIER_VERSION` is now 2; run `agent-hub rebuild` on each project before `prune`.

Record survey of the owner's 51 Cursor agent transcripts (record shapes and wrapper tag names only): every message record has exactly `role` and `message`; user prompts are wrapped in `<user_query>`, sometimes after a `<timestamp>` block. 22 files end with a newline (19 of them with a `turn_ended` record, 3 with an assistant record); the 29 files without a final newline were all last written February to May 2026 and end with an assistant record. The Cursor version that wrote each file was not recorded.

Live check on the owner's Windows work computer: `plan-import ~/.cursor/projects` classified all 51 as `cursor`, 51 ready, no unknown record types, 13 subagents with their own identity. With the first version of this branch deployed to the owner's Linux work server, the Windows watcher uploaded the transcripts with client `cursor`. One chat ID present in two Cursor workspace folders with different content was refused with HTTP 409 and stays queued. Not run: a live Cursor chat being written while the watcher runs, the `agent-hub` MCP server inside Cursor itself, macOS or Linux clients.

---

## 0.1.14 private skills repository, October 25, 2026

macOS, CPython 3.12: `PYTHONPATH=src python -m pytest -q` ran 427 tests, all passed (23 new in `tests/test_skills.py`: source validation, clone beside `client.json` and fast-forward update against a synthetic local origin, dry run, reported errors, prompt once / declined / never noninteractive, `--skills-repo` and `none`, reconfigure keeps the setting).

Live check on the owner's Mac with a temporary copy of `client.json`: `setup --clients t3 --skills-repo <local checkout> --dry-run` ran the repository's `install.sh --dry-run`; the same command without `--dry-run` ran `install.sh` (every skill already linked, nothing changed) and saved `skills_repo`. Cloning a private repository over SSH was exercised only through the synthetic tests, not against GitHub. Not run on Linux or Windows.

---

## 0.1.13 summary pilot and chat outcomes, October 20, 2026

**Summary pilot.** GPT-6.1-Sol (low effort, isolated `codex exec` on the Codex subscription) summarized positions 147,456–161,728 (2026-10-04..20) of a copy of the pruned home archive with the 0.1.12 worker's rules: 2,146 calls, 25.9 million input tokens (65% cached), 268,000 output tokens, 1,770 model summaries and 802 free concatenations; 367 first answers too long and shortened; 10 nodes kept as excerpts; 6 answers rejected for quoting a `<budget:…>` tag that the records discussed (the check is narrowed in this release). Twenty broad questions about that period with 3–5 key points each (verified in the chats) were answered by Sonnet 5.5 (low) from the injected text and graded per key point by Sonnet 5.5 (medium): startup context alone 0% with or without summaries; startup plus first-prompt matches 14.8% without and 12.5% with summaries. A summary line covering thousands of records cannot carry one chat's outcome, so the tree summaries were not kept. Fact recall (25 questions) was 24/25 with and without them.

**Chat outcomes.** Same 20 questions and graders on the unsummarized copy: matches as in 0.1.12 (three per chat) 15.8%; three per chat plus each chat's latest assistant message 23.5% (7 questions better, 2 worse); two per chat plus the latest message 23.3%. Fact recall 24/25, 24/25 and 23/25.

macOS, CPython 3.12.14: `PYTHONPATH=src python -m pytest -q` ran 404 tests, all passed.

---

## 0.1.12 what a new chat learns, October 20, 2026

All home-archive measurements used an online backup of the live database on agent-vm (501,895 records, 2026-10-20 06:04 UTC), never the live file.

**Composition.** Record text plus raw source by class: bookkeeping 224,158 records, 3,396 MB (Codex `event_msg` 2.1 GB, Codex `compacted` snapshots 1.0 GB); tool 117,248, 1,293 MB; Codex approval-reviewer threads (782) 106,519, 733 MB; conversation 16,796, 196 MB; other subagent threads 20,915, 183 MB; injected 15,178, 87 MB. The 0.1.11 startup context (8,000 characters) was almost entirely event markers, token counts and tool output.

**Hook limits** (agent-vm, numbered markers injected by a test hook, isolated sessions that wrote no transcript). Claude Code 2.1.304: 9,900 characters of `additionalContext` arrived whole for both `SessionStart` and `UserPromptSubmit`; 10,100 became a preview plus a saved-file path. Codex 0.163.0 (`codex exec --dangerously-bypass-hook-trust` in a temporary `CODEX_HOME`): with no limit, a 30,000-character injection (7,500 tokens) kept its start and end with "…5031 tokens truncated…"; with `additionalContextLimit` 9500 it arrived whole, so the limit counts tokens.

**Rebuild and prune** (scratch copy): reclassify and rebuild 95–100 s; prune report 61 s; apply 173 s (341,570 records and 4.2 of 5.9 GB of record text removed, 160,325 kept, positions 0..160,324, 320,642 tree nodes; write-ahead log peaked under 1.9 GB with `secure_delete` off); VACUUM 32 s, 8.1 GB to 2.55 GB. Startup context 0.01–0.05 s; first-prompt matches over the 25 questions: median 69 ms, p90 95 ms, max 117 ms (177/320/387 ms before batching class lookups, reading each text once, ranking row ids first, a linear excerpt window and building excerpts only for kept lines; an earlier project-filtered FTS query took up to 7.6 s). The hook process itself, against an instant local stub on the Mac: 34 ms median with the loopback client, 55 ms with httpx.

**What a new chat can answer.** 25 questions about specific facts from past chats (April–October 2026; IPs, paths, file names, quote and commit IDs), each with keywords verified in its chat's stored text and absent from the question, written by Sonnet 5.5 and reviewed. Haiku 5.5 (low effort) answered each from the injected text only; correct = every keyword in the answer.

| Injected | Characters | Keywords present | Answered correctly |
| --- | --- | --- | --- |
| nothing | 0 | – | 0/25 |
| 0.1.11 startup | 7,988 | 1/25 | 1/25 |
| 0.1.12 startup (recent chats + history) | 9,392 | 0/25 | 0/25 |
| 0.1.12 startup + first-prompt matches (first version) | 16,958 | 15/25 | 13/25 |
| 64,000-character pack (matches, chats, history) | 63,958 | 15/25 | 12/25 |
| 0.1.12 startup + first-prompt matches (final: densest-window excerpts, term-coverage rerank, three per chat) | 17,923 | 21/25 | 21/25 |

A larger pack did not help; the first prompt's matches did. The startup section names recent work but holds few exact facts.

**Summary model trial** (5 regions of 8 conversation records, bottom-up as the worker does it, on the subscriptions: Claude through isolated `claude -p`, Codex through `codex exec --ephemeral` in a temporary `CODEX_HOME` with the worker's prompt as `model_instructions_file`). "Fits" = at most 512 bytes; "junk" = an accepted line the 0.1.12 check rejects.

| Model / effort | Calls | Fits first try | Fits after retries | Junk | Input tokens per call (cached) | Output | Seconds |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Haiku 5.5 / low | 58 | 68% | 95% | 3 (ruler copies) | 5,560 (12%) | 634 | 4.0 |
| Haiku 5.5 / medium | 54 | 71% | 100% | 2 (ruler, `<budget:…>` tag) | 5,480 (37%) | 1,180 | 5.9 |
| Sonnet 5.5 / low | 56 | 64% | 97% | 0 | 4,601 (14%) | 210 | 4.8 |
| GPT-6-Luna / low | 75 (cap) | 48% | 62% | 0 | 13,712 (52%) | 153 | 17.1 |
| GPT-6-Luna / medium | 75 (cap) | 50% | 68% | 0 | 13,593 (58%) | 168 | 17.0 |
| GPT-6.1-Sol / low | 53 | 79% | 98% | 0 | 12,933 (55%) | 127 | 16.1 |
| GPT-6.1-Sol / medium | 53 | 81% | 98% | 0 | 13,197 (57%) | 158 | 20.8 |

Reading the lines side by side: Haiku and GPT-6-Luna mixed preceding-context facts (the user's earlier words) into summaries of tool-output leaves; Luna rarely fit and fell back to excerpts. Sonnet and GPT-6.1-Sol kept to each record, kept attribution and exact IDs and paths; Sol fit most often and drew more facts from long tool output; Sonnet abbreviated raw coordinates that Sol copied. Sol low and medium were nearly identical. About 10,000 of Sol's input tokens per call are `codex exec`'s own instructions and tool list (measured with an empty prompt), mostly cached. GPT-6.1-Luna was not offered by the Codex catalog (gpt-6-luna was tested). Recommendation if summaries are enabled: GPT-6.1-Sol at low effort on the Codex subscription, Sonnet 5.5 at low effort as the alternative; not Haiku or Luna. The worker would need a subscription backend (it calls an OpenAI-compatible API today), ideally one long-lived `codex app-server` session rather than a process per call. Input averaged about 2.2 characters per token (JSON-escaped, code-heavy text).

**Dry-run usage estimate** (worker rules simulated over the cleaned tree; nothing written): conversation only, 2,656 leaf and 13,857 merge calls for a first pass (16,513; about 23,000 with the measured shortening rate), mean input 21,000 characters (19,000 of it preceding context and span detail), about 67 calls a day for new history; with tool output included, 120,144 calls and 474 a day. Preceding context of 4,000 and span detail of 2,000 characters would cut mean input to 8,800 characters. With GPT-6.1-Sol (measured 1.23 calls per node, about 10,000 tokens of `codex exec` overhead per call), the conversation-only first pass is about 20,000 calls and 400 million input tokens (280 million with the smaller context), at 16 s per sequential call about 90 hours; afterwards about 80 calls and 1.6 million tokens a day.

macOS, CPython 3.12.14: `PYTHONPATH=src python -m pytest -q` ran 388 tests, all passed (one upstream Starlette warning).

---

## 0.1.11 set-aside capture jobs, October 20, 2026

On the home Mac, 124 queued capture jobs had 2,000+ attempts: 28 transcripts missing from disk and 96 Codex threads. A read-only `thread/read` through the installed Codex 0.163.0 app-server returned "thread not loaded" for every thread, and none had a rollout file. The VM had 6 missing transcripts. None of the 34 missing transcripts appears in either watcher's scan baseline, so they were never on disk.

New tests in `tests/test_clients.py`: a missing source is set aside only after 24 hours and revived by a new enqueue; another failure restarts the 24 hours; `queue list`/`requeue` through the CLI; a 0.1.10 outbox keeps its jobs when the columns are added; "thread not loaded" maps to a gone source without copying the native message, and other app-server errors do not.

macOS, CPython 3.12.14: `PYTHONPATH=src python -m pytest -q` ran 347 tests, all passed (one upstream Starlette warning).

---

## 0.1.10 foreign-key indexes, October 20, 2026

On the home VM, `agent-hub reorder --project home --apply` (0.1.9) stayed in the tree rebuild's first `DELETE FROM tree_nodes` for 40 minutes (py-spy stack at `store.py` `_rebuild_tree`; 1.36 TB read through `/proc/<pid>/io`, almost no writes) and was stopped without committing. `EXPLAIN QUERY PLAN` showed the foreign-key child lookups on `tree_nodes.left_id`/`right_id` narrowing only by project.

`tests/test_store.py::test_every_foreign_key_child_column_is_indexed` and `::test_opening_an_older_database_adds_the_foreign_key_indexes` fail on 0.1.9 and pass now. A synthetic benchmark (not part of the suite) timed `reorder_by_time(apply=True)` on macOS, CPython 3.12.14: 4,000 records 8.3 s and 8,000 records 34.1 s on 0.1.9 (quadratic); 0.1 s and 0.3 s with the indexes.

macOS, CPython 3.12.14: `PYTHONPATH=src python -m pytest -q` ran 342 tests, all passed (one upstream Starlette warning). The fix is not yet exercised on the deployed home VM.

---

## 0.1.9 fixes from the UniiChat comparison, October 19, 2026

UniiChat source (github.com/VictorTaelin/UniiChat, commit 0500bf6) was read as data; none of its code was run. Each Agent Hub bug below was reproduced with a synthetic test that fails on 0.1.8 and passes now:

- 8,000-character context for 1,000 records covered records 985–999 only; it now covers 0–999 with no gaps (`tests/test_store.py`).
- A context with 60 active multi-byte notes measured 168,089 bytes on 0.1.8, over the 160,000-byte result guard; now at most 140,000.
- A summary answer always over 512 bytes made every run spend calls on one node and summarize nothing; an oversized record kept the root extractive; fenced extraction JSON stalled extraction (`tests/test_worker.py`).
- A queued `[temp]` Claude prompt did not exclude the chat (`tests/test_privacy.py`).
- Upload jobs and discovered files did not run oldest first (`tests/test_clients.py`).

New in the same release, each with synthetic tests: time reorder (backfilled session moved first, per-session order kept with missing and backwards timestamps, IDs/notes/search unchanged, forgotten gaps closed, worker checkpoints translated, refused while a worker run holds the lock); dated one-line context (oldest first, hostile multi-line text confined to its own line, query matches capped at half the budget); `lo+n` zoom through the store and REST route; merges receiving their own records as span detail and retries showing the 512-byte cut; parser version 2 roles and payloads for Codex and Claude Code with version 1 output unchanged, version kept per file, and a lost checkpoint falling back to version 1 with all records matching as duplicates; and forgetting resetting only model summaries that could have seen the chat.

Linux, CPython 3.13.16: `PYTHONPATH=src python -m pytest -q` ran 340 tests, 339 passed. The one failure, `test_client_against_real_authenticated_service_contract`, is the environment-specific httpx mock-transport failure also recorded in the two entries below. `scripts/browser-smoke.cjs` passed its 27 checks against the synthetic fixture. The deployed home VM was not exercised.

---

## 0.1.8 browser password sign-in, October 12, 2026

Linux, CPython 3.13.16: `PYTHONPATH=src python -m pytest -q` ran 309 tests, 308
passed. The one failure, `test_client_against_real_authenticated_service_contract`,
is the same environment-specific httpx mock-transport failure recorded for the
previous commit. Fourteen new tests in `tests/test_browser_login.py` cover: refusal
before a password is set; scrypt storage without the plaintext; wrong-password
rejection; `HttpOnly`/`SameSite=Strict` cookies, `Secure` for HTTPS pages; admin
REST access with the cookie; no MCP access with the cookie; cookie writes refused
without an allowed `Origin`; sign-in refused without one; no fallback from an
explicit bearer header; sign-out, password change, disable and expiry revoking
sessions; throttling with `Retry-After`; per-port cookie names; and the
`set-password` command's `--stdin` and `--disable` paths.

`scripts/browser-smoke.cjs` passed 27 checks in headless Chromium 141 against
`scripts/smoke_fixture.py` (synthetic data and a per-run synthetic password),
directly and again through a local TCP forwarder on another port standing in for
an SSH tunnel: wrong-password message, sign-in, session surviving reload, cookie
unreadable from page script, review and forget over the session, sign-out staying
signed out after reload, and the token fallback being dropped on reload, plus the
earlier UI checks. The deployed home VM and the Mac tunnel were not exercised.

---

## Memory browser redesign and tunnel origins, October 12, 2026

The browser UI was rewritten (`src/agent_hub/static/`): project home, search with
highlighted matches, session transcripts, a record/note inspector, an agent-context
preview, a summary-tree timeline and a connect-agents page. It still loads no
third-party code, renders captured text with `textContent` only and keeps the token
in page memory.

Server changes: a browser `Origin` naming the same allowed host and port as the
request is accepted (previously a page opened through an SSH tunnel on a port other
than 8765 got `403 Origin is not allowed` on every write, so reviewing notes and
forgetting chats failed). `/health` now reports the server `domain`, and session
lists include a bounded `preview` of the first typed user request plus the first
and last source timestamps.

Linux, CPython 3.13.16: `python -m pytest -q` ran 295 tests, 294 passed. The one
failure, `test_client_against_real_authenticated_service_contract`, fails the same
way on the unmodified previous commit with this environment's httpx mock transport.
New tests cover tunnel-port same-origin writes, still-rejected foreign/default-port
and non-allowlisted origins, the `/health` domain and session previews.

Browser: `scripts/browser-smoke.cjs` was rewritten for the new UI and passed all
21 checks in headless Chromium 141 against `scripts/smoke_fixture.py` (synthetic
data), at 1440×1000 and 390×844, including literal rendering of hostile text, cancel
and confirm forgetting, no browser storage and no page errors. A separate synthetic
run through a local TCP forwarder on port 18765 (standing in for an SSH tunnel)
verified sign-in, note creation and review, in light and dark color schemes.
The deployed home VM and the Mac tunnel were not exercised.

---

## Current update: 0.1.5, October 11–12, 2026

This section supersedes the original build's target-installation/publication
blockers below. Private GitHub publication and 0.1.4 CI were subsequently verified.
The home VM service, authenticated Mac SSH tunnel and both native watchers were
installed. Actual harmless Codex and Claude CLI replies from both Mac and Agent VM
were found in the shared store with exact assistant text and source provenance.
Those checks establish native CLI capture, not a T3 UI lifecycle or trusted hook
startup-context injection. Codex hook trust and app reload remain client checks.

For 0.1.5, macOS Python 3.12 full suite: **261 passed**, one upstream Starlette
warning. Command: `PYTHONPATH=src python -m pytest -q`, using the development
venv. The loopback MCP test required ordinary local socket access outside the
sandbox. Eight new synthetic T3 tests cover read-only/raw preservation, Unicode,
source identity, provider changes/message revisions, acknowledgements, replay,
bounded passes, schema errors, source reset and destination mismatch.

Home VM acceptance: 104/104 saved T3 thread records matched their original
source rows and normalized text, with authenticated HTTP retrieval verified.
Source/checkpoint sequence both 107; saved provider names Codex, Claude and Grok.
The separate user service is enabled/active. This is saved-history comparison;
a fresh T3 UI turn and Cursor inference were not exercised.

The T3 adapter targets the live home server's 0.0.45 event schema. Native Cursor,
standalone Grok, Windows historical import and a T3 V2 coordinator upgrade are not
qualified by these tests. No model worker is enabled by default.

---

# Validation evidence

## Version 0.1.4 Windows backup correction

The 0.1.3 Windows run installed dependencies successfully, then found six backup-related failures from fsync on a read-only descriptor and one test-only Unicode decoding failure. The backup now uses r+b without modifying snapshot bytes, and the UTF-8 fixture assertion declares its encoding. Existing backup/restore and raw-retrieval tests provide cross-platform regression coverage. Final CI results are recorded in the publication receipt; native-client lifecycle and permanent deployment remain unvalidated.

## Version 0.1.3 Windows installation correction

The first published 0.1.2 GitHub run passed Linux and macOS on Python 3.11/3.12 plus the Docker build/CLI check. Both Windows jobs failed before tests because MCP requires an unpinned Windows-only pywin32 dependency in hash mode. Version 0.1.3 adds a platform-marked pin and hashes from PyPI without changing runtime code. Local macOS Python 3.12.14 release checks passed: 253 tests (one existing warning, 3.87 seconds) and isolated wheel/source build. Publication receipt records the final remote run outcome. Native Codex/Claude/T3 sessions and permanent deployment remain unvalidated.

## Version 0.1.2 domain separation · 11 October 2026 (America/Los_Angeles)

Recovered the complete 0.1.1 ZIP from the original conversation's download control. Original archive: 739,014 bytes, SHA-256 `14194748e6753271cf3abae554131dcf3e069fe64a3d0ce75253bc954f16ab82`. Local tag `v0.1.1` preserves its source tree as recovered; the original author's reported checks below are historical evidence, not re-executed 0.1.1 claims.

Current validation ran on macOS arm64 with bundled Python 3.12.14. Runtime dependencies installed with `pip install --require-hashes -r requirements.lock`; test tools installed from the development extra.

- Full suite: **253 passed**, one existing Starlette/httpx deprecation warning, in 3.52 seconds. Includes 17 new profile/domain/backfill tests and the actual stdio/HTTP MCP round trip. The first restricted execution passed 235 tests and failed one temporary socket bind because of sandbox permissions; the authorized full execution above passed all 253.
- New behavior: invalid strict profiles, explicit-project bypass, Codex/Claude/generic mixed-project sources, absent source evidence, hook-cwd disagreement, local memory tool denial before credentials/network, raw preservation, local planner with no queue/token/network, overwrite protection, REST/MCP cross-domain denial even for admin, mixed database startup refusal and CLI setup round-trip.
- Standard isolated package build: 0.1.2 source distribution and universal Python wheel succeeded using setuptools 84.0.0. An initial no-isolation attempt had no setuptools backend; the standard isolated build resolved it.
- Second fresh environment: locked runtime installation, wheel installation without dependency resolution, `pip check` reports **No broken requirements found**.
- Installed-wheel smoke: imported 0.1.2 from the second environment's site-packages, started a real temporary localhost service, served browser assets, verified unauthenticated denial, created a strict home profile, planned and captured synthetic history, retrieved its exact raw record, and verified denial for work projects including administrator project creation. Process stopped and temporary data removed. No real transcripts or paid models were used.

The UI and static assets are unchanged; the browser screenshots below remain earlier evidence. A native installed Codex/Claude/T3 lifecycle session, Windows execution, permanent host, private-network routing, live model provider, retention lifecycle and production backfill have **not** been validated in this release. A collector is not DLP: cwd checks cannot classify pasted data or omitted native metadata.

GitHub connector identified `iminsandiego` but listed zero installations/repositories and exposes no repository-creation action. Initial local CLI credentials were invalid and SSH had no accepted key. The user refreshed CLI authentication; it now verifies `iminsandiego` with repo scope. Publication and remote CI are separate release gates; the final publication receipt records their actual results.


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

## Version 0.1.6 privacy and backfill, October 12, 2026

macOS Python 3.12: `PYTHONPATH=src python -m pytest -q` passed **287 tests**,
one upstream Starlette warning, 4.24 seconds. New synthetic tests exercise
prefix exclusion before storage, replay after checkpoint loss, late T3/native
aliases, child inheritance without parent/sibling deletion, real authorization,
source-linked note/index/tree purge, stable surviving IDs, restore with current
policy, crash between ledger commit and purge, concurrent replay, in-flight
semantic work, cache scrubbing, large raw records and bounded streaming import.
Streaming fixtures preserve raw bytes/ordinals and resume after an outage;
malformed or rewritten sources remain visible.

Local headless Chrome browser smoke passed **15 checks**, including cancel and
confirm Forget this chat, source-linked note removal, source inspection, literal
hostile text, mobile layout and no persistent browser credentials. Synthetic
fixture only; the screenshot was visually inspected. The local runner reads its
private fixture credential directly; no production credential was sent to a
browser connector. The package build and JavaScript syntax check passed. Target
installation/backfill evidence is recorded separately after deployment.

The full 286-test release gate passed again after a live large-archive test exposed a deletion stall. Forgetting now replaces only erased leaves and affected ancestors, with a regression asserting that unrelated semantic summaries survive and a full rebuild is not used. Package rebuild succeeded; backfill jobs yield to ordinary live capture. Target-server replay and complete inventory evidence follow below.


### Deployed privacy and real T3 recall

Mac Python3.12 and Debian13/VM Python3.13.5 installed0.1.6 with matching
`store.py` SHA256 `2bb34ab24a5669e1677cedaa961e0c304076744e57106990ec50b3ea42c50060`.
Both installed dependency checks passed. The service, native watcher, T3 reader
and backup timer were active after deployment. Only Agent Hub services were
restarted; T3 and unrelated workloads remained running.

A synthetic deployed HTTP/native-queue test passed temporary exclusion,
forgetting both native and proven T3 copies, append and replay after lost local
checkpoints, T3 replay exclusion, zero final test queue, and403 for administrative
deletion attempted with ordinary harness credentials. Two synthetic records
were purged; no user chat was deleted. The first large-archive deletion test timed
out and blocked writes because full-tree removal was expensive. The affected-tree
fix above was deployed; the same synthetic workflow then passed. Durable queues
retained transient restart/lock errors for retry rather than dropping records.

The missing named-chat source predates first watcher installation.
It was last changed03:52:58Z; installation baseline at04:00:09Z excluded unchanged
historical files. Backfill captured every byte and original record of that source.
An attributed Codex name record points to the native session. MCP retrieval of
the last records verified an earlier file-transfer discussion.

A fresh real T3 Claude Opus5.5 chat (ID withheld),
asked where that chat left off without a memory-lookup reminder. It used memory
tools and returned that transfer's last recorded status and pending checksum
verification, explicitly distinguishing historical state from current completion.
The test started with `[temp]`. Read-only T3/source and archive comparisons found
both its T3 and native Claude identities marked temporary, with **zero stored test
events** in either identity. Native/T3 source transcripts remain in those clients.

Private GitHub push was confirmed by matching remote/local main SHA
`7298b7ef3693a505abebe6fc8b94e0c8333c7660`. All seven jobs passed in
https://github.com/iminsandiego/agent-hub/actions/runs/38209299651:
Python3.11/3.12 on Ubuntu, macOS and Windows, plus Docker build/CLI startup.
The repository readback confirmed private visibility and administrator access.


Full historical backfill processed all available original Mac/VM Codex and
Claude files, all available native transcript files. Two actively
changing Mac chats continue streaming; their saved historical prefixes were
acknowledged. Eight Mac/four VM older hook jobs reference nonexistent sessions
or source files and remain visible; they are not available historical transcripts.
Transient interrupted-upload jobs drained successfully without source alteration.

A larger live backup exposed repeated-copy starvation from ongoing writes.
The fix pins and establishes a WAL read snapshot throughout all incremental
backup steps. A regression writes successfully from a separate connection during
backup and verifies that the snapshot contains only the original source record,
while the live archive contains the new record. The final full suite passed
**287 tests**, one upstream warning, in4.24seconds, and package build succeeded.
This follows SQLite's documented restart behavior for changing source databases:
https://www.sqlite.org/backup.html. Only the owned unfinished temporary copy was
cleaned; no completed snapshot or user history was removed.
