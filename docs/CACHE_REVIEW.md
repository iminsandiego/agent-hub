# Cache correction review

Reviewed **2026-10-08 04:23:22 UTC** against the restored, verified Agent Hub 0.1.0 delivery baseline and the corrected specification. The application was already implemented; this review identifies what the later upstream change means for it. It makes no claim that a native client or provider has achieved a particular cache-hit rate.

## Sources and correction

The user-supplied screenshot described VictorTaelin's cache fix and a 98%+ result. The primary [author comment, 6413482](https://gist.github.com/VictorTaelin/91837951a5ce5b38f341ec1ba1df6449#gistcomment-6413482), corroborates the update notice. The revised specification provides the qualification for its percentages.

| Reference | Revision | Content commit |
| --- | --- | --- |
| [Earlier OptChat](https://gist.github.com/VictorTaelin/91837951a5ce5b38f341ec1ba1df6449/f51fe5c910427fd6f384d22823140b1693c76207) | `f51fe5c910427fd6f384d22823140b1693c76207` | 2026-10-04 02:42:39 UTC |
| [Corrected UniiChat](https://gist.github.com/VictorTaelin/91837951a5ce5b38f341ec1ba1df6449/3c190e06f34aba0c69f49042c526093269604935) | `3c190e06f34aba0c69f49042c526093269604935` | 2026-10-08 01:58:24 UTC |

[UPSTREAM_ANALYSIS.md](UPSTREAM_ANALYSIS.md) now describes the corrected source. [SOURCES.json](SOURCES.json) retains the earlier snapshot and adds the current metadata, hashes, author comment and screenshot observation. No upstream prompt or screenshot binary is distributed.

The old merge priority used a pair's first event. The correction uses `(T - last_inclusive) / 2^level`. For ten events with a view of `0+4, 4+4, 8+1, 9+1`, the old rule selects the older 0–7 merge; the correction selects 8–9. The upstream analysis gives the numerical derivation. The factor of four in the old denominator did not change ranking.

The new recipe also appends until the view exceeds 128,000 bytes, batches merges toward 64,000, persists the view across restarts, and keeps a separate 16–32 KB compaction view. It shares constant system/tool prefixes, uses four-line cache blocks and coordinates shared-prefix writes. These are material design changes, not merely explanatory additions.

The reported **98.6% for turns** and **96.2% for compactions** come from a 3,000-message replay against a model of Anthropic's cache. This review did not rerun that simulation or measure equivalent provider behavior. A provider prompt cache is separate from Agent Hub's database and summary cache.

## Impact on the existing application

| Area | Finding | Disposition |
| --- | --- | --- |
| Archived source | The upstream merge defect concerns prompt layout; it did not alter Agent Hub's accepted event records. | No archive migration or rewriting of captured evidence is needed for this correction. |
| Retrieval tree | `Store._view` constructs a dyadic frontier and refines recent ranges. The old age-based score is absent. | Do not claim that changing that formula repairs our retrieval code. |
| Native Codex/Claude/T3 | The native application owns its system prompt, tools, model call and placement of injected context. | No native prompt-cache control or 98% guarantee is claimed. |
| Default operation | Deterministic summaries, capture and retrieval make no model calls. | The optional provider-cache issue causes no default inference charges. |
| Optional worker context | Preceding-context roots are recomputed. For example, `0..3, 4..5, 6` become `0..7`, changing the first context line. | Full persistent cache-oriented context remains unimplemented; automatic cache behavior is provider-dependent and unmeasured. |
| Shortening requests | The baseline sent a fresh request containing the prior summary and correction, without the original source/context. | Targeted continuation fix below; this affects source fidelity and the opportunity to reuse a prefix. |
| Provider integration | The worker calls an explicitly configured Chat Completions endpoint and does not own the native client's account/model/prompt. | Shared turn/compaction cache reuse cannot simply be assumed. |

The optional worker needed a real review despite the MCP boundary. Hard input and call caps constrain work but do not establish cache efficiency. Repeated tree-work selection also remains distinct from the revised upstream ready-queue scheduler; that redesign is outside this narrow correction.

## Targeted shortening patch

The patch retains the original system message and complete bounded source/context at the start of every shortening request. After an overlong answer, it appends that answer as an assistant message and the correction as a user message. A second retry retains the base and earlier exchange before appending its next answer/correction.

This keeps original evidence available and preserves the earlier request prefix. It does not guarantee a provider cache hit: endpoint behavior, model, timing and minimum cacheable prefix still matter.

The input guard counts **all message-content characters**, including the base and every appended assistant/correction message; it does not count tokens or JSON framing. One validator checks the complete conversation before call accounting and again before HTTP construction. An over-budget continuation is not sent partially. The hard 512-byte accepted-summary limit, total call cap and deterministic fallback remain in force.

The patch does not implement the upstream persisted sawtooth views, cache-block policy, native turn-cache sharing or a new measured hit rate. Original-record storage is unchanged.

## Verification status

The revised working tree passed **236 tests**, with one existing Starlette/httpx test-client deprecation warning, in **5.44 seconds**. The focused worker/admin suite passed **53 tests in 0.81 seconds**. These runs exercised the correction in version 0.1.1; the earlier 0.1.0 results remain historical evidence. Environment, commands and package verification are recorded in [VALIDATION.md](VALIDATION.md).

Focused regressions inspect actual HTTP request bodies using a mock transport: two/four/six-message shapes for the initial call and both retries, unchanged system/source/context, complete earlier-message prefixes, cumulative input rejection before either retry, provider-side guarding before HTTP construction, one/two/three-call caps, and retained fallback/original source. These are request-structure and correctness checks, not provider cache benchmarks. No paid model calls or native-client cache measurements are claimed.
