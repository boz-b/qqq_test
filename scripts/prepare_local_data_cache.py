#!/usr/bin/env python3
# Use the project virtual environment's Python interpreter when this script is run from setup or maintenance commands.

"""Prepare local CSV caches for the qqq_test data pipeline."""
# Explain the purpose of this file in one short module-level string.

from __future__ import annotations
# Allow modern type hints without forcing Python to resolve every type name immediately.

import json
# Import JSON support so event rows can be rebuilt from public/data/*.json files.

import shutil
# Import Python's safe file-copy helper so metadata such as modified time can be preserved.

from pathlib import Path
# Import Path so file and folder paths can be built safely without manual string concatenation.

import pandas as pd
# Import pandas because the daily CSV date column needs timezone-safe parsing and rewriting.

BASE_DIR = Path(__file__).resolve().parents[1]
# Find the project root by taking the parent of the scripts/ folder that contains this file.

DATA_DIR = BASE_DIR / "data"
# Build the canonical local data-cache folder path used by the dashboard and export scripts.

LEGACY_FILES = {
    # Map old repo-root cache filenames to their canonical data/ cache filenames.
    "qqq_1m.csv": DATA_DIR / "qqq_1m.csv",
    # Map the old intraday price CSV to the canonical intraday cache path.
    "qqq_daily.csv": DATA_DIR / "qqq_daily.csv",
    # Map the old daily price CSV to the canonical daily cache path.
    "ff_events.csv": DATA_DIR / "ff_events.csv",
    # Map the old event CSV to the canonical combined-events cache path.
}
# Finish the mapping of legacy cache files to canonical cache files.


def _copy_legacy_file_if_needed(source: Path, target: Path) -> None:
    """Copy one legacy root CSV into data/ when the canonical file is missing."""
    # Explain that this helper keeps existing canonical files untouched.
    if target.exists():
        # If the canonical data/ file already exists, do not overwrite newer local cache data.
        print(f"[prepare_local_data_cache] keeping existing {target.relative_to(BASE_DIR)}")
        # Tell the operator which existing canonical cache file was preserved.
        return
        # Stop this helper early because there is nothing to copy.

    if not source.exists():
        # If the old repo-root fallback file is missing too, there is nothing to restore from.
        print(f"[prepare_local_data_cache] no legacy source for {target.relative_to(BASE_DIR)}")
        # Tell the operator that this specific cache file could not be restored locally.
        return
        # Stop this helper early because no source file exists.

    shutil.copy2(source, target)
    # Copy the legacy CSV into data/ while preserving useful file metadata.

    print(f"[prepare_local_data_cache] copied {source.name} -> {target.relative_to(BASE_DIR)}")
    # Tell the operator exactly which legacy cache file was copied.


def _normalize_daily_csv(path: Path) -> None:
    """Rewrite daily CSV date labels so mixed daylight-saving offsets cannot break pandas."""
    # Explain that this helper addresses the mixed-timezone issue seen in dashboard smoke tests.
    if not path.exists():
        # If there is no daily CSV yet, there is nothing to normalize.
        print(f"[prepare_local_data_cache] daily cache missing: {path.relative_to(BASE_DIR)}")
        # Tell the operator that the daily file was not present.
        return
        # Stop this helper early because no file can be processed.

    df = pd.read_csv(path)
    # Read the daily CSV into a table so the date column can be normalized safely.

    if "date" not in df.columns:
        # If the expected date column is absent, the file is malformed for this project.
        raise RuntimeError(f"daily CSV is missing required date column: {path}")
        # Stop with a clear error so a broken cache is not silently accepted.

    parsed_utc = pd.to_datetime(pd.Index(df["date"]), utc=True, errors="raise")
    # Parse every date label through UTC so mixed -05:00 and -04:00 offsets are accepted in one column.

    df["date"] = pd.DatetimeIndex(parsed_utc.date).strftime("%Y-%m-%d")
    # Store only the intended trading calendar date, which is stable across daylight-saving changes.

    df.to_csv(path, index=False)
    # Write the cleaned daily CSV back without pandas adding an extra row-number column.

    print(f"[prepare_local_data_cache] normalized daily dates in {path.relative_to(BASE_DIR)}")
    # Tell the operator that the daily cache is now safe for dashboard/export loading.


def _restore_events_from_public_json(path: Path) -> None:
    """Merge event rows embedded in public/data JSON back into the local ff_events CSV."""
    # Explain that this helper rebuilds local event history from the static frontend data when raw caches were deleted.
    public_data_dir = BASE_DIR / "public" / "data"
    # Build the folder path where Vercel/static dashboard JSON files are stored.

    rows = []
    # Start an empty list that will hold reconstructed event rows before they become a DataFrame.

    for json_path in sorted(public_data_dir.glob("*.json")):
        # Loop through each static JSON payload file in chronological filename order.
        if json_path.name == "dates.json":
            # Skip the date-list file because it does not contain per-day event rows.
            continue
            # Move on to the next JSON file.

        payload = json.loads(json_path.read_text())
        # Read and parse one static dashboard payload file.

        date_label = json_path.stem
        # Use the filename, such as 2026-05-08, as the trading date for all events inside that payload.

        for event in payload.get("ff_events", []):
            # Loop through the event rows embedded in this day's static dashboard payload.
            time_text = str(event.get("time", "00:00") or "00:00").strip()
            # Read the event time text, defaulting to midnight if the field is absent or blank.

            local_timestamp = pd.Timestamp(f"{date_label} {time_text}", tz="America/New_York")
            # Rebuild the event timestamp as an Eastern-time market-calendar timestamp.

            rows.append(
                # Add one reconstructed CSV-style event row to the in-memory list.
                {
                    # Start the dictionary that matches the columns expected by dashboard.py.
                    "DateTime": local_timestamp.strftime("%Y-%m-%dT%H:%M:%S%z"),
                    # Store the timestamp with an explicit offset so later UTC parsing is deterministic.
                    "Currency": "USD",
                    # Restore the currency as USD because this project filters and displays USD macro/news events.
                    "Impact": event.get("impact", ""),
                    # Copy the impact label shown in the static dashboard data.
                    "Event": event.get("event", ""),
                    # Copy the event title shown in the static dashboard data.
                    "Actual": event.get("actual", ""),
                    # Copy the actual value when the static data has one.
                    "Forecast": event.get("forecast", ""),
                    # Copy the forecast value when the static data has one.
                    "Previous": event.get("previous", ""),
                    # Copy the previous value when the static data has one.
                }
                # Finish the reconstructed event row dictionary.
            )
            # Finish appending this event row to the list.

    if not rows:
        # If no public JSON event rows were found, leave the existing CSV untouched.
        print("[prepare_local_data_cache] no public/data events found to restore")
        # Tell the operator that no static event history was available.
        return
        # Stop this helper early because there is nothing to merge.

    restored = pd.DataFrame(rows)
    # Convert the reconstructed event list into a table with the normal event CSV columns.

    frames = [restored]
    # Start the merge list with events recovered from public/data JSON files.

    if path.exists():
        # If a local event CSV already exists, merge it instead of replacing it.
        frames.append(pd.read_csv(path))
        # Add existing local event rows so current weekly refresh data is preserved.

    merged = pd.concat(frames, ignore_index=True)
    # Combine recovered static events and existing local events into one table.

    merged["DateTime"] = pd.to_datetime(merged["DateTime"], utc=True, errors="coerce")
    # Parse timestamps through UTC so rows with different offsets can be safely deduplicated and sorted.

    merged = merged.dropna(subset=["DateTime", "Event"])
    # Remove rows that do not have a usable timestamp or event title.

    merged = merged.drop_duplicates(subset=["DateTime", "Event"], keep="last")
    # Keep one copy of duplicate events, preferring the later row in the merged table.

    merged = merged.sort_values("DateTime").reset_index(drop=True)
    # Sort events chronologically and reset row numbers after sorting.

    merged["DateTime"] = merged["DateTime"].dt.strftime("%Y-%m-%d %H:%M:%S%z")
    # Store timestamps in one consistent offset-bearing string format for the CSV cache.

    merged.to_csv(path, index=False)
    # Write the merged event archive back to the canonical local event cache.

    print(f"[prepare_local_data_cache] restored {len(merged)} event rows into {path.relative_to(BASE_DIR)}")
    # Tell the operator how many total event rows are now available locally.


def main() -> int:
    """Prepare data/ cache files and return a shell-style exit code."""
    # Define the main workflow as a function so it can be imported or tested later if needed.
    DATA_DIR.mkdir(exist_ok=True)
    # Create the canonical data/ folder if it was deleted or has not been created yet.

    for legacy_name, canonical_path in LEGACY_FILES.items():
        # Loop through every known legacy cache file that may still exist at the repo root.
        legacy_path = BASE_DIR / legacy_name
        # Build the full path to the repo-root legacy source file.
        _copy_legacy_file_if_needed(legacy_path, canonical_path)
        # Copy this legacy file only if the canonical data/ version is missing.

    _normalize_daily_csv(DATA_DIR / "qqq_daily.csv")
    # Normalize the canonical daily cache so mixed timezone offsets cannot break pandas loading.

    _restore_events_from_public_json(DATA_DIR / "ff_events.csv")
    # Rebuild local event history from committed static JSON so deleted raw event caches can be recovered.

    return 0
    # Return success to the shell when all cache-preparation steps complete.


if __name__ == "__main__":
    # Only run the workflow automatically when the script is executed directly from the shell.
    raise SystemExit(main())
    # Convert the main function's return code into the process exit status.
