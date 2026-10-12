# Implementation review

This review accompanied implementation. It concentrates on failures that would expose another project's history, lose a capture job, corrupt an existing installation, or make retrieval impractical. The implementation is independently written; the upstream architectural analysis is in [UPSTREAM_ANALYSIS.md](UPSTREAM_ANALYSIS.md).

## Verified server boundaries

`tests/test_security.py` exercises the real FastAPI routes, authentication store, request middleware, and official MCP SDK Streamable HTTP handler against temporary databases. The reviewer's last complete run of that file passed **94 checks**. The full project test count is recorded separately by the release validation process.

Verified behavior includes:

- Every private REST route and the MCP endpoint reject missing credentials before parsing a request body.
- Revoking a machine token takes effect on subsequent requests from the same client.
- Host and Origin allowlists apply to REST and MCP; wildcard configuration is rejected.
- Project restrictions apply both to the requested project and to the identifier being retrieved. Knowing another project's event, session, memory, or tree-node ID does not grant access.
- Concurrent REST and MCP requests retain their own credentials. Completing a request does not leave its identity installed on the next request.
- Read-only clients cannot ingest or propose memories. Ordinary writing clients cannot approve memories or create projects.
- Cross-project source references and supersession attempts fail without partial state changes.
- A transcript that contains instructions remains quoted historical data. Ingestion does not create an active instruction, and candidate creation cannot set its own approval status.
- Oversized bodies, including streamed bodies with misleading Content-Length, are rejected. Invalid or excessive retrieval arguments are rejected.
- Event pages preserve Unicode and reconstruct the requested captured text or raw representation exactly. Full raw downloads retain the same project authorization checks.

These are application behavior tests. They do not establish that any model is immune to instruction injection, that an actual native client's hooks have executed, or that a particular external deployment is configured correctly.

## Findings resolved during the review

| Finding | Consequence | Resolution and evidence |
| --- | --- | --- |
| Authentication connections relied on garbage collection for closure. | Repeated requests could retain database file descriptors. A diagnostic with garbage collection disabled grew from 4 to 305 descriptors after 150 authentication calls; collection released them. This was a reproduction of resource lifetime, not a throughput benchmark. | The authentication store now explicitly commits or rolls back and closes every connection. A portable regression observes actual `close()` calls without depending on `/proc` or garbage-collection timing. |
| Raw event and session retrieval could return large captured records directly to an agent. | A small tool request could consume a large portion of the model's context. | Event retrieval now uses explicit character offsets and continuation metadata; session and leaf previews are bounded. Exact raw download remains a separate authenticated operation. Regression coverage includes long Unicode records and an 80-record session. |
| Private configuration replacement truncated existing files in place. | A failed write could destroy a working configuration, and an existing permissive mode could remain permissive. | Replacement now uses a private temporary file and atomic rename. Tests cover permissions, symlink replacement, and failure before rename while preserving the old configuration. |
| Reviews did not retain the authenticated administrator's identity. | An approval trail could not distinguish the credential that performed the review. | The REST route passes the administrator ID to the review log. Approval still does not mark a historical claim as independently verified truth. |
| Client-side state connections had the same implicit-closure pattern. | Long-running watchers and repeated hooks could retain local database handles. | The client state store now has an explicit closing context manager. |
| Session metadata included changing observations such as pending turns and newly encountered record types. | Later appends could conflict with the archive's immutable session metadata. | Changing observations remain capture diagnostics and are excluded from immutable wire metadata. Client regression coverage verifies that a newly encountered record type does not block later ingestion. |
| JSONL and app-server exports reused the same source-session identity. | Two different representations of one native session could conflict or appear to be interchangeable originals. | App-server capture uses a distinct source-stream suffix and retains the native session ID as provenance. Semantic overlap across the two representations is documented; semantic deduplication is not claimed. |
| Queue revisions restarted after deleting and recreating a job. | A stale second drainer could acknowledge a newly queued job with the same ID and revision. | Every enqueue now creates a nonrepeating generation. Completion and failure updates are conditional on the captured generation. The client tests reproduce the delete/re-enqueue/stale-drainer sequence. |
| Configuration validation occurred after replacing a credential file. | A rejected URL or project mapping could leave a previously working client with the wrong token. | The prospective configuration is validated first. Token and configuration paths must remain separate; a regression preserves the existing token on validation failure. |
| Offline context could omit its capture time and lose a quoted record boundary when shortened. | Users and agents could mistake stale context for a fresh response or receive partial data lines. | Cached context includes its timestamp, expires after seven days, and fits the hook budget using complete lines. Cache identity includes endpoint, project, and credential identity; authorization failures do not use cached history. |
| App-server tool-item normalization omitted command, output, and tool identity fields. | The raw item was retained, but full-text search and semantic summaries could receive a generic placeholder. | Known command, MCP, and dynamic-tool variants now use the fields verified in the locally generated Codex protocol schema. Original captured item JSON remains available. |

## Result-size contract

The context request's `budget_chars` limits the context text, not tokenizer output. The server defaults to 12,000 characters and accepts 512–64,000; the local CLI/stdio gateway defaults to 8,000 and clamps requests to 512–24,000. Event offsets and lengths also count Unicode characters. The separate result check rejects a logical returned value above 160,000 UTF-8 bytes. The MCP SDK may represent that value in both text and structured content, so its complete transport envelope is larger. Exact raw downloads intentionally use a different contract from a model-facing preview.

No truncation marker changes the archived source. A preview's continuation fields identify how to retrieve the remaining representation. A summary or preview must not be described as the complete original when its metadata says otherwise.

## Installation and upgrade boundaries

Setup preserves unrelated client settings and records backups. It does not bypass native hook trust, workspace trust, or managed organization policy. The reviewed Windows Codex hook launcher uses shell commands; unsupported shell metacharacters in generated paths are rejected before configuration files are written. The documented watcher option remains available when lifecycle hooks are unsuitable. Actual Windows, macOS, Claude Code, and T3 lifecycle execution requires verification on those installations.

The outbox retains references to capture sources, not an independent copy of their contents. Successful server ingestion establishes archive retention. Sources must remain readable until then, and missed-hook recovery requires an explicit capture root or later import. Separate native attachments and spilled tool-output files are outside this release's record-capture contract.

The original archive and derived normalized text are protected from silent conflicting replay. Consequently, a future adapter change that alters normalized content or source identity needs an explicit migration or source-stream version. Retained raw records make such reprocessing possible. Moving a captured source or assigning it to a different project is likewise an explicit operation, rather than an automatic reassignment of existing evidence.

This review does not claim a production-scale benchmark, paid model-provider validation, live-device lifecycle execution, or installation on the user's computers.
