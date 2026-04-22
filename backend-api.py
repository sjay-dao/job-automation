from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from flask import Flask, jsonify, request, send_from_directory

from config import BASE_DIR, load_settings
from csv_writer import build_job_uid, read_existing_rows, update_row
from main import run
from parser import parse_job_posted_date


app = Flask(__name__, static_folder="static", static_url_path="/static")

DEFAULT_STATUS = "New"
DEFAULT_SOURCE = "LinkedIn"


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def get_output_csv_path() -> Path:
    settings = load_settings()
    return settings["output_csv_path"]


def normalize_job_row(row: dict[str, str]) -> dict[str, str]:
    normalized = dict(row)
    normalized["status"] = str(normalized.get("status") or DEFAULT_STATUS).strip() or DEFAULT_STATUS
    normalized["source"] = str(normalized.get("source") or DEFAULT_SOURCE).strip() or DEFAULT_SOURCE
    normalized["last_updated"] = str(normalized.get("last_updated") or "").strip()
    normalized["job_uid"] = str(normalized.get("job_uid") or build_job_uid(normalized)).strip()
    posted_date = str(normalized.get("posted_date") or "").strip()
    if not posted_date:
        posted_date = parse_job_posted_date(str(normalized.get("date_posted") or ""))
    normalized["posted_date"] = posted_date
    return normalized


@app.get("/")
def index():
    return send_from_directory(BASE_DIR / "static", "index.html")


@app.get("/api/jobs")
def get_jobs():
    csv_path = get_output_csv_path()
    jobs = [normalize_job_row(job) for job in read_existing_rows(csv_path)]
    return jsonify(
        {
            "count": len(jobs),
            "jobs": jobs,
            "csv_path": str(csv_path),
        }
    )


@app.post("/run")
def run_automation():
    output_path = run()
    return jsonify({"status": "done", "output_csv": str(output_path)}), 200


@app.post("/api/jobs/status")
def update_job_status():
    payload = request.get_json(force=True, silent=True) or {}
    job_key = str(payload.get("job_key", "")).strip()
    status = str(payload.get("status", "")).strip()

    if not job_key:
        return jsonify({"error": "job_key is required"}), 400
    if not status:
        return jsonify({"error": "status is required"}), 400

    csv_path = get_output_csv_path()
    updates = {
        "status": status,
        "last_updated": utc_now_iso(),
    }
    updated = update_row(
        csv_path,
        job_key,
        updates,
    )
    if not updated:
        return jsonify({"error": "job not found"}), 404

    return jsonify(
        {
            "status": "ok",
            "job_key": job_key,
            "job_status": status,
            "job_last_updated": updates["last_updated"],
        }
    ), 200


if __name__ == "__main__":
    app.run(port=5000, debug=True)
