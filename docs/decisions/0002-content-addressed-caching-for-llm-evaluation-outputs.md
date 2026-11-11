# Content-addressed caching for LLM evaluation outputs

Status: accepted (generated, pending human review)

## Context

Re-running evaluation suites should not call the model again; outputs must be reproducible and comparable across runs. Ad hoc prompt-keyed caches miss when parameters or model changes, and hit when they shouldn't.

## Decision

Implement a content-addressed cache where each request is keyed by the canonical JSON serialization of model, messages, and parameters, using SHA-256. Store outputs on disk with a bounded size and eviction based on write time. Provide a `CachingLLM` wrapper that transparently uses the cache.

## Consequences

Evaluations become deterministic and cheaper when repeated. The cache persists across processes and is inspectable. Input size limits and corruption handling ensure robustness. Concurrency across processes is explicitly unsupported.
