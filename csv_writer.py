from __future__ import annotations

import csv
import json
from pathlib import Path

from parser import parse_job_posted_date


CSV_COLUMNS = [
    "job_uid",
    "job_id",
    "source",
    "search_keyword",
    "status",
    "last_updated",
    "match_score",
    "score",
    "title",
    "company",
    "location",
    "extracted_location",
    "date_posted",
    "posted_date",
    "applicant_count",
    "matched_categories",
    "matched_keywords",
    "score_breakdown",
    "job_link",
    "description",
]


def build_job_uid(row: dict[str, object]) -> str:
    source = str(row.get("source") or "LinkedIn").strip() or "LinkedIn"
    job_id = str(row.get("job_id") or "").strip()
    job_link = str(row.get("job_link") or "").strip()
    identifier = job_id or job_link
    if not identifier:
        title = str(row.get("title") or "").strip()
        company = str(row.get("company") or "").strip()
        location = str(row.get("location") or row.get("extracted_location") or "").strip()
        identifier = "|".join(part for part in [title, company, location] if part)
    return f"{source}:{identifier}" if identifier else ""


def get_row_key(row: dict[str, object]) -> str:
    return str(row.get("job_uid") or build_job_uid(row)).strip()


def normalize_row_dates(row: dict[str, object]) -> dict[str, object]:
    normalized = {**row}
    if not normalized.get("posted_date"):
        normalized["posted_date"] = parse_job_posted_date(str(normalized.get("date_posted", "")))
    return normalized


def load_seen_jobs(path: Path) -> set[str]:
    if not path.exists():
        return set()

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return set()

    if isinstance(data, list):
        seen: set[str] = set()
        for item in data:
            value = str(item).strip()
            if not value:
                continue
            seen.add(value)
            if value.isdigit():
                seen.add(f"LinkedIn:{value}")
        return seen
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
        row = normalize_row_dates(row)
        row_key = get_row_key(row)
        if row_key:
            keyed_rows[row_key] = row

    for row in new_rows:
        row = {**row}
        row = normalize_row_dates(row)
        row_key = get_row_key(row)
        if row_key:
            row["job_uid"] = row_key
            existing_row = keyed_rows.get(row_key, {})
            merged_row = {**existing_row, **row}
            if existing_row.get("status") and str(row.get("status", "")).strip().lower() in {"", "new"}:
                merged_row["status"] = existing_row.get("status")
            if existing_row.get("last_updated") and str(row.get("status", "")).strip().lower() in {"", "new"}:
                merged_row["last_updated"] = existing_row.get("last_updated")
            if not merged_row.get("source"):
                merged_row["source"] = existing_row.get("source") or "LinkedIn"
            keyed_rows[row_key] = merged_row

    sorted_rows = sorted(
        keyed_rows.values(),
        key=lambda row: int(str(row.get("match_score", row.get("score", "0"))) or 0),
        reverse=True,
    )

    with csv_path.open("w", newline="", encoding="utf-8") as file_obj:
        writer = csv.DictWriter(file_obj, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        for row in sorted_rows:
            row = {**row}
            if not row.get("job_uid"):
                row["job_uid"] = build_job_uid(row)
            if "match_score" not in row and "score" in row:
                row = {**row, "match_score": row.get("score", "")}
            if "score" not in row and "match_score" in row:
                row = {**row, "score": row.get("match_score", "")}
            if not row.get("status"):
                row = {**row, "status": "New"}
            if not row.get("source"):
                row = {**row, "source": "LinkedIn"}
            if not row.get("extracted_location"):
                row["extracted_location"] = row.get("location", "")
            writer.writerow({column: row.get(column, "") for column in CSV_COLUMNS})


def update_row(csv_path: Path, job_key: str, updates: dict[str, object]) -> bool:
    existing_rows = read_existing_rows(csv_path)
    updated = False

    for index, row in enumerate(existing_rows):
        row = normalize_row_dates(row)
        row_key = get_row_key(row)
        if row_key and row_key == str(job_key):
            row.update({key: value for key, value in updates.items() if value is not None})
            if not row.get("job_uid"):
                row["job_uid"] = row_key
            existing_rows[index] = row
            updated = True
            break

    if not updated:
        return False

    with csv_path.open("w", newline="", encoding="utf-8") as file_obj:
        writer = csv.DictWriter(file_obj, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        for row in existing_rows:
            row = {**row}
            if not row.get("job_uid"):
                row["job_uid"] = build_job_uid(row)
            if "match_score" not in row and "score" in row:
                row = {**row, "match_score": row.get("score", "")}
            if "score" not in row and "match_score" in row:
                row = {**row, "score": row.get("match_score", "")}
            if not row.get("status"):
                row = {**row, "status": "New"}
            if not row.get("source"):
                row = {**row, "source": "LinkedIn"}
            if not row.get("extracted_location"):
                row["extracted_location"] = row.get("location", "")
            writer.writerow({column: row.get(column, "") for column in CSV_COLUMNS})

    return True
