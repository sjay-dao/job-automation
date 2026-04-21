from __future__ import annotations

import random
import time
import os
from pathlib import Path

from selenium import webdriver
from selenium.webdriver.chrome.options import Options

from config import BASE_DIR, load_settings
from csv_writer import load_seen_jobs, persist_seen_jobs, upsert_rows
from job_search import collect_jobs_for_keyword
from login import login_to_linkedin
from scorer import score_job


def prepare_runtime_environment() -> None:
    cache_dir = BASE_DIR / ".selenium"
    cache_dir.mkdir(exist_ok=True)
    os.environ["SE_CACHE_PATH"] = str(cache_dir)

    for key in [
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "ALL_PROXY",
        "http_proxy",
        "https_proxy",
        "all_proxy",
    ]:
        os.environ.pop(key, None)


def build_driver(settings: dict) -> webdriver.Chrome:
    prepare_runtime_environment()
    options = Options()
    options.add_argument("--start-maximized")
    options.add_argument("--disable-notifications")
    options.add_argument("--disable-popup-blocking")
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_argument("--window-size=1440,1200")
    if settings.get("browser", {}).get("headless"):
        options.add_argument("--headless=new")
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option("useAutomationExtension", False)
    return webdriver.Chrome(options=options)


def process_keyword(driver, keyword: str, settings: dict, seen_job_ids: set[str]) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    jobs = collect_jobs_for_keyword(driver, keyword, settings, seen_job_ids)
    for job in jobs:
        score_result = score_job(
            description=str(job.get("description", "")),
            title=str(job.get("title", "")),
            scoring_rules=settings["scoring"],
            resume_profile=settings.get("resume_profile"),
        )
        job["match_score"] = score_result["match_score"]
        job["score"] = score_result["match_score"]
        job["matched_categories"] = score_result["matched_categories"]
        job["matched_keywords"] = score_result["matched_keywords"]
        job["score_breakdown"] = score_result["score_breakdown"]
        rows.append(job)
    return rows


def run() -> Path:
    settings = load_settings()
    persisted_seen_job_ids = load_seen_jobs(settings["jobs_seen_path"])
    output_csv_path: Path = settings["output_csv_path"]
    scraping = settings.get("scraping", {})
    between_keywords_min = float(scraping.get("between_keywords_min_seconds", 2.0))
    between_keywords_max = float(scraping.get("between_keywords_max_seconds", 4.0))

    driver = build_driver(settings)
    try:
        login_to_linkedin(
            driver=driver,
            email=settings["linkedin_email"],
            password=settings["linkedin_password"],
            login_url=settings["linkedin"]["login_url"],
        )

        for keyword in settings["job_titles"]:
            print(f"[scrape] keyword: {keyword}", flush=True)
            new_rows = process_keyword(driver, keyword, settings, set())
            print(f"[scrape] collected {len(new_rows)} rows for {keyword}", flush=True)
            for row in new_rows:
                upsert_rows(output_csv_path, [row])
                job_id = str(row.get("job_id") or row.get("job_link") or "")
                if job_id:
                    persisted_seen_job_ids.add(job_id)
                    persist_seen_jobs(settings["jobs_seen_path"], persisted_seen_job_ids)

            time.sleep(random.uniform(between_keywords_min, between_keywords_max))

        return output_csv_path
    finally:
        driver.quit()


if __name__ == "__main__":
    final_path = run()
    print(f"Saved results to: {final_path}")
