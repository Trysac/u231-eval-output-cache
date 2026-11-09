# Security notes

## Threat model

`eval_output_cache` stores model outputs in plaintext JSON files and returns them to callers. It validates request inputs and bounds sizes, but it is not an access-control or encryption layer.

### Defended

- Message validation before hashing: at most 1000 messages, roles limited to `system`, `user` and `assistant`, string content, and at most 1,000,000 characters per content string. Invalid input raises `CacheError` with code `invalid_messages`.
- Parameter validation before hashing: string keys, JSON scalars, lists and dicts, finite floats, and nesting depth at most 8. Invalid input raises `CacheError` with code `invalid_params`.
- Key validation: `OutputCache.get` and `OutputCache.put` accept only keys matching `^[0-9a-f]{64}$`; other keys raise `CacheError` with code `invalid_key`.
- Output length validation: `put` rejects outputs longer than `max_output_chars` (default 1,000,000) with code `output_too_large` before writing.
- Atomic writes: `put` writes through a temporary file in the target directory, flushes, calls `fsync`, then uses `os.replace`; on failure it removes the temporary file.
- Corrupt-entry handling: malformed JSON files are marked corrupt during the directory scan; `get` on a corrupt entry returns `None` and increments `CacheStats.corrupt` without raising.
- Event isolation: `on_event` receives only `event` and `key` values (`hit`, `miss`, `write`, `evict`), never message contents or outputs.
- Bounded index: `max_entries` defaults to 10,000 and eviction removes entries with the smallest `written_at`, breaking ties by the smallest key.
- No dynamic code execution: the code uses `json` and standard-library file APIs; it does not call `eval` or `exec`.
- No runtime dependencies: the package uses only Python standard-library modules.

### Not defended

- Confidentiality at rest: outputs are stored as plaintext JSON under `directory/<key[:2]>/<key>.json`; there is no encryption, access control or permission management.
- Secure deletion: eviction unlinks files with `Path.unlink`, but the code cannot guarantee physical erasure by the filesystem or backups.
- Cache-key secrecy: keys are deterministic SHA-256 hashes, not keyed MACs; anyone who can reconstruct a request can compute its key.
- Concurrent writers: the code has no file locking; multiple processes writing to the same directory are unsupported and may race.
- Expiry and revocation: there is no TTL; entries remain until overwritten, evicted or removed outside the library.
- Hostile directory contents: construction scans recursively for files named as 64 lowercase hex characters plus `.json`; it reads and JSON-parses matching files without a file-size or scan-count limit before eviction is applied.
- Output sanitization: model outputs are stored and returned verbatim up to `max_output_chars`; the library does not validate or escape their contents.
- Callback trust: `on_event` is caller-supplied and receives cache keys; whatever the callback logs or does with those keys is outside the library's control.

## Publishing

The repository contains no publishing automation. The package is standard-library only and declares no runtime dependencies in the code shown here. Release permissions and artifact distribution are outside this code.
