from __future__ import annotations

import csv
import json
from pathlib import Path


CSV_COLUMNS = [
    "job_id",
    "search_keyword",
    "match_score",
    "score",
    "title",
    "company",
    "location",
    "date_posted",
    "applicant_count",
    "matched_categories",
    "matched_keywords",
    "score_breakdown",
    "job_link",
    "description",
]


def load_seen_jobs(path: Path) -> set[str]:
    if not path.exists():
        return set()

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return set()

    if isinstance(data, list):
        return {str(item) for item in data if item}
    return set()


def persist_seen_jobs(path: Path, seen_job_ids: set[str]) -> None:
    ordered = sorted(seen_job_ids)
    path.write_text(json.dumps(ordered, indent=2), encoding="utf-8")


def read_existing_rows(csv_path: Path) -> list[dict[str, str]]:
    if not csv_path.exists():
        return []
    with csv_path.open("r", newline="", encoding="utf-8") as file_obj:
        reader = csv.DictReader(file_obj)
        return list(reader)


def upsert_rows(csv_path: Path, new_rows: list[dict[str, object]]) -> None:
    existing_rows = read_existing_rows(csv_path)
    keyed_rows: dict[str, dict[str, object]] = {}

    for row in existing_rows:
        job_id = row.get("job_id") or row.get("job_link")
        if job_id:
            keyed_rows[str(job_id)] = row

    for row in new_rows:
        job_id = str(row.get("job_id") or row.get("job_link") or "")
        if job_id:
            keyed_rows[job_id] = row

    sorted_rows = sorted(
        keyed_rows.values(),
        key=lambda row: int(str(row.get("match_score", row.get("score", "0"))) or 0),
        reverse=True,
    )

    with csv_path.open("w", newline="", encoding="utf-8") as file_obj:
        writer = csv.DictWriter(file_obj, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        for row in sorted_rows:
            if "match_score" not in row and "score" in row:
                row = {**row, "match_score": row.get("score", "")}
            if "score" not in row and "match_score" in row:
                row = {**row, "score": row.get("match_score", "")}
            writer.writerow({column: row.get(column, "") for column in CSV_COLUMNS})
