"""Tests for the eval_output_cache package."""

import hashlib
from collections.abc import Sequence
from pathlib import Path

import pytest

from eval_output_cache import (
    CacheError,
    CacheStats,
    CachingLLM,
    FakeLLM,
    Message,
    OutputCache,
    RecordedLLM,
    RecordingExhaustedError,
    cache_key,
)


def make_messages(*roles_and_contents: tuple[str, str]) -> list[Message]:
    """Build a list of valid messages from a shorthand list."""
    return [
        {"role": role, "content": content}  # type: ignore[typeddict-item]
        for role, content in roles_and_contents
    ]


def test_cache_key_exact_hash() -> None:
    messages = make_messages(("user", "hi"))
    params = {"temperature": 0}
    expected = hashlib.sha256(
        b'{"messages":[{"content":"hi","role":"user"}],"model":"m","params":{"temperature":0}}'
    ).hexdigest()
    assert cache_key("m", messages, params) == expected


def test_cache_key_changes_with_model_message_param() -> None:
    base = cache_key("m", make_messages(("user", "hi")), {"temperature": 0})
    assert cache_key("other", make_messages(("user", "hi")), {"temperature": 0}) != base
    assert cache_key("m", make_messages(("user", "hello")), {"temperature": 0}) != base
    assert cache_key("m", make_messages(("user", "hi")), {"temperature": 1}) != base


def test_cache_key_params_order_irrelevant() -> None:
    key1 = cache_key("m", make_messages(("user", "hi")), {"temperature": 0, "n": 1})
    key2 = cache_key("m", make_messages(("user", "hi")), {"n": 1, "temperature": 0})
    assert key1 == key2


def test_cache_key_nan_param_raises_invalid_params() -> None:
    with pytest.raises(CacheError) as exc_info:
        cache_key("m", make_messages(("user", "hi")), {"temperature": float("nan")})
    assert exc_info.value.code == "invalid_params"


def test_cache_key_invalid_role_raises_invalid_messages() -> None:
    messages = [{"role": "tool", "content": "hi"}]  # type: ignore[typeddict-item]
    with pytest.raises(CacheError) as exc_info:
        cache_key("m", messages, {})
    assert exc_info.value.code == "invalid_messages"


def test_cache_key_rejects_too_deep_params() -> None:
    params = {"a": {"b": {"c": {"d": {"e": {"f": {"g": {"h": {"i": 1}}}}}}}}}
    with pytest.raises(CacheError) as exc_info:
        cache_key("m", [], params)
    assert exc_info.value.code == "invalid_params"


def test_cache_key_rejects_too_many_messages() -> None:
    messages = [{"role": "user", "content": "x"}] * 1001
    with pytest.raises(CacheError) as exc_info:
        cache_key("m", messages, {})
    assert exc_info.value.code == "invalid_messages"


def test_cache_key_rejects_overlong_content() -> None:
    messages = [{"role": "user", "content": "x" * 1_000_001}]
    with pytest.raises(CacheError) as exc_info:
        cache_key("m", messages, {})
    assert exc_info.value.code == "invalid_messages"


def test_output_cache_persists_across_instances(tmp_path: Path) -> None:
    key = "a" * 64
    cache1 = OutputCache(tmp_path)
    cache1.put(key, "answer")
    cache2 = OutputCache(tmp_path)
    assert cache2.get(key) == "answer"


def test_output_cache_accepts_str_directory(tmp_path: Path) -> None:
    key = "a" * 64
    cache = OutputCache(str(tmp_path))
    cache.put(key, "answer")
    assert OutputCache(str(tmp_path)).get(key) == "answer"


def test_output_cache_get_unknown_key_returns_none(tmp_path: Path) -> None:
    cache = OutputCache(tmp_path)
    assert cache.get("b" * 64) is None


def test_output_cache_invalid_key_raises(tmp_path: Path) -> None:
    cache = OutputCache(tmp_path)
    with pytest.raises(CacheError) as exc_info:
        cache.get("not-a-key")
    assert exc_info.value.code == "invalid_key"
    with pytest.raises(CacheError) as exc_info:
        cache.put("BAD_KEY", "x")
    assert exc_info.value.code == "invalid_key"


def test_output_cache_eviction_with_injected_clock(tmp_path: Path) -> None:
    clock_values = [1.0, 2.0, 3.0]
    clock = iter(clock_values).__next__
    cache = OutputCache(tmp_path, max_entries=2, clock=clock)
    keys = ["1" * 64, "2" * 64, "3" * 64]
    outputs = ["one", "two", "three"]
    for key, out in zip(keys, outputs, strict=False):
        cache.put(key, out)
    assert len(cache) == 2
    stats = cache.stats()
    assert stats == CacheStats(hits=0, misses=0, writes=3, evictions=1)
    # First key should be evicted
    assert cache.get(keys[0]) is None
    assert cache.get(keys[1]) == "two"
    assert cache.get(keys[2]) == "three"


def test_output_cache_overwrite_does_not_evict(tmp_path: Path) -> None:
    cache = OutputCache(tmp_path, max_entries=2)
    key = "c" * 64
    cache.put(key, "old")
    cache.put(key, "new")
    assert len(cache) == 1
    assert cache.get(key) == "new"
    stats = cache.stats()
    assert stats.writes == 2
    assert stats.evictions == 0


def test_caching_llm_caches_results(tmp_path: Path) -> None:
    recorded = RecordedLLM(["x"])
    cache = OutputCache(tmp_path)
    caching = CachingLLM(recorded, cache, model="m", params={})
    messages = make_messages(("user", "hello"))
    first = caching.complete(messages, max_tokens=10)
    second = caching.complete(messages, max_tokens=10)
    assert first == "x"
    assert second == "x"
    stats = cache.stats()
    assert stats.hits == 1
    assert stats.misses == 1
    assert stats.writes == 1


def test_caching_llm_different_max_tokens_calls_again_and_exhausts(
    tmp_path: Path,
) -> None:
    recorded = RecordedLLM(["x"])
    cache = OutputCache(tmp_path)
    caching = CachingLLM(recorded, cache, model="m", params={})
    messages = make_messages(("user", "hello"))
    assert caching.complete(messages, max_tokens=10) == "x"
    with pytest.raises(RecordingExhaustedError):
        caching.complete(messages, max_tokens=11)


def test_output_cache_rejects_too_large_output(tmp_path: Path) -> None:
    cache = OutputCache(tmp_path, max_output_chars=5)
    key = "d" * 64
    with pytest.raises(CacheError) as exc_info:
        cache.put(key, "x" * 6)
    assert exc_info.value.code == "output_too_large"
    assert cache.get(key) is None  # nothing written


def test_output_cache_corrupt_entry_returns_none_and_counts_corrupt(
    tmp_path: Path,
) -> None:
    cache = OutputCache(tmp_path)
    key = "e" * 64
    cache.put(key, "ok")
    # Corrupt the file
    path = tmp_path / key[:2] / (key + ".json")
    path.write_text("{not json", encoding="utf-8")
    # Rebuild
    cache2 = OutputCache(tmp_path)
    assert cache2.get(key) is None
    stats = cache2.stats()
    assert stats.corrupt == 1


def test_on_event_callback_receives_expected_payloads(tmp_path: Path) -> None:
    events: list[dict[str, str]] = []
    cache = OutputCache(tmp_path, on_event=events.append)
    key = "f" * 64
    cache.put(key, "val")
    cache.get(key)
    cache.get("0" * 64)  # miss
    cache.put("1" * 64, "other")
    # Check events subset
    assert {"event": "write", "key": key} in events
    assert {"event": "hit", "key": key} in events
    assert {"event": "miss", "key": "0" * 64} in events


def test_fake_llm_calls_function(tmp_path: Path) -> None:
    def fake_fn(messages: Sequence[Message]) -> str:
        return "fake"

    llm = FakeLLM(fake_fn)
    assert llm.complete(make_messages(("user", "hi")), max_tokens=10) == "fake"


def test_recorded_llm_raises_when_exhausted() -> None:
    llm = RecordedLLM(["a"])
    assert llm.complete([], max_tokens=1) == "a"
    with pytest.raises(RecordingExhaustedError):
        llm.complete([], max_tokens=1)


def test_cache_key_unicode_content_uses_ensure_ascii_false() -> None:
    messages = make_messages(("user", "héllo ✓"))
    expected = hashlib.sha256(
        '{"messages":[{"content":"héllo ✓","role":"user"}],"model":"m","params":{}}'.encode()
    ).hexdigest()
    assert cache_key("m", messages, {}) == expected


def test_cache_key_empty_messages_list() -> None:
    expected = hashlib.sha256(b'{"messages":[],"model":"m","params":{}}').hexdigest()
    assert cache_key("m", [], {}) == expected


def test_output_cache_empty_output_is_cached_not_a_miss(tmp_path: Path) -> None:
    cache = OutputCache(tmp_path)
    key = "a" * 64
    cache.put(key, "")
    assert cache.get(key) == ""
    stats = cache.stats()
    assert stats.hits == 1
    assert stats.misses == 0


def test_caching_llm_replays_empty_output(tmp_path: Path) -> None:
    recorded = RecordedLLM([""])
    cache = OutputCache(tmp_path)
    caching = CachingLLM(recorded, cache, model="m", params={})
    messages = make_messages(("user", "hello"))
    assert caching.complete(messages, max_tokens=10) == ""
    assert caching.complete(messages, max_tokens=10) == ""
    assert cache.stats().hits == 1
