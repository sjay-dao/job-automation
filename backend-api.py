from __future__ import annotations

from pathlib import Path

from flask import Flask, jsonify, send_from_directory

from config import BASE_DIR, load_settings
from csv_writer import read_existing_rows
from main import run


app = Flask(__name__, static_folder="static", static_url_path="/static")


def get_output_csv_path() -> Path:
    settings = load_settings()
    return settings["output_csv_path"]


@app.get("/")
def index():
    return send_from_directory(BASE_DIR / "static", "index.html")


@app.get("/api/jobs")
def get_jobs():
    csv_path = get_output_csv_path()
    jobs = read_existing_rows(csv_path)
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


if __name__ == "__main__":
    app.run(port=5000, debug=True)
