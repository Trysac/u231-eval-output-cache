# Architecture

This package implements a content-addressed, bounded, persistent cache for LLM outputs.

## Design decisions

- **Canonical keys**: `cache_key` serializes the model name, messages, and parameters (including `max_tokens`) into a deterministic JSON payload and hashes with SHA-256. Key order within `params` does not affect the key.
- **On-disk storage**: Each entry is stored as a JSON file under `directory/<first-2-hex-chars>/<key>.json`. The file contains the output and a `written_at` timestamp. Writes are atomic via a temporary file and `os.replace`.
- **Eviction**: The cache enforces `max_entries` by removing entries with the smallest `written_at`, breaking ties by the smallest key. This mimics LRU behavior when the clock is monotonic.
- **Corruption handling**: Corrupt files are detected during scanning; a `get` on a corrupt entry returns `None` and increments the `corrupt` statistic without raising.
- **Input limits**: Messages are limited to 1000 entries and 1,000,000 characters per content string. Parameters are recursively validated to a depth of 8 and must be JSON-scalar, list, or dict types. Invalid inputs raise `CacheError` with a machine-readable code.
- **Portability**: The implementation uses only the Python standard library.
