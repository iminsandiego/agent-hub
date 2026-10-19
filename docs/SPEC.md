# Agent Hub — tailored implementation specification

Version 0.1.2 · 11 October 2026 (America/Los_Angeles)

This is the implementation contract for the owner's shared agent infrastructure. It incorporates the useful historical-memory structure from UniiChat (formerly OptChat) while accounting for native coding clients, multiple computers, multiple repositories per project, local device access, and durable evidence. The separate [upstream analysis](UPSTREAM_ANALYSIS.md) records what was actually read and corrects claims from the earlier conversation.

The [home/work and ingestion contract](DOMAINS_AND_INGESTION.md) supplements this specification and supersedes examples using one mixed-domain service. Existing 0.1.1 archive identities and payloads remain compatible; strict domain deployment uses new domain-prefixed project IDs without silently reassigning existing history.

## 1. Outcome and scope

One private GitHub repository holds the application, reproducible installation instructions, and the future integration catalog. Independent home and employer-approved work service instances hold their respective memory. Each authorized computer gets a local client and its own project-scoped token. Codex, Claude Code, and the providers used by T3 can access the same memory through MCP.

The first implementation must support:

1. Explicitly selected, automatically captured local sessions and historical backfill.
2. Original captured-record retention, source identity and idempotent ingestion.
3. Project-scoped lexical retrieval and a navigable binary tree of history summaries.
4. Small context packs, source drill-down, and separately reviewed durable memories.
5. Offline-safe capture, retries, source rewrite detection, and visible ingestion failures.
6. Per-computer revocable credentials, explicit project authorization, and authenticated browser/API access.
7. New-computer setup that preserves existing client configuration.
8. Optional model-assisted enrichment with recorded usage and bounded calls.
9. Backup/restore and a tested portable package.
10. A repository convention for future MCP servers, plugins, and skills.

This version does not implement a new model/chat harness, a replacement for native client compaction, vector embeddings, an OAuth identity provider, cross-user SaaS tenancy, automatic requirement approval, semantic contradiction resolution, a full plugin marketplace, or a device automation runtime. Future integrations can be added without changing memory's identity model.

## 2. Architecture and placement

The service is a Python application with SQLite on a local persistent filesystem. FastAPI supplies the REST API and browser. The official MCP Python SDK supplies the remote Streamable HTTP endpoint and the local stdio gateway. A lightweight independent capture process handles session files and supported exports. The worker handles derived data separately from capture.

| Component | Runs where | Responsibility |
| --- | --- | --- |
| Memory service | Always-on server | Authentication, scoped ingestion/retrieval, memory review, browser, HTTP MCP |
| SQLite memory database | Server local disk | Original raw record strings, normalized searchable text, provenance, summary cache, memory state and reviews |
| Client configuration and credential | Each execution host | Service URL, unique machine identity, explicit project mapping, scoped credential |
| Capture hooks | Inside supported native client lifecycle | Fast local notification or bounded context injection |
| Watcher/uploader | Each execution host | Retry queued sources, scan configured capture roots, maintain checkpoints, and backfill history |
| Stdio MCP gateway | Started by native client | Expose five memory tools while forwarding authenticated requests to server |
| Enrichment worker | Server | Deterministic candidate selection; opt-in model summaries and candidates |
| Integration catalog | Git repository/package | Reviewed inventory of MCP/plugin/skill definitions and setup conventions |

GitHub stores code and documentation. The server stores conversations and operational memory. The databases are never synchronized by Git, cloud file synchronization, or direct network-mounted SQLite access. Multiple computers talk to the API.

Device SSH, GUI test automation, robot control, device tooling, repository commands, and model inference remain in their existing execution environments. They are not proxied through the memory service. The service cannot make a cloud execution environment reach a private LAN device merely by remembering it.

## 3. Deliberate differences from corrected UniiChat

This comparison uses the corrected Gist revision `3c190e06f34aba0c69f49042c526093269604935`, committed on 8 October 2026 UTC (7 October in Los Angeles). The original revision used for version 0.1.0 is preserved as historical evidence in the source audit. The [cache correction review](CACHE_REVIEW.md) explains the changed merge rule and its effect on this application.

| Corrected UniiChat mechanism | Agent Hub decision | Reason |
| --- | --- | --- |
| One endless conversation controlled by the harness | Multiple native sessions with shared project memory | Codex/Claude/T3 retain their native tools, subscriptions, and session lifecycle |
| Fresh model invocation for every user turn | No control over native model calls | An attached MCP cannot promise to reset another application's context |
| One global append-only JSONL log | Transactional project/event/session archive in SQLite | Concurrent computers, retries, provenance, and atomic index updates |
| Persist an append-only growing view, then batch from over 128,000 to at most 64,000 bytes; merge by age from the pair's last message | Request-specific context packs and dyadic retrieval views; no claim that they preserve a provider prompt prefix | Retrieval across projects and native clients has a different contract; the corrected harness algorithm is not implemented by these projections |
| All visible history summarized before a new model turn | Immediate deterministic excerpts, optional asynchronous semantic enrichment | Offline memory or provider failures must not freeze coding clients |
| Approximate 512-byte summary target | Hard 512-byte semantic summary limit | A predictable cache and retrieval budget; unsuccessful shortening retains the labelled fallback |
| Separate persisted compactor view cycling between 16,000 and 32,000 bytes, sharing constant system/tools with its own turns | Bounded, recomputed preceding context and independent worker prompts; original input retained across shortening retries | We control worker requests, but not the native clients' complete prompts or caches. Full cache-aware worker views remain a separate improvement |
| Agent instructions survive only through summaries | Reviewed memory records independent of the tree | Preserve exact decisions, provenance and explicit supersession |
| Master reports tagged as user-like messages | Preserve captured native role and source | Assistant/tool statements must not become the user's instructions |
| Some tool results capped before archival | Retain entire successfully captured raw record | Exact captured evidence matters; retrieval can be paged separately |
| Harness controls block cache marks and coordinates concurrent prefix writers | No cache-hit guarantee for native clients or the optional worker | The native application constructs its requests; our compatible-provider requests have no provider-specific cache policy or measured hit rate |

The tree improves navigation; it does not guarantee perfect recall. A summary can omit the only useful keyword. Search over the adapter's normalized event text and original-record retrieval are independent recovery paths. Search uses SQLite FTS5 when available and reports a simpler literal substring fallback otherwise. Raw fields omitted by normalization remain retrievable but are not automatically included in the search index. No numerical accuracy, cost, or performance claim from the upstream author is accepted as a test result for this implementation.

## 4. Authority and project boundaries

Project is a memory domain, not a single repository. `atlas` can include product source, verification automation, test utilities, and requirements work. `harbor` is separate. `personal` is separate. A future explicit shared scope is possible, but no implicit global memory is injected into every project.

A computer resolves a project from an explicit command/configuration assignment or the longest matching configured path. Paths on Windows, macOS, and Linux can map to the same project. An unknown path produces an actionable failure and retained pending capture; it does not silently assign the conversation to a broad default. Deliberate fallback assignment is allowed only when the user supplies a default project.

Every project-scoped API or MCP operation checks the token's project and permission. Identifiers do not authorize access. Resolving a known event, memory, session, or node ID from a different project must fail. Reading project lists filters them to authorized scopes; the shared integration catalog requires authentication but contains no project history.

Authority depends on the question:

- Controlled requirements define required behavior.
- Identified installed builds and execution evidence establish what was tested or observed.
- A pinned source revision explains that revision's implementation; it is not automatically the installed device's build.
- A historical discussion records what someone previously said, inferred, proposed, or observed.

These are distinct roles, not a single universal priority ladder. A memory cannot establish that a verification test ran, that a requirement changed, or that an installed build contains a source modification. Review means a note is useful context; it does not convert the note into validated engineering evidence.

## 5. Archive and identity contract

An ingestion request names a project, native client, machine, external session identity, session metadata, and one or more events. Each event includes a stable source event identifier, role, normalized text, raw captured record string, and optional source timestamp.

The server derives a session identity from the project/client/machine/external-session tuple. Within that identity, an event identifier is immutable. A duplicate with identical payload is acknowledged without adding a second event. An existing identifier with changed content rejects the entire batch. Event identity must not depend solely on its content: two intentionally repeated user messages are two events, while a changed source record must not masquerade as an unrelated append.

Accepted events receive a contiguous, monotonically increasing sequence within their project. This sequence defines tree position. Source timestamps are retained separately from ingestion time. Backfilled older sessions appear at their actual ingestion position; the service does not rewrite already assigned project indices to sort by historical time.

For line-oriented captures, the client keeps stable line ordinal identity and a prefix checksum. An incomplete trailing line waits for completion. A malformed complete line is reported and blocks advancement past that line. Truncation or rewritten source prefixes are conflicts requiring an explicit recovery decision. Unknown record types are preserved, with the normalization limitation visible; they are not silently discarded.

The raw record is authoritative for what the adapter captured. JSONL adapters store the original decoded UTF-8 record string without the line separator; app-server export stores the returned item's JSON representation. This is not a promise of complete vendor conversation export: inaccessible items, separately stored attachments or tool-output files, hidden reasoning, deleted local sessions, or formats a client does not export remain outside the archive. A source-file prefix checksum verifies bytes seen by the importer; it does not independently attest vendor completeness.

The wire contract accepts at most 1,000,000 normalized-text characters and 2,000,000 raw-record characters per event, subject also to the configured request-body limit (4 MiB by default, including JSON encoding and batch overhead). An oversized record is rejected visibly, without silently truncating the archived evidence. Explicit chunk/blob support is outside this release.

Different capture formats can represent the same conversation differently. Automatic cross-format or cross-machine semantic deduplication is not attempted. Choose one primary capture route per native session. A later migration must be explicit so evidence is not merged on guesswork.

## 6. Storage and durability

The memory database contains projects, sessions, immutable events, FTS search rows when supported, memory records, memory-to-event references, memory idempotency keys, review history, and summary nodes. The authentication database stores token digests, scopes, creation time, and revocation. The worker database stores extraction checkpoints, blocked enrichment inputs, and outbound-call observations.

The local outbox durably stores upload jobs, not independent transcript copies. A queued file or native thread must still be readable when the uploader runs. Before server acceptance, source deletion can therefore cause permanent loss. Explicit capture roots allow the watcher to rediscover file growth after missed hooks; the server and its backups preserve only records that reached the archive.

Memory transactions use SQLite WAL, foreign keys, an explicit writer transaction, a busy timeout, and full synchronization. All events, source metadata, sequence allocation, lexical indexing, and deterministic tree updates for a batch commit together. A conflict rolls the batch back. Connections are not shared unsafely between request threads.

The database schema carries a version. A newer unsupported schema is rejected. This first release has no arbitrary forward migration logic; future schema changes must add explicit upgrade and rollback guidance. A raw database file is not an API.

Summary nodes are derived and rebuildable. A rebuild replaces semantic cache entries with deterministic defaults; original events and durable memory records remain. It leaves the worker's existing call ledger and checkpoints in place, and generating the semantic cache again can incur new model calls. This is a deliberate local administrative operation, not an agent-facing tool. Online backup uses SQLite's backup API. Restore requires a destination without an existing memory/auth database, server configuration, or administrative token and verifies the backup's integrity before use. Authentication credentials are provisioned separately after restoring a memory-only backup.

## 7. Tree, summaries, and context packs

Each project event is a leaf. A parent covers two adjacent equal-sized aligned ranges. The archive uses zero-based project indices with inclusive `lo` and `hi` fields. Node IDs contain the project and range; a node covering eight events represents a true complete eight-event subtree. Arbitrary range requests are not silently coerced into a valid node.

Append operations create the leaf and any newly completed parents. A non-power-of-two history is a forest of complete dyadic roots. Every frontier must tile the entire captured range exactly once, with no gaps or overlap. A `max_nodes` value is a refinement target: at least the number of roots is required to represent the complete forest. API response limits still apply.

The default cache is deterministic:

- A short role-attributed normalized-text representation can be kept verbatim; this is distinct from the event's complete raw record.
- A long source is represented by a clearly labelled extractive excerpt.
- A parent combines its two children's representations.
- `zoom` returns the two children; at a leaf it returns a bounded page of the original captured event.

The optional semantic worker processes leaves and ready parents in source order. It includes actual role attribution and bounded preceding context. It can concatenate already processed short children without a model call. Such a concatenation is only called verbatim when the descendants were themselves original verbatim text. Semantic results record model, time, and a source fingerprint. Completion uses a compare-and-swap check; a stale result cannot overwrite a node whose source has changed.

Semantic generation targets at most 512 UTF-8 bytes. Up to two shortening requests can follow an initial request, and all count against the overall call budget. A shortening request preserves the original system and user source/context messages exactly and appends the previous assistant response and a correction. A second shortening request retains that complete conversation and appends another response/correction pair. The full conversation must fit the 24,000-character input limit before a request consumes a call; no original source or earlier message is cropped to make a retry fit. An empty, interrupted, malformed, oversized, or stale result leaves the prior labelled fallback available. Native sessions never wait for this worker to finish.

The context pack contains a warning that all included history is data, active reviewed notes, relevant matching events when a query was supplied, and recent/coarse tree entries. It includes stable source IDs. It uses complete escaped JSON records so a quoted historical command is not accidentally presented as live system instructions. Oversized records can be omitted to fit, with `truncated=true`; absence from the pack does not imply absence from the archive.

`budget_chars` measures the returned text field, not tokens. The server REST/direct-HTTP MCP default is 12,000 characters, minimum 512, maximum 64,000. The local client, CLI and stdio gateway default to 8,000 and clamp requests to 512–24,000; startup hooks fit the final injection into 8,000 characters. Other response fields and SDK envelopes add overhead. A separate guard rejects a logical serialized tool result above 160,000 UTF-8 bytes. The MCP SDK can represent that value in both text and structured content, so the complete transport envelope may be larger. The system makes no byte-to-token conversion guarantee and does not promise native prompt-cache reuse. These retrieval projections can change their leading text after an append, review, query change, or semantic completion. They are not safe substitutes for the corrected Gist's persisted append-only prompt view. Since 0.1.6 there is no local offline context cache; earlier caches are scrubbed on upgrade.

Within the budget, the pack lists active notes, then query matches, then a view of the whole history: it starts from the forest's roots, so every event is covered exactly once, and splits the most recent nodes (relative to their width) while the pack still fits, so detail fades with age. If even the roots do not fit, the newest roots that fit are kept and `truncated` is set. The pack also stays under 140,000 UTF-8 bytes so multi-byte text cannot trip the result guard.

## 8. Durable memories and review

Memory kinds are decision, instruction, observation, procedure, failure, question, and preference. A record has a statement, source-event references, creator, status, timestamps, and review history. Source IDs are validated against the same project. A deliberately source-less note remains explicitly unverified.

All normal writes create `candidate` records. The five agent tools cannot activate, reject, or supersede a note. A local administrative command or authenticated administrative browser/API action changes its state. Activation may explicitly supersede one prior active memory in the same project. The old statement remains present and marked superseded, retrievable by ID or the explicit status list. Ordinary memory search includes candidates and active notes. The source events behind a rejected or superseded note can still appear in event search or the historical tree; reviewing a note does not erase its historical evidence.

Candidate generation has two modes:

1. Local deterministic selection recognizes explicit user decision/instruction markers and preserves the selected wording. It is a limited heuristic, not general semantic understanding.
2. Optional model extraction proposes records from bounded source events. Every returned reference must be in the actual input. Schema and reference validation precede acceptance. Model outputs cannot mark tests as executed or activate themselves.

Automatic contradictory-memory detection, calibration of confidence scores, inference of a source revision, and requirement approval are outside this release. Users can search and review competing statements with their original evidence. The precise limitation is preferable to a numeric confidence field that has no calibration.

## 9. API and MCP contract

All `/mcp` access requires a bearer token. `/v1` access requires a bearer token or, for the browser only, a password sign-in session (below). The health response and static browser shell contain no private history. Token secrets are high-entropy random values; only their digest is stored in the authentication database. Server-admin credentials are separate from normal per-computer read/write tokens.

| MCP tool | Purpose | Bounds and state |
| --- | --- | --- |
| `memory_context(project, budget_chars, query)` | Startup/task context | Character-bounded history, explicit truncation |
| `memory_search(project, query, limit)` | Original-event and memory lexical search | Query up to 1,000 characters; 1–50 hits |
| `memory_get(project, kind, id, offset, limit, max_chars, representation)` | Event, session, or memory detail | Event text/raw pages up to 24,000 chars; session offsets count records |
| `memory_zoom(project, node_id)` | Hierarchical navigation | Children or first 1,000-character leaf preview |
| `memory_note(project, statement, kind, source_event_ids, idempotency_key)` | Candidate proposal | Statement up to 8,000 chars; never activates a note |

An event response distinguishes normalized text from raw representation, gives total character count and `next_offset`, and indicates whether it is truncated. A session result gives bounded event previews and the next record offset. The authenticated raw-download route returns the complete captured record for file workflows.

REST routes include health, scoped projects, ingestion, context, search, events, sessions, nodes, tree, memories, review, stats, and catalog. The endpoint is `/mcp` for Streamable HTTP. The stdio gateway exposes the same functional surface using the official SDK and authenticated REST calls.

The service uses provisioned bearer credentials, not an OAuth authorization server. Clients that require OAuth discovery without configurable headers should use the local stdio gateway. There is no claim of complete MCP OAuth support.

**Browser password (0.1.8).** People sign in to the browser with one server password, set locally with `agent-hub set-password` and stored as a salted scrypt hash in the authentication database. A correct password creates a 30-day server session: the browser holds its random secret only in an `HttpOnly`, `SameSite=Strict` cookie (also `Secure` when the page is served over HTTPS), named per port so tunnels to separate home/work servers do not collide; the database stores its digest. The session is the server administrator's browser credential with `*` scope and `admin` permission. It authenticates REST `/v1` requests only, never `/mcp`, so agents cannot use it. An explicit `Authorization` header is never replaced by the cookie. Sign-in, sign-out and every cookie-authenticated non-GET request must carry an `Origin` that is allowlisted or names the requested host; together with `SameSite=Strict` this prevents cross-site use. Wrong passwords are throttled server-wide after five attempts with an exponential delay of up to 15 minutes. Changing or disabling the password signs out every browser. Agent and per-computer tokens are unchanged, and a pasted token remains a supported browser fallback held only in page memory. Browsers do not isolate cookies by port, so another web service on the same host name as the tunnel could receive the cookie; use the HTTPS name for remote access where that matters.

## 10. Capture and native-client setup

The client guide is the versioned source of exact hook/configuration syntax. The implementation distinguishes evidence from current documentation, fixture/protocol tests, and real native-client runs.

Codex has documented startup/teardown hooks, but a transcript path can be null and native history formats evolve. Teardown enqueues local work and returns promptly; it does not upload a whole session or run summarization within the hook deadline. Legacy JSONL capture and an explicit supported export route are distinct adapters. A null path is an export requirement, not successful ingestion.

Claude Code uses its documented configuration/hook surfaces. Existing user settings are preserved and our own managed entries are updated idempotently. For explicitly configured capture roots, the watcher rediscovers session file growth independently of whether teardown ran. A partial-file job also remains queued until completion. A hook-only source that has already drained needs a later hook or an explicit import to capture subsequent growth; simply running the watcher does not scan every native history directory.

T3 reuses the selected provider's authentication and configuration on its execution host. Its inbound control MCP is a separate feature. Configure and verify memory in the provider used by T3; do not install invented global T3 hooks.

Startup requests fetch context for the mapped project under a short network timeout. Since 0.1.6 no context is cached locally: when the service is unavailable, the hook injects no historical text and reports the error without blocking the coding session. Upload state is a private local runtime file.

The install flow creates a private client configuration and credential reference, a stable machine ID, explicit project mappings, native MCP registration, and supported capture hooks. It must preserve unrelated MCP entries, provider settings, trust policies, and hooks. It must not weaken security options or silently enable arbitrary registry entries.

## 11. Operational and security limits

The service defaults to loopback. Remote use requires HTTPS termination or an SSH tunnel to a loopback endpoint, explicit allowed hosts, and explicit browser origins; a private network can additionally limit reachability. Agent Hub clients keep TLS validation enabled and reject off-host plaintext HTTP. The Python service does not itself provision certificates or enforce HTTPS behind a reverse proxy. A token is never placed in a URL, committed file, or ordinary log by the application. The browser keeps a pasted token in page memory, not persistent browser storage; a password session is an `HttpOnly` cookie that page scripts cannot read.

Request bodies are bounded before application parsing. Query strings, event fields, memory fields and result sizes have separate limits. SQL uses bound parameters; lexical search terms are escaped instead of interpreting arbitrary query syntax or regular expressions. The browser renders captured content as text and loads no third-party scripts.

Source data may contain credentials or confidential engineering material. Capture directories and projects are explicitly selected. The archive is not automatically encrypted by the app: use the server's protected disk, backups, and access controls. Optional external model enrichment sends its selected source/context to the configured endpoint; retrieving memory into a cloud-backed coding model also exposes that returned content to that client/provider. Running the memory database locally does not imply model inference is local.

The LLM worker requires explicit endpoint, model, and `--llm --once` selection. `--max-calls` is 1–100 and includes failed requests and shortening retries. Each call has a finite timeout, at most 24,000 input characters across all message content (including retry history), and at most 1,200 requested output tokens. Provider usage is recorded as reported; no dollar estimate or cache-hit percentage is invented. Retaining an unchanged message prefix across retries makes reuse possible on a compatible provider, but it does not prove a cache hit. The worker still reconstructs context between distinct nodes and lacks the Gist's persistent 16–32 KB view, explicit cache-block policy and shared-prefix coordination. Model/provider differences may require compatibility changes, especially if they do not support chat-completions `max_tokens`.

An input over the 24,000-character worker bound is recorded as blocked, with its source and deterministic fallback retained. Extraction advances past that record. A blocked summary node keeps its labelled excerpt as final (`summary_model` `fallback-final`, mode still `extractive`) so its ancestors can still be summarized; their source marks that child as an excerpt with the omitted text left in the original records, and the summarizer is told not to guess it. `worker-status` exposes blocked items. `--retry-blocked` clears that project's blocked entries and rejection counts, reopens kept excerpts and rewinds extraction to before its earliest blocked event; unchanged oversized inputs become blocked again, and ancestors already summarized over an excerpt are kept until a rebuild. Transport and provider failures stop the run and retain the work for a later bounded run. An answer that cannot be accepted (malformed or mis-cited extraction JSON, an incomplete or empty reply, a summary still over 512 bytes after shortening) is retried on a later run; a second rejection of the same item blocks only that item, so one stubborn record cannot stall the project. A single surrounding Markdown code fence around extraction JSON is accepted. Chunk-aware semantic compaction is future work. No whole-event summary is claimed after seeing only a truncated source.

## 12. Verification and delivery gates

The repository must demonstrate meaningful tests for:

- exact captured-record round trip, duplicate retries, conflicting identity rollback, stable append sequence, and concurrent writers;
- every lookup's project scope, token revocation, denied promotion, origin/host checks, request bounds and real MCP protocol requests;
- dyadic coverage, non-power-of-two history, zoom back to originals, cache rebuild, and semantic completion source fingerprints;
- durable memory status, explicit supersession, source validation and omission of inactive notes from the active context section;
- offline queued capture, incomplete/malformed JSONL, rewritten prefixes, mapping ambiguity, configuration preservation and idempotent setup;
- bounded responses, paged retrieval, source downloads, Unicode, backups and restore integrity;
- worker limits, malformed model output, fabricated references, complete source/context retention across shortening retries, append-only retry message prefixes, full-history input bounds, retry accounting, no-default-model-call behavior, and restartable checkpoints;
- package build and installation in a clean environment.

`docs/VALIDATION.md` records executed commands, actual outcomes, and unexecuted native/deployment gates. A CI workflow is configuration until it has run. A local server smoke test is not the owner's server deployment. A fixture hook test is not an installed-client certification. A Git commit or ZIP is not a verified remote push.

Future work is additive: richer multi-source extraction, semantic retrieval if justified by measured misses, native-format evolution, curated plugin/skill installation, stronger enterprise identity, and device-specific MCPs. These must preserve the event archive, project boundaries, explicit evidence references, and reversible review history established here.

## Explicit privacy exclusions (0.1.6)

The immutable archive has an explicit user-authorized erasure exception. The
server maintains a separate content-free identity/relationship ledger. Temporary
prefixes and administrator exclusions are enforced before ingestion, including
late aliases. Purge removes live originals and source-linked derivatives,
preserves surviving source IDs/sequence positions, and invalidates in-flight
semantic work. Restore requires current policy; offline context caches are not
used. See TEMPORARY_CHATS.md for protocol boundaries and backup limitations.
