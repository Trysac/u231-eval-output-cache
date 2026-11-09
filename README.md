# eval-output-cache

[![PyPI version](https://img.shields.io/pypi/v/trysac-eval-output-cache)](https://pypi.org/project/trysac-eval-output-cache/)
[![License: MIT](https://img.shields.io/pypi/l/trysac-eval-output-cache)](LICENSE)
[![CI](https://github.com/Trysac/u231-eval-output-cache/actions/workflows/ci.yml/badge.svg)](https://github.com/Trysac/u231-eval-output-cache/actions/workflows/ci.yml)

Content-addressed cache of model outputs for repeatable evaluations: canonical request keys, a bounded on-disk store and a caching LLM port

## Problem

Describe in two or three sentences the concrete problem this utility solves, who hits it, and what
they do today without it. Replace this paragraph when the first real feature lands.

## Install

```sh
pip install trysac-eval-output-cache
# or
uv add trysac-eval-output-cache
```

Requires Python 3.10 or newer. No runtime dependencies.

## Usage

```python
import eval_output_cache

# normalize() trims surrounding whitespace and lower-cases the text.
print(eval_output_cache.normalize("  Hello World "))  # -> "hello world"

# Blank input is rejected explicitly instead of returning an empty string.
try:
    eval_output_cache.normalize("   ")
except ValueError as exc:
    print(f"rejected: {exc}")
```

## Documentation

- [Architecture](docs/ARCHITECTURE.md) and [decisions](docs/decisions/)
- [Testing](docs/TESTING.md) and [security](docs/SECURITY.md)
- [Project record](docs/PROJECT.md) and [stack](docs/STACK.md)
- [Changelog](CHANGELOG.md) and [contributing guide](CONTRIBUTING.md)

## License

[MIT](LICENSE) (c) 2026 Miguel Gomez
