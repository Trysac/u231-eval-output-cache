"""Content-addressed cache for evaluation outputs.

The cache keys each model call on a canonical JSON serialization of the model name,
messages, and parameters (including ``max_tokens``). Outputs are stored on disk
under a directory derived from the first two hex characters of the key, and an
in-memory index tracks entries for fast lookup and eviction.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import logging
import math
import os
import re
import tempfile
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Protocol, TypedDict

logger = logging.getLogger(__name__)
logger.addHandler(logging.NullHandler())

_KEY_RE = re.compile(r"^[0-9a-f]{64}$")
_MAX_MESSAGES = 1000
_MAX_MESSAGE_CONTENT_CHARS = 1_000_000
_MAX_PARAMS_DEPTH = 8


class CacheError(Exception):
    """Base error raised by the cache."""

    def __init__(
        self,
        code: Literal["invalid_params", "invalid_messages", "invalid_key", "output_too_large"],
    ) -> None:
        self.code = code
        super().__init__(code)


class Message(TypedDict):
    role: Literal["system", "user", "assistant"]
    content: str


class LLMPort(Protocol):
    def complete(self, messages: Sequence[Message], *, max_tokens: int) -> str: ...


class RecordingExhaustedError(Exception):
    """Raised when a RecordedLLM runs out of scripted replies."""


class RecordedLLM:
    """Returns scripted replies in order; raises when exhausted."""

    def __init__(self, replies: Sequence[str]) -> None:
        self._replies = list(replies)
        self._index = 0

    def complete(self, messages: Sequence[Message], *, max_tokens: int) -> str:
        if self._index >= len(self._replies):
            raise RecordingExhaustedError
        reply = self._replies[self._index]
        self._index += 1
        return reply


class FakeLLM:
    """Calls a function with the messages; ignores max_tokens."""

    def __init__(self, fn: Callable[[Sequence[Message]], str]) -> None:
        self._fn = fn

    def complete(self, messages: Sequence[Message], *, max_tokens: int) -> str:
        return self._fn(messages)


def _validate_messages(messages: Sequence[Message]) -> None:
    if not isinstance(messages, Sequence) or isinstance(messages, (str, bytes)):
        raise CacheError("invalid_messages")
    if len(messages) > _MAX_MESSAGES:
        raise CacheError("invalid_messages")
    for msg in messages:
        if not isinstance(msg, Mapping):
            raise CacheError("invalid_messages")
        if "role" not in msg or "content" not in msg:
            raise CacheError("invalid_messages")
        if msg["role"] not in ("system", "user", "assistant"):
            raise CacheError("invalid_messages")
        if not isinstance(msg["content"], str):
            raise CacheError("invalid_messages")
        if len(msg["content"]) > _MAX_MESSAGE_CONTENT_CHARS:
            raise CacheError("invalid_messages")


def _validate_params(params: Mapping[str, object], depth: int = 0) -> None:
    if depth > _MAX_PARAMS_DEPTH:
        raise CacheError("invalid_params")
    for key, value in params.items():
        if not isinstance(key, str):
            raise CacheError("invalid_params")
        _validate_param_value(value, depth + 1)


def _validate_param_value(value: object, depth: int) -> None:
    if depth > _MAX_PARAMS_DEPTH:
        raise CacheError("invalid_params")
    if value is None or isinstance(value, (str, bool, int)):
        return
    if isinstance(value, float):
        if not math.isfinite(value):
            raise CacheError("invalid_params")
        return
    if isinstance(value, dict):
        _validate_params(value, depth)
        return
    if isinstance(value, list):
        for item in value:
            _validate_param_value(item, depth + 1)
        return
    raise CacheError("invalid_params")


def cache_key(model: str, messages: Sequence[Message], params: Mapping[str, object]) -> str:
    """Return a canonical SHA-256 hex digest for a model request."""
    _validate_messages(messages)
    _validate_params(params)
    payload = {
        "model": model,
        "messages": list(messages),
        "params": dict(params),
    }
    serialized = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class CacheStats:
    hits: int
    misses: int
    writes: int
    evictions: int
    corrupt: int = 0


@dataclass
class _Entry:
    output: str | None
    written_at: float
    corrupt: bool


class OutputCache:
    """Bounded on-disk cache of model outputs.

    Keys are 64-character lowercase hex strings (typically produced by
    :func:`cache_key`). Outputs are stored as JSON files under
    ``directory/<key[:2]>/<key>.json``. The cache is rebuilt by scanning the
    directory on instantiation; eviction removes entries with the smallest
    ``written_at`` timestamp, breaking ties by the smallest key, until the
    total number of entries does not exceed ``max_entries``.
    """

    def __init__(
        self,
        directory: Path | str,
        *,
        max_entries: int = 10_000,
        max_output_chars: int = 1_000_000,
        clock: Callable[[], float] = time.time,
        on_event: Callable[[dict[str, str]], None] | None = None,
    ) -> None:
        self._directory = Path(directory)
        self._max_entries = max_entries
        self._max_output_chars = max_output_chars
        self._clock = clock
        self._on_event = on_event
        self._index: dict[str, _Entry] = {}
        self._hits = 0
        self._misses = 0
        self._writes = 0
        self._evictions = 0
        self._corrupt = 0
        self._directory.mkdir(parents=True, exist_ok=True)
        self._scan_directory()
        while len(self._index) > self._max_entries:
            self._evict_one()

    def _scan_directory(self) -> None:
        for root, _dirs, files in os.walk(self._directory):
            for filename in files:
                match = re.fullmatch(r"([0-9a-f]{64})\.json", filename)
                if not match:
                    continue
                key = match.group(1)
                path = Path(root) / filename
                try:
                    data = json.loads(path.read_text(encoding="utf-8"))
                    if not isinstance(data, dict):
                        raise ValueError
                    output = data.get("output")
                    written_at = data.get("written_at")
                    if not isinstance(output, str) or not isinstance(written_at, (int, float)):
                        raise ValueError
                    entry = _Entry(output=output, written_at=float(written_at), corrupt=False)
                except Exception:
                    entry = _Entry(output=None, written_at=0.0, corrupt=True)
                self._index[key] = entry

    def _entry_path(self, key: str) -> Path:
        return self._directory / key[:2] / (key + ".json")

    def _remove_file(self, key: str) -> None:
        path = self._entry_path(key)
        try:
            path.unlink(missing_ok=True)
        except OSError:
            logger.debug("failed to remove file for key %s", key)

    def _evict_one(self) -> None:
        if not self._index:
            return
        candidate_key = min(
            self._index,
            key=lambda k: (self._index[k].written_at, k),
        )
        self._index.pop(candidate_key, None)
        self._remove_file(candidate_key)
        self._evictions += 1
        self._emit("evict", candidate_key)

    def _emit(self, event: Literal["hit", "miss", "write", "evict"], key: str) -> None:
        if self._on_event is not None:
            self._on_event({"event": event, "key": key})

    def _validate_key(self, key: str) -> None:
        if not _KEY_RE.fullmatch(key):
            raise CacheError("invalid_key")

    def get(self, key: str) -> str | None:
        """Return the cached output for *key*, or ``None`` on a miss or corruption."""
        self._validate_key(key)
        entry = self._index.get(key)
        if entry is None:
            self._misses += 1
            self._emit("miss", key)
            return None
        if entry.corrupt:
            self._corrupt += 1
            self._emit("miss", key)
            return None
        self._hits += 1
        self._emit("hit", key)
        return entry.output

    def put(self, key: str, output: str) -> None:
        """Store *output* under *key*, overwriting any existing entry."""
        self._validate_key(key)
        if len(output) > self._max_output_chars:
            raise CacheError("output_too_large")
        path = self._entry_path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        written_at = self._clock()
        data = {"output": output, "written_at": written_at}
        fd, tmp_path = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as tmp:
                json.dump(data, tmp, ensure_ascii=False)
                tmp.flush()
                os.fsync(tmp.fileno())
            os.replace(tmp_path, path)
        except BaseException:
            with contextlib.suppress(OSError):
                os.unlink(tmp_path)
            raise
        self._index[key] = _Entry(output=output, written_at=written_at, corrupt=False)
        self._writes += 1
        self._emit("write", key)
        while len(self._index) > self._max_entries:
            self._evict_one()

    def __len__(self) -> int:
        return len(self._index)

    def stats(self) -> CacheStats:
        """Return a snapshot of the cache statistics."""
        return CacheStats(
            hits=self._hits,
            misses=self._misses,
            writes=self._writes,
            evictions=self._evictions,
            corrupt=self._corrupt,
        )


class CachingLLM:
    """Wraps an LLM port and caches its responses using an :class:`OutputCache`.

    The cache key is derived from ``model``, the provided ``messages``, and the
    merged parameters (``params`` plus ``max_tokens``)."""

    def __init__(
        self,
        inner: LLMPort,
        cache: OutputCache,
        *,
        model: str,
        params: Mapping[str, object],
    ) -> None:
        self._inner = inner
        self._cache = cache
        self._model = model
        self._params = dict(params)

    def complete(self, messages: Sequence[Message], *, max_tokens: int) -> str:
        key = cache_key(self._model, messages, {**self._params, "max_tokens": max_tokens})
        cached = self._cache.get(key)
        if cached is not None:
            return cached
        output = self._inner.complete(messages, max_tokens=max_tokens)
        self._cache.put(key, output)
        return output


__all__ = [
    "CacheError",
    "CacheStats",
    "CachingLLM",
    "FakeLLM",
    "LLMPort",
    "Message",
    "OutputCache",
    "RecordedLLM",
    "RecordingExhaustedError",
    "cache_key",
]
