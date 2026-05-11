# Local environment setup

This project keeps real API keys outside git.

## Files

- `env.example/finnhub.env.example` is the safe Finnhub template committed to git.
- `env/finnhub.env` is the real local Finnhub file and is ignored by git.
- `env.example/llm_summary.env.example` is the safe optional AI-summary template committed to git.
- `env/llm_summary.env` is the real local AI-summary file and is ignored by git.
- `.env` and `.env.*` are also ignored for local-only overrides.

## Finnhub key setup

1. Copy `env.example/finnhub.env.example` to `env/finnhub.env`.
2. Put the real Finnhub key in `env/finnhub.env` only.
3. Do not commit files under `env/`.

## Optional AI summary key setup

Part 6 is intentionally on hold until Boz chooses and adds a cheap AI API key.

1. Copy `env.example/llm_summary.env.example` to `env/llm_summary.env`.
2. Put the real AI API key and model settings in `env/llm_summary.env` only.
3. Leave `LLM_SUMMARY_ENABLED=0` until the summary code is implemented and tested.
4. Do not commit files under `env/`.

The planned part-6 implementation should use an OpenAI-compatible HTTP API when possible so no provider SDK dependency is needed.

## Python rule

Use only the project-local `venv/` for dependencies. Do not install Python libraries globally on this computer.

## Local runtime setup

Run this from the project root after cloning or restoring the repo:

```bash
scripts/setup_local_runtime.sh
```

The script creates `data/`, `logs/`, `env/`, `env/finnhub.env`, `env/llm_summary.env`, and `venv/`, installs `requirements.txt` into `venv/`, and syntax-checks the Python files.
