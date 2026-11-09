# trysac-eval-output-cache

Content-addressed cache of model outputs for repeatable evaluations. It hashes a canonical JSON form of the model name, messages and parameters with SHA-256, stores each output in a JSON file under a directory, and wraps an `LLMPort` so repeated model requests replay the stored output exactly.

[![Python Version](https://img.shields.io/badge/python-3.10%2B-blue)](https://python.org)
[![License: MIT](https://img.shields.io/badge/license-MIT-green)](https://opensource.org/licenses/MIT)

## Installation

```bash
pip install trysac-eval-output-cache
```

The import package is `eval_output_cache`.

## Quick start

```python
from eval_output_cache import CachingLLM, OutputCache, RecordedLLM

inner = RecordedLLM(["42"])
cache = OutputCache("cache-dir")
llm = CachingLLM(inner, cache, model="gpt-4", params={"temperature": 0})
messages = [{"role": "user", "content": "What is 6 * 7?"}]
print(llm.complete(messages, max_tokens=10))
print(llm.complete(messages, max_tokens=10))
```

The second call uses the cached output for the same canonical request; `max_tokens` is part of the cache key.

## API overview

`eval_output_cache` exports:

- `Message`: `TypedDict` with `role` in `system`, `user`, `assistant` and a string `content`.
- `LLMPort`: protocol with `complete(messages, *, max_tokens: int) -> str`.
- `cache_key(model, messages, params) -> str`: returns a 64-character lowercase SHA-256 hex digest. The payload is JSON with sorted keys, compact separators, non-ASCII characters written as UTF-8 and NaN disallowed.
- `OutputCache(directory, *, max_entries=10_000, max_output_chars=1_000_000, clock=time.time, on_event=None)`: a persistent bounded cache. `directory` accepts `Path` or `str`. `get(key)` returns the stored string or `None` on a miss or corrupt entry; `put(key, output)` writes atomically through a temporary file and `os.replace`; `len(cache)` is the number of indexed entries; `stats()` returns `CacheStats`.
- `CacheStats`: frozen dataclass with `hits`, `misses`, `writes`, `evictions`, and `corrupt` (default `0`).
- `CachingLLM(inner, cache, *, model, params)`: implements `LLMPort`; its key is `cache_key(model, messages, {**params, 'max_tokens': max_tokens})`.
- `RecordedLLM(replies)`: returns scripted replies in order and raises `RecordingExhaustedError` when exhausted.
- `FakeLLM(fn)`: calls `fn(messages)` and ignores `max_tokens`.
- `CacheError(code)`: base error with `code` set to `invalid_params`, `invalid_messages`, `invalid_key`, or `output_too_large`. The exception message is the code.

Errors and limits:

- `cache_key` raises `invalid_messages` for a non-sequence, more than 1000 messages, invalid role/content/types, or content longer than 1,000,000 characters; it raises `invalid_params` for non-string keys, unsupported values, non-finite floats, or nesting deeper than 8.
- `OutputCache.get` and `OutputCache.put` raise `invalid_key` unless the key matches `^[0-9a-f]{64}$`; `put` raises `output_too_large` when `len(output) > max_output_chars` and writes nothing.
- Eviction removes entries with the smallest `written_at`, breaking ties by the smallest key, until `len(cache) <= max_entries`.
- Entries are stored at `directory/<key[:2]>/<key>.json`; construction scans the directory and rebuilds the in-memory index.
- `on_event` receives a dict with keys `event` and `key`; `event` is one of `hit`, `miss`, `write` or `evict`, and the callback never receives message contents or outputs.
- Multiple processes writing concurrently to one directory are not supported.

## Why not `functools.lru_cache` or `joblib.Memory`

`functools.lru_cache` is in-process and keyed on Python call arguments; it does not persist outputs or define a canonical model-request key. `joblib.Memory` memoizes Python function calls to disk but does not provide this library's `LLMPort` wrapper, 64-hex key format or eviction by `written_at`. This library stores one JSON file per canonical model request and replays exactly.

Security limits and the threat model are in [docs/SECURITY.md](docs/SECURITY.md).
