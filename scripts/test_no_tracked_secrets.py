#!/usr/bin/env python3
"""Fail when secret-bearing local paths or obvious real credential assignments are tracked."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SENSITIVE_VARIABLES = {
    "BRAVE_SEARCH_API_KEY",
    "DATABASE_URL",
    "FINNHUB_API_KEY",
    "GEMINI_API_KEY",
    "GEMINI_CALENDAR_ACTUALS_API_KEY",
}
PLACEHOLDER_MARKERS = (
    "***",
    "<",
    "change-me",
    "example",
    "placeholder",
    "put-your",
    "your_",
    "your-",
    "…",
)


def _tracked_files() -> list[str]:
    result = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=ROOT,
        check=True,
        capture_output=True,
    )
    return [path.decode("utf-8") for path in result.stdout.split(b"\0") if path]


def _sensitive_path(path: str) -> bool:
    parts = Path(path).parts
    name = Path(path).name.lower()
    return (
        (parts and parts[0] == "env")
        or name == ".pgpass"
        or name == ".env"
        or name.startswith(".env.")
    )


def _looks_like_placeholder(value: str) -> bool:
    normalized = value.strip().strip("\"'").lower()
    return not normalized or any(marker in normalized for marker in PLACEHOLDER_MARKERS)


def main() -> None:
    tracked = _tracked_files()
    problems = [f"tracked sensitive path: {path}" for path in tracked if _sensitive_path(path)]
    assignment = re.compile(
        rf"^\s*(?:export\s+)?({'|'.join(sorted(SENSITIVE_VARIABLES))})\s*=\s*(.*?)\s*$",
        re.MULTILINE,
    )
    for relative_path in tracked:
        path = ROOT / relative_path
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for variable, value in assignment.findall(text):
            if not _looks_like_placeholder(value):
                problems.append(f"possible real credential assignment: {relative_path}:{variable}")

    if problems:
        raise SystemExit("\n".join(problems))
    print(f"tracked secret safety test passed for {len(tracked)} file(s)")


if __name__ == "__main__":
    main()
