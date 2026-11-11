# Testing

## Running

The tests are in `tests/test_eval_output_cache.py` and use pytest and `tmp_path`. Run:

```sh
pytest tests/test_eval_output_cache.py
```

## Policy

The suite imports the public package `eval_output_cache` and checks exact values. It covers:

- `cache_key`: exact SHA-256 digest, sensitivity to model, message and parameter changes, parameter-order irrelevance, rejection of NaN, invalid roles, depth greater than 8, more than 1000 messages, content longer than 1,000,000 characters, Unicode content with `ensure_ascii=False`, and an empty message list.
- `OutputCache`: persistence across instances, string directory input, unknown keys returning `None`, invalid keys raising `invalid_key`, eviction with an injected clock and `max_entries=2`, overwrite without eviction, rejection of outputs larger than `max_output_chars`, corrupt files returning `None` and incrementing `corrupt`, and empty output strings cached and returned as hits.
- `CachingLLM`: cached results, `max_tokens` participating in the key so a different value calls the inner LLM again and raises `RecordingExhaustedError`, and replay of empty output strings.
- `FakeLLM` calling its function and `RecordedLLM` raising `RecordingExhaustedError` when scripted replies run out.
- `on_event`: payloads containing the expected `write`, `hit` and `miss` event and key pairs.

## Tiers

The supplied code has a single test module; it defines no separate local, CI or conformance tiers and no marker-based selection.

## Layout

`tests/test_eval_output_cache.py` is the only test file. No `tests/conftest.py` or shared fixture file is included.
