#!/usr/bin/env bash
# Use the Bash shell because this setup script relies on Bash-safe options and path handling.

set -euo pipefail
# Stop immediately on errors, missing variables, or failed commands inside pipelines so setup cannot silently half-finish.

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# Find the absolute path of the project root by going one folder up from this script's folder.

cd "$REPO_DIR"
# Change into the project root so every relative path below points at the correct project files.

mkdir -p data
# Create the local data-cache folder if it does not already exist.

mkdir -p logs
# Create the local log folder used by cron jobs and manual refresh runs.

mkdir -p env
# Create the ignored local environment folder where real API-key files can live safely.

if [ ! -f env/finnhub.env ]; then
# Check whether the local Finnhub env file is missing before creating a safe placeholder.
    cp env.example/finnhub.env.example env/finnhub.env
# Copy the committed safe template into the ignored local env folder for Boz to edit later.
fi
# Finish the conditional block that creates the local Finnhub env file only when needed.

if [ ! -f env/llm_summary.env ]; then
# Check whether the optional AI-summary env file is missing before creating a safe placeholder.
    cp env.example/llm_summary.env.example env/llm_summary.env
# Copy the committed safe AI-summary template into the ignored local env folder for Boz to edit later.
fi
# Finish the conditional block that creates the local AI-summary env file only when needed.

if [ ! -f env/brave_search.env ]; then
# Check whether the optional Brave Search env file is missing before creating a safe placeholder.
    cp env.example/brave_search.env.example env/brave_search.env
# Copy the committed safe Brave Search template into the ignored local env folder for macro actual enrichment.
fi
# Finish the conditional block that creates the local Brave Search env file only when needed.

if [ ! -f env/database.env ]; then
# Check whether the optional database env file is missing before creating a safe placeholder.
    cp env.example/database.env.example env/database.env
# Copy the committed safe database template into the ignored local env folder for future DB work.
fi
# Finish the conditional block that creates the local database env file only when needed.

chmod 600 env/*.env 2>/dev/null || true
# Restrict local env files to the current user when possible, while allowing setup to continue on filesystems that do not support chmod.

if [ ! -d venv ]; then
# Check whether the project-local Python virtual environment is missing.
    python3 -m venv venv
# Create a project-local virtual environment so Python packages are installed inside this repo, not globally.
fi
# Finish the conditional block that creates the virtual environment only when needed.

venv/bin/python -m pip install --upgrade pip
# Upgrade pip inside the project-local virtual environment, not in the system Python installation.

venv/bin/python -m pip install -r requirements.txt
# Install the project's declared Python dependencies into the project-local virtual environment.

venv/bin/python scripts/prepare_local_data_cache.py
# Restore legacy root CSV caches into data/ when needed and normalize daily dates safely.

venv/bin/python -m py_compile *.py scripts/*.py
# Compile-check the project Python files using the virtual environment to catch syntax errors early.

venv/bin/python scripts/db_migrate.py --dry-run
# Validate database migration files without requiring PostgreSQL to be running.

printf 'Local runtime setup complete. Activate with: source venv/bin/activate\n'
# Print the command Boz or a future assistant can use to activate this project's virtual environment.
