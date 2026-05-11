# Local environment setup

This project keeps real API keys outside git.

## Files

- `env.example/finnhub.env.example` is the safe template committed to git.
- `env/finnhub.env` is the real local file and is ignored by git.
- `.env` and `.env.*` are also ignored for local-only overrides.

## Finnhub key setup

1. Copy `env.example/finnhub.env.example` to `env/finnhub.env`.
2. Put the real Finnhub key in `env/finnhub.env` only.
3. Do not commit files under `env/`.

## Python rule

Use only the project-local `venv/` for dependencies. Do not install Python libraries globally on this computer.

## Local runtime setup

Run this from the project root after cloning or restoring the repo:

```bash
scripts/setup_local_runtime.sh
```

The script creates `data/`, `logs/`, `env/`, `venv/`, installs `requirements.txt` into `venv/`, and syntax-checks the Python files.
