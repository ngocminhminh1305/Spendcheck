"""Small CSV and JSON helpers shared by command-line scripts."""

import csv
import json
from pathlib import Path


def read_csv(path: Path) -> list[dict]:
    """Read UTF-8 CSV data, including files saved with an Excel BOM."""
    with path.open(newline="", encoding="utf-8-sig") as stream:
        return list(csv.DictReader(stream))


def write_csv(path: Path, rows: list[dict], fields: list[str]) -> None:
    """Write explicit columns so empty datasets still have a usable header."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def write_json(path: Path, value: dict) -> None:
    """Write a readable JSON report with strict finite-number handling."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n")
