# Project record

## Objective

Content-addressed cache of model outputs for repeatable evaluations: canonical request keys, a bounded on-disk store and a caching LLM port.

## Scope

In scope:

- `cache_key` for a canonical SHA-256 request key over model, messages and params.
- `OutputCache` as a persistent, bounded store with `get`, `put`, `__len__` and `stats`.
- `CachingLLM` as an `LLMPort` wrapper that replays stored outputs.
- `RecordedLLM`, `FakeLLM`, `CacheError`, `CacheStats`, `Message` and `RecordingExhaustedError`.

Out of scope:

- semantic or fuzzy matching;
- TTL expiry;
- sharing a cache across machines;
- concurrent writers from several processes, which the code does not support.

## Timeline

The code and specification do not record timeline entries.

## Effort metrics

Measured values only; a value that has not been measured stays "pending measurement".

| Metric | Value |
|---|---|
| Tokens (input / output) | 626994 / 55255 |
| Hours (human) | pending measurement |
| Cost (USD) | 0.0783 |

## Factory run u231 (measured from API usage)

| Phase | Model | Batch | Input | Output | Cache write | Cache read | Cost (USD) |
|---|---|---|---|---|---|---|---|
| generation | deepseek-v4-pro | yes | 4803 | 15419 | 0 | 0 | 0.0337 |
| fix-1 | deepseek-flash | no | 8448 | 2281 | 0 | 28928 | 0.0027 |
| audit | deepseek-flash | no | 27114 | 20616 | 0 | 340096 | 0.0175 |
| fix-2 | deepseek-flash | no | 19743 | 2623 | 0 | 124928 | 0.0049 |
| docs | deepseek-flash | no | 72678 | 14316 | 0 | 256 | 0.0195 |

Total: $0.0783. Prices: deepseek line, as measured by its adapter.
