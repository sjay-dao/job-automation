from __future__ import annotations

import random
import time
import os
from pathlib import Path

from selenium import webdriver
from selenium.webdriver.chrome.options import Options

from config import BASE_DIR, load_settings
from csv_writer import build_job_uid, load_seen_jobs, persist_seen_jobs, read_existing_rows, upsert_rows
from job_sources import collect_jobs_for_source, enabled_sources
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
    browser_settings = settings.get("browser", {})
    user_data_dir = str(browser_settings.get("user_data_dir", "") or "").strip()
    profile_directory = str(browser_settings.get("profile_directory", "") or "").strip()
    if user_data_dir:
        user_data_path = Path(user_data_dir)
        if not user_data_path.is_absolute():
            user_data_path = (BASE_DIR / user_data_path).resolve()
        user_data_path.mkdir(parents=True, exist_ok=True)
        user_data_dir = str(user_data_path)
        options.add_argument(f"--user-data-dir={user_data_dir}")
    if profile_directory:
        options.add_argument(f"--profile-directory={profile_directory}")
    if browser_settings.get("headless"):
        options.add_argument("--headless=new")
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option("useAutomationExtension", False)
    driver = webdriver.Chrome(options=options)
    driver.set_page_load_timeout(45)
    driver.set_script_timeout(30)
    return driver


def process_keyword(
    driver,
    keyword: str,
    settings: dict,
    seen_job_uids: set[str],
    source_key: str,
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    jobs = collect_jobs_for_source(source_key, driver, keyword, settings, seen_job_uids)
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
    output_csv_path: Path = settings["output_csv_path"]
    persisted_seen_job_uids = load_seen_jobs(settings["jobs_seen_path"])
    for existing_row in read_existing_rows(output_csv_path):
        row_uid = build_job_uid(existing_row)
        if row_uid:
            persisted_seen_job_uids.add(row_uid)
    scraping = settings.get("scraping", {})
    between_keywords_min = float(scraping.get("between_keywords_min_seconds", 2.0))
    between_keywords_max = float(scraping.get("between_keywords_max_seconds", 4.0))
    source_keys = enabled_sources(settings)
    browser_settings = settings.get("browser", {})

    if "jobstreet" in source_keys and not str(browser_settings.get("user_data_dir", "") or "").strip():
        print(
            "[jobstreet] Tip: set browser.user_data_dir in config.json to reuse a logged-in Chrome profile. "
            "If JobStreet shows a Google sign-in wall, the scraper will pause for manual login.",
            flush=True,
        )

    driver = build_driver(settings)
    try:
        if "linkedin" in source_keys:
            linkedin_settings = settings.get("job_sources", {}).get("linkedin", {})
            login_to_linkedin(
                driver=driver,
                email=settings["linkedin_email"],
                password=settings["linkedin_password"],
                login_url=str(linkedin_settings.get("login_url", "https://www.linkedin.com/login")),
            )

        for source_key in source_keys:
            source_name = str(settings.get("job_sources", {}).get(source_key, {}).get("source_name", source_key.title()))
            print(f"[scrape] source: {source_name}", flush=True)
            for keyword in settings["job_titles"]:
                print(f"[scrape] keyword: {keyword}", flush=True)
                new_rows = process_keyword(driver, keyword, settings, persisted_seen_job_uids, source_key)
                print(f"[scrape] collected {len(new_rows)} rows for {source_name} / {keyword}", flush=True)
                for row in new_rows:
                    upsert_rows(output_csv_path, [row])
                    job_uid = str(row.get("job_uid") or "")
                    if job_uid:
                        persisted_seen_job_uids.add(job_uid)
                        persist_seen_jobs(settings["jobs_seen_path"], persisted_seen_job_uids)

                time.sleep(random.uniform(between_keywords_min, between_keywords_max))

        return output_csv_path
    finally:
        driver.quit()


if __name__ == "__main__":
    final_path = run()
    print(f"Saved results to: {final_path}")
