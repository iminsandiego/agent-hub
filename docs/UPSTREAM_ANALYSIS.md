# Upstream analysis: corrected UniiChat, earlier OptChat, and OptMem

Current review: **2026-10-08 04:23:22 UTC**. The corrected UniiChat specification is the current reference. The earlier OptChat snapshot remains historical evidence of what informed Agent Hub 0.1.0. This is an independent analysis; no upstream application source or compactor prompt is distributed here. Exact hashes and retrieval metadata are in [SOURCES.json](SOURCES.json). [CACHE_REVIEW.md](CACHE_REVIEW.md) records the application impact and worker correction.

## 1. Sources and revision history

| Source | Inspected artifact | Revision and status |
| --- | --- | --- |
| [Corrected UniiChat Gist](https://gist.github.com/VictorTaelin/91837951a5ce5b38f341ec1ba1df6449/3c190e06f34aba0c69f49042c526093269604935) | The file is still `optchat.md`, but its title is now UniiChat. It contains a specification and an algorithm fragment, not the full application implementation. | **Current:** `3c190e06f34aba0c69f49042c526093269604935`, committed 2026-10-08 01:58:24 UTC; 19,092 UTF-8 bytes. |
| [Earlier OptChat Gist](https://gist.github.com/VictorTaelin/91837951a5ce5b38f341ec1ba1df6449/f51fe5c910427fd6f384d22823140b1693c76207) | The 35,129-byte specification inspected on 2026-10-07. | **Historical:** `f51fe5c910427fd6f384d22823140b1693c76207`, committed 2026-10-04 02:42:39 UTC. Its merge rule and cache instructions were superseded. |
| [Author's correction notice](https://gist.github.com/VictorTaelin/91837951a5ce5b38f341ec1ba1df6449#gistcomment-6413482) | Comment 6413482 by VictorTaelin, corroborated through the Gist API. | Created and updated 2026-10-08 01:59:25 UTC. It identifies a cache-breaking recipe bug and asks builders to reread the specification. |
| [OptMem source](https://github.com/VictorTaelin/OptMem/blob/1fb164cf39028047781f72ac3bb1e5a691c1dcb0/memo) | Actual Python `memo` CLI, previously read alongside its README and repository metadata. | Pinned commit `1fb164cf39028047781f72ac3bb1e5a691c1dcb0`, committed 2026-07-31 02:19:57 UTC. Not refetched during this cache review. |

The current Gist API activity timestamp is **2026-10-08 04:19:09 UTC**, distinct from the content commit and review time. Its raw-file Git blob is `4c09901baa3685852bf252cdb70ace81d01d6be5`, independently verified from the downloaded bytes. The old API timestamp, content hash and Git blob remain in the manifest rather than being overwritten with newer metadata.

The user-supplied screenshot prompted this recheck and described a cache fix plus a 98%+ result. The author's API comment corroborates the correction notice. The revised Gist qualifies its precise percentages as a simulation result; the screenshot is not independent performance evidence.

The earlier exact-path lookup of `VictorTaelin/OptChat` returned HTTP 404. That was an observation on 2026-10-07, not a fresh claim about every possible repository or private implementation. This review does not claim to have tested the author's complete chat application.

## 2. What the systems implement

UniiChat owns a complete chat harness. A new user turn waits for preceding history to be summarized, renders that view before logging the new input, and creates a fresh model conversation. Input during active work arrives between tool calls. The harness controls the system prompt, tools, message layout, model invocation and cache marks.

An attached MCP does not own native Codex, Claude Code or T3 provider requests. Supported hooks can supply startup context, but connecting an MCP does not reproduce this turn loop. This distinction does **not** exempt Agent Hub's optional LLM worker from review: that worker makes its own requests and can improve their layout, even though it cannot generally reuse a native client's account, model, system prompt and tool prefix.

The corrected main log distinguishes user messages, agent replies, tool calls, tool results, imported notes and a separate `work` kind for subagent reports. The older recipe represented reports as specially prefixed user-like entries. Detailed subagent steps remain in separate logs. Tool output is still clipped to a combined 30,000 characters of head and tail before logging, and reasoning is still excluded. Other long text is now split into successive messages instead of cut. Introductory claims about complete memory therefore do not imply unlimited original tool-output recovery.

OptMem is different: its actual CLI stores explicitly submitted notes, capped at 280 UTF-8 bytes by default. The agent supplies `nap` summaries; the CLI does not automatically capture conversations or call a background model. It uses fixed-width 320-byte original-note records and 288-byte summary records, direct file offsets, a recomputed `wake` covering and regex recall over original notes. These are findings about the pinned source, not a new UniiChat application release.

Agent Hub preserves exactly what its adapters successfully submit. Upstream truncation, deleted sources, inaccessible history and separate attachments remain capture limitations. A queued path or thread ID is not a second copy of its contents. Once accepted, original records and source identity remain independent of lossy summaries.

## 3. Corrected tree and view mechanics

The tree remains binary: each leaf represents one event, and each parent combines two adjacent, aligned equal-sized children. A source or child concatenation that fits can become a node without a model call. Nodes are addressed by first event plus a power-of-two span. Upstream still targets 512 UTF-8 bytes and can retain the shortest of five attempts even if slightly larger; this is softer than Agent Hub's accepted semantic-summary limit.

### Which siblings merge

The corrected priority is:

```text
due = (T - last) / 2^level
```

`T` is the event count; `last` is the pair's **inclusive last event index**. Choose the largest priority, the older pair on a tie, and only a pair whose parent is built. The earlier rule was `(T - first) / 2^(level + 2)`. Its factor of four scales every priority alike; the start-based age was the error. An exclusive end index must not be substituted for the corrected inclusive `last`.

For ten events and the view `0+4, 4+4, 8+1, 9+1`:

| Eligible merge | Child span / level | Earlier priority | Corrected priority |
| --- | --- | --- | --- |
| Events 0–3 with 4–7 | 4 / 2 | `(10 - 0) / 16 = 0.625` | `(10 - 7) / 4 = 0.75` |
| Events 8 and 9 | 1 / 0 | `(10 - 8) / 4 = 0.5` | `(10 - 9) / 1 = 1` |

The old rule rewrites the older portion. The corrected rule selects the recent pair and preserves more of the earlier prompt prefix. The author's broader equivalence checks against his rollback-state list were not rerun here.

### When siblings merge, and what survives restart

The old view was refitted after appends and node completions around one 128,000-byte target. The corrected view appends until it exceeds **128,000 bytes**, then batches merges toward **64,000 bytes**. If required parents are unavailable, the unfinished batch continues on later messages. Ordinary maintenance never splits a merged part.

Between batches, earlier rendered lines remain fixed and new lines extend the suffix. Batching concentrates prefix rewrites into fewer occasions. These are view-size targets, not token counts or limits on the complete API request including tools, system text and serialization.

The corrected view is saved to `view.json` and loaded on restart. This explicitly supersedes the old instruction to reconstruct it by replaying the log. Reconstructed availability/order can differ from the live sequence and invalidate reusable prefixes.

### Navigation and waiting

`zoom(start, span)` requires an aligned, positive power-of-two span. A non-leaf expansion returns two child summaries; a leaf request retrieves its logged original, with paging for long text. Reaching a leaf summary takes `log2(span)` expansions; retrieving a long original can require another request and pages. A summary may omit the clue needed to choose a branch. Neither source retention nor cache efficiency establishes perfect recall, so Agent Hub keeps lexical search independently available.

The corrected compactor permits up to eight simultaneous calls. A leaf can start with fewer than eight earlier unbuilt lines; a merge needs both children. Its context stops before the first unbuilt line. Ready queues replace whole-tree work scans. Failed calls retry on the next message, superseding the older ten-second retry loop. The main chat still waits for summaries, so compactor availability affects its progress.

## 4. Cache layout and measurement limits

Turns and compactions now share a constant system/tool prefix. The Anthropic recipe groups view lines into blocks of four and marks the last complete block plus the request end. A call that would duplicate an in-flight write of a shared prefix waits until the earlier response begins. These are provider-specific request-layout instructions, not capabilities every MCP client automatically supplies.

Compactions maintain a smaller view, initially merged to **16 KB**, appended up to **32 KB**, then merged again; a main-view batch also triggers an update. The source to summarize follows this context. This replaces the old near-full main-view context and separate compactor prompt. Shortening is requested within the same conversation, retaining the original input.

The reported **98.6% turn-prefix reads** and **96.2% compaction-prefix reads** come from replaying 3,000 messages against a model of Anthropic's cache. A separate 30,000-message simulation supports the batching comparison. Neither is provider telemetry collected by Agent Hub, a benchmark run in this audit, or a guarantee across accounts, models and cache expiration. No such percentage is claimed for our native clients or worker. OptMem's earlier million-note performance report was likewise not independently benchmarked.

The source archive, derived node cache and provider prompt cache are separate. A prefix miss affects cost and latency; it does not itself erase archived records. Cheap repeated input does not establish semantic correctness or complete retention.

## 5. Deliberate Agent Hub differences

| Requirement | Implemented behavior or boundary |
| --- | --- |
| Keep native coding environments | Shared API/MCP and supported capture adapters; no ownership of native system prompts, model calls or compaction. |
| Preserve captured evidence | Immutable raw records, stable source identity and transactional provenance; summaries do not replace originals. |
| Isolate projects and computers | Explicit project assignment, scoped credentials and idempotent replay. |
| Keep retrieval practical | Scoped lexical search, bounded context packs and dyadic drill-down. The request-specific frontier uses neither upstream age-priority formula. |
| Preserve decisions with evidence | Candidate notes and explicit human review remain independent of lossy summaries; recollection is not proof that a test passed. |
| Run without a provider key | Deterministic, labelled extractive fallback; ordinary capture and retrieval make no LLM calls. |
| Optional semantic enrichment | Explicit endpoint/model, bounded input and calls, source fingerprints and recorded provider usage. No persistent sawtooth view or measured cache-hit target is implemented. |
| Shorten with the original evidence | The targeted worker change preserves base system/source/context and appends assistant/correction history under cumulative bounds. Patch verification is tracked in [CACHE_REVIEW.md](CACHE_REVIEW.md). |
| Reproducible installation | Source, adapters, setup and integration catalog live in Git; credentials, transcripts and operational databases do not. |

The optional worker's contextual roots can change early between tasks. Some static prefix may be automatically cached, but that is not the revised upstream architecture. A future cache-oriented worker would need persistent project-scoped context, request-prefix tests and real provider usage measurements while retaining source, scope and spending bounds.

## 6. Corrections retained from the original audit

- The Gist is a specification; OptMem provides note-CLI source. They are different systems.
- The old merge formula, rebuild-on-start instruction and cache layout are historical observations, not current recommendations.
- Permanent source storage does not establish perfect recall or absence of context degradation.
- Byte targets, Unicode-character limits and tokens are different units.
- The main upstream log excludes reasoning and clips tool results; subagent detail belongs to separate logs.
- An attached MCP does not itself capture conversations or install trusted lifecycle hooks.
- The screenshot's broad cache claim must be read with the revised Gist's simulation qualification.
- Requirements, current source, installed builds and historical observations answer different questions. Recollection cannot establish that a device test ran or a requirement changed.

## 7. License and provenance observations

At the OptMem commit inspected on 2026-10-07, its tree contained no license file and repository metadata reported `license: null`. [Issue 8, “license?”](https://github.com/VictorTaelin/OptMem/issues/8), was open with no retrieved comments. Those observations were not refreshed during this review. Neither inspected Gist revision contained an explicit license statement. These are factual observations, not a legal conclusion.

Agent Hub's implementation and prompts are independently written. Do not vendor downloaded research source or copy upstream system/compactor prompts into the distributed repository. Preserve the historical and corrected source links so future reviews can identify what changed and when.
