from __future__ import annotations

from datetime import datetime, timezone
import random
import time
from typing import Generator
from urllib.parse import urlencode

from selenium.common.exceptions import StaleElementReferenceException, TimeoutException
from selenium.webdriver.common.by import By
from selenium.webdriver.remote.webdriver import WebDriver
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

from csv_writer import build_job_uid
from parser import (
    extract_card_snapshot,
    extract_description_panel,
    get_job_link,
    is_promoted,
    parse_job_age_days,
    parse_job_posted_date,
)
from scroll_handler import find_scroll_container


JOB_CARD_SELECTOR = (
    By.XPATH,
    "//li[contains(@class,'jobs-search-results__list-item') or @data-occludable-job-id]"
    " | //div[@role='listitem' and .//a[contains(@href,'/jobs/view/')]]",
)


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def build_jobs_url(
    base_url: str,
    keyword: str,
    location: str,
    date_posted: str,
    max_job_age_days: int | None = None,
) -> str:
    posted_map = {
        "today": "r86400",
        "past_24_hours": "r86400",
        "past_week": "r604800",
        "past_month": "r2592000",
    }
    query = {
        "keywords": keyword,
        "location": location,
        "f_TPR": posted_map.get(date_posted, posted_map["past_24_hours"]),
    }
    return f"{base_url}?{urlencode(query)}"


def open_search_results(
    driver: WebDriver,
    jobs_url: str,
    keyword: str,
    location: str,
    date_posted: str,
    max_job_age_days: int | None = None,
    timeout: int = 20,
) -> None:
    wait = WebDriverWait(driver, timeout)
    driver.get(build_jobs_url(jobs_url, keyword, location, date_posted, max_job_age_days))
    wait.until(EC.presence_of_all_elements_located(JOB_CARD_SELECTOR))


def iter_job_cards(
    driver: WebDriver,
    max_jobs: int,
    pause_seconds: float = 1.1,
    step_px: int = 640,
) -> Generator:
    container = find_scroll_container(driver)
    seen_keys: set[str] = set()
    stable_rounds = 0
    previous_count = -1
    previous_height = -1

    while stable_rounds < 3:
        cards = driver.find_elements(*JOB_CARD_SELECTOR)
        current_count = len(cards)

        for card in cards:
            key = (
                card.get_attribute("data-occludable-job-id")
                or card.get_attribute("data-job-id")
                or card.get_attribute("id")
                or get_job_link(card)
                or card.text[:200]
            )
            if not key or key in seen_keys:
                continue

            seen_keys.add(key)
            yield card
            if len(seen_keys) >= max_jobs:
                return

        if container is not None:
            current_height = driver.execute_script("return arguments[0].scrollHeight;", container)
            current_top = driver.execute_script("return arguments[0].scrollTop;", container)
            next_top = min(current_top + step_px, current_height)
            driver.execute_script("arguments[0].scrollTop = arguments[1];", container, next_top)
        else:
            current_height = driver.execute_script("return document.body.scrollHeight;")
            current_top = driver.execute_script("return window.scrollY;")
            next_top = min(current_top + step_px, current_height)
            driver.execute_script("window.scrollTo(0, arguments[0]);", next_top)

        time.sleep(pause_seconds + random.uniform(0.1, 0.6))

        if current_count == previous_count and current_height == previous_height:
            stable_rounds += 1
        else:
            stable_rounds = 0

        previous_count = current_count
        previous_height = current_height


def load_job_details(driver: WebDriver, job_card, timeout: int = 8) -> dict[str, str | int | None]:
    driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", job_card)
    time.sleep(0.6 + random.uniform(0.2, 0.8))
    driver.execute_script("arguments[0].click();", job_card)

    wait = WebDriverWait(driver, timeout)
    try:
        wait.until(lambda drv: bool(extract_description_panel(drv).get("description")))
    except TimeoutException:
        pass

    time.sleep(0.4)
    return extract_description_panel(driver)


def collect_jobs_for_keyword(
    driver: WebDriver,
    keyword: str,
    settings: dict,
    seen_job_uids: set[str],
) -> list[dict[str, object]]:
    max_job_age_days = settings.get("max_job_age_days")
    max_job_age_days = int(max_job_age_days) if isinstance(max_job_age_days, int) else None
    linkedin_settings = settings.get("job_sources", {}).get("linkedin", {})
    source_name = str(linkedin_settings.get("source_name", settings.get("source_name", "LinkedIn")) or "LinkedIn")
    open_search_results(
        driver,
        settings["linkedin"]["jobs_url"],
        keyword,
        settings["location"],
        settings["date_posted"],
        max_job_age_days=max_job_age_days,
    )

    collected_jobs: list[dict[str, object]] = []
    local_seen_ids: set[str] = set()
    max_applicants = settings.get("max_applicants")
    max_jobs = int(settings.get("max_jobs_per_keyword", 250))
    scraping = settings.get("scraping", {})
    scroll_pause_seconds = float(scraping.get("scroll_pause_seconds", 1.1))
    scroll_step_px = int(scraping.get("scroll_step_px", 640))
    between_cards_min = float(scraping.get("between_cards_min_seconds", 0.8))
    between_cards_max = float(scraping.get("between_cards_max_seconds", 1.6))

    for index, card in enumerate(iter_job_cards(
        driver,
        max_jobs=max_jobs,
        pause_seconds=scroll_pause_seconds,
        step_px=scroll_step_px,
    ), start=1):
        try:
            if is_promoted(card):
                continue

            snapshot = extract_card_snapshot(card)
            job_id = snapshot.get("job_id") or snapshot.get("job_link")
            job_uid = build_job_uid({
                "source": source_name,
                "job_id": job_id or "",
                "job_link": snapshot.get("job_link") or "",
            })
            if (
                not job_id
                or str(job_uid) in seen_job_uids
                or str(job_id) in local_seen_ids
            ):
                continue

            if isinstance(max_job_age_days, int):
                age_days = parse_job_age_days(str(snapshot.get("date_posted", "")))
                if age_days is not None and age_days > max_job_age_days:
                    continue

            snapshot["posted_date"] = parse_job_posted_date(str(snapshot.get("date_posted", "")))
            snapshot["status"] = "New"
            snapshot["source"] = str(settings.get("source_name", "LinkedIn") or "LinkedIn")
            snapshot["last_updated"] = utc_now_iso()

            details = load_job_details(driver, card)
            applicant_count = details.get("applicant_count")
            if (
                isinstance(applicant_count, int)
                and isinstance(max_applicants, int)
                and applicant_count > max_applicants
            ):
                continue

            snapshot.update(details)
            if not snapshot.get("title"):
                snapshot["title"] = details.get("derived_title", "")
            if not snapshot.get("company"):
                snapshot["company"] = details.get("derived_company", "")
            if not snapshot.get("location"):
                snapshot["location"] = details.get("derived_location", "")
            if not snapshot.get("title"):
                continue
            snapshot["job_uid"] = job_uid
            snapshot["source"] = source_name
            snapshot["search_keyword"] = keyword
            collected_jobs.append(snapshot)
            local_seen_ids.add(str(job_id))
            if index >= max_jobs:
                break
        except StaleElementReferenceException:
            continue
        finally:
            time.sleep(random.uniform(between_cards_min, between_cards_max))

    return collected_jobs
