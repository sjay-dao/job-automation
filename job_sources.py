from __future__ import annotations

import random
import re
import time
from datetime import datetime, timezone
from typing import Callable, Generator
from urllib.parse import parse_qs, quote_plus, urlparse, urlencode

from selenium.common.exceptions import StaleElementReferenceException, TimeoutException
from selenium.webdriver.common.by import By
from selenium.webdriver.remote.webdriver import WebDriver
from selenium.webdriver.remote.webelement import WebElement
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

from job_search import collect_jobs_for_keyword as collect_linkedin_jobs
from job_search import JOB_CARD_SELECTOR as LINKEDIN_CARD_SELECTOR
from job_search import build_jobs_url as build_linkedin_jobs_url
from parser import parse_job_age_days, parse_job_posted_date
from scroll_handler import find_scroll_container


SOURCE_ORDER = ["linkedin", "jobstreet", "indeed"]
CARD_SELECTOR = tuple[str, str]


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def compact_lines(text: str) -> list[str]:
    return [line.strip() for line in text.splitlines() if line.strip()]


def slugify_keyword(keyword: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", keyword.lower()).strip("-")
    return slug or "jobs"


def extract_href(card: WebElement, xpaths: list[str]) -> str:
    for xpath in xpaths:
        try:
            href = card.find_element(By.XPATH, xpath).get_attribute("href")
            if href:
                return href.split("#")[0]
        except Exception:
            continue
    return ""


def get_card_container(card: WebElement) -> WebElement:
    for xpath in [
        "./ancestor::article[1]",
        "./ancestor::li[1]",
        "./ancestor::div[1]",
    ]:
        try:
            return card.find_element(By.XPATH, xpath)
        except Exception:
            continue
    return card


def extract_jobstreet_job_id(job_link: str) -> str:
    match = re.search(r"/job/(\d+)", job_link)
    return match.group(1) if match else ""


def extract_indeed_job_id(job_link: str) -> str:
    query_params = parse_qs(urlparse(job_link).query)
    if query_params.get("jk"):
        return query_params["jk"][0]

    match = re.search(r"/viewjob/([^/?#]+)", job_link)
    if match:
        return match.group(1)

    return ""


def build_job_uid(source_name: str, job_id: str, job_link: str) -> str:
    identifier = job_id or job_link
    return f"{source_name}:{identifier}" if identifier else ""


def first_matching_line(lines: list[str], patterns: list[str]) -> str:
    for line in lines:
        for pattern in patterns:
            if re.search(pattern, line, flags=re.IGNORECASE):
                return line
    return ""


def last_non_empty_line(lines: list[str]) -> str:
    for line in reversed(lines):
        if line:
            return line
    return ""


def extract_body_text(driver: WebDriver, timeout: int = 12) -> str:
    wait = WebDriverWait(driver, timeout)
    try:
        wait.until(lambda drv: bool(drv.find_element(By.TAG_NAME, "body").text.strip()))
    except TimeoutException:
        pass

    try:
        return driver.find_element(By.TAG_NAME, "body").text.strip()
    except Exception:
        return ""


def extract_detail_date(text: str) -> str:
    lines = compact_lines(text)
    match = first_matching_line(
        lines,
        [
            r"(?i)\bposted\s+.+ago\b",
            r"(?i)\blisted\s+.+ago\b",
            r"(?i)\b\d+\s*(?:minute|minutes|min|mins|hour|hours|hr|hrs|day|days|week|weeks)\s+ago\b",
            r"(?i)\bjust posted\b",
            r"(?i)\bnew\b",
        ],
    )
    if not match:
        return ""

    normalized = match.lower()
    if "just posted" in normalized or normalized == "new":
        return "today"

    return match


def normalize_location_line(line: str) -> str:
    return line.strip().rstrip(",")


def parse_jobstreet_card(card: WebElement, source_name: str, keyword: str) -> dict[str, object]:
    container = get_card_container(card)
    lines = compact_lines(container.text)
    job_link = extract_href(
        card,
        [
            ".//a[contains(@href,'/job/') and contains(@href,'origin=cardTitle')]",
            ".//a[contains(@href,'/job/')]",
        ],
    )
    job_id = extract_jobstreet_job_id(job_link)
    title = lines[0] if lines else ""
    company = ""
    for line in lines[1:4]:
        if line.lower().startswith("at "):
            company = line[3:].strip()
            break

    if not company and len(lines) > 1:
        company = lines[1]

    location = first_matching_line(
        lines,
        [
            r"\bremote\b",
            r"\bhybrid\b",
            r"\bonsite\b",
            r"\bon-site\b",
            r"\bMetro Manila\b",
            r"\bPhilippines\b",
            r"\bCity\b",
        ],
    )
    date_posted = first_matching_line(
        lines,
        [
            r"(?i)\bposted\s+.+ago\b",
            r"(?i)\blisted\s+.+ago\b",
            r"(?i)\b\d+\s*(?:m|h|d|w)\s+ago\b",
            r"(?i)\b\d+\s*(?:minute|minutes|hour|hours|day|days|week|weeks)\s+ago\b",
        ],
    )

    return {
        "job_id": job_id,
        "job_uid": build_job_uid(source_name, job_id, job_link),
        "job_link": job_link,
        "title": title,
        "company": company,
        "location": normalize_location_line(location),
        "date_posted": date_posted,
        "source": source_name,
        "search_keyword": keyword,
    }


def parse_indeed_card(card: WebElement, source_name: str, keyword: str, location: str) -> dict[str, object]:
    container = get_card_container(card)
    lines = compact_lines(container.text)
    job_link = extract_href(
        card,
        [
            ".//a[contains(@href,'/viewjob?jk=')]",
            ".//a[contains(@href,'/rc/clk?jk=')]",
            ".//a[contains(@href,'jk=')]",
        ],
    )
    job_id = extract_indeed_job_id(job_link)

    title = lines[0] if lines else ""
    company = ""
    location_text = ""
    for line in lines[1:6]:
        lowered = line.lower()
        if not company and lowered not in {"new", "today"} and not re.search(r"\b\d+(\.\d+)?\s+out of\s+5\b", line.lower()):
            if not re.search(r"\b(remote|hybrid|city|county|state|province|philippines)\b", lowered):
                company = line
                continue
        if not location_text and re.search(r"\b(remote|hybrid|city|county|state|province|philippines|work in)\b", lowered):
            location_text = line

    if not location_text:
        location_text = location or ""

    date_posted = first_matching_line(
        lines,
        [
            r"(?i)\bnew\b",
            r"(?i)\bjust posted\b",
            r"(?i)\bposted\s+.+ago\b",
            r"(?i)\b\d+\s*(?:day|days|hour|hours|minute|minutes)\s+ago\b",
        ],
    )
    if not date_posted:
        date_posted = "today"

    return {
        "job_id": job_id,
        "job_uid": build_job_uid(source_name, job_id, job_link),
        "job_link": job_link,
        "title": title,
        "company": company,
        "location": normalize_location_line(location_text),
        "date_posted": date_posted,
        "source": source_name,
        "search_keyword": keyword,
    }


def collect_cards(
    driver: WebDriver,
    card_selector: CARD_SELECTOR,
    snapshot_builder: Callable[[WebElement], dict[str, object]],
    max_jobs: int,
    pause_seconds: float,
    step_px: int,
) -> Generator[dict[str, object], None, None]:
    container = find_scroll_container(driver)
    seen_keys: set[str] = set()
    stable_rounds = 0
    previous_count = -1
    previous_height = -1

    while stable_rounds < 3:
        cards = driver.find_elements(*card_selector)
        current_count = len(cards)

        for card in cards:
            try:
                snapshot = snapshot_builder(card)
            except StaleElementReferenceException:
                continue

            key = str(snapshot.get("job_uid") or snapshot.get("job_link") or snapshot.get("job_id") or "").strip()
            if not key or key in seen_keys:
                continue

            seen_keys.add(key)
            yield snapshot
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


def collect_detail_page_data(driver: WebDriver, source_name: str, snapshot: dict[str, object], keyword: str) -> dict[str, object]:
    detail_text = extract_body_text(driver)
    detail_date = extract_detail_date(detail_text)
    if detail_date:
        snapshot["date_posted"] = detail_date

    snapshot["posted_date"] = parse_job_posted_date(str(snapshot.get("date_posted", "")))
    snapshot["description"] = detail_text
    snapshot["source"] = source_name
    snapshot["search_keyword"] = keyword
    snapshot["last_updated"] = utc_now_iso()
    return snapshot


def collect_jobstreet_jobs(
    driver: WebDriver,
    keyword: str,
    settings: dict,
    seen_job_uids: set[str],
) -> list[dict[str, object]]:
    source_settings = settings.get("job_sources", {}).get("jobstreet", {})
    source_name = str(source_settings.get("source_name", "JobStreet") or "JobStreet")
    jobs_url_base = str(source_settings.get("jobs_url_base", "https://ph.jobstreet.com") or "https://ph.jobstreet.com")
    max_jobs = int(settings.get("max_jobs_per_keyword", 250))
    scraping = settings.get("scraping", {})
    scroll_pause_seconds = float(scraping.get("scroll_pause_seconds", 1.1))
    scroll_step_px = int(scraping.get("scroll_step_px", 640))
    between_cards_min = float(scraping.get("between_cards_min_seconds", 0.8))
    between_cards_max = float(scraping.get("between_cards_max_seconds", 1.6))
    max_job_age_days = settings.get("max_job_age_days")
    max_job_age_days = int(max_job_age_days) if isinstance(max_job_age_days, int) else None

    search_url = f"{jobs_url_base}/{slugify_keyword(keyword)}-jobs"
    driver.get(search_url)
    WebDriverWait(driver, 20).until(EC.presence_of_all_elements_located((By.XPATH, "//a[contains(@href,'/job/') and contains(@href,'origin=cardTitle')]")))

    snapshots: list[dict[str, object]] = []
    for snapshot in collect_cards(
        driver,
        (By.XPATH, "//a[contains(@href,'/job/') and contains(@href,'origin=cardTitle')]"),
        lambda card: parse_jobstreet_card(card, source_name, keyword),
        max_jobs=max_jobs,
        pause_seconds=scroll_pause_seconds,
        step_px=scroll_step_px,
    ):
        try:
            job_uid = str(snapshot.get("job_uid") or "").strip()
            if not job_uid or job_uid in seen_job_uids:
                continue

            if isinstance(max_job_age_days, int):
                age_days = parse_job_age_days(str(snapshot.get("date_posted", "")))
                if age_days is not None and age_days > max_job_age_days:
                    continue

            job_link = str(snapshot.get("job_link") or "").strip()
            if not job_link:
                continue

            driver.get(job_link)
            snapshot = collect_detail_page_data(driver, source_name, snapshot, keyword)

            if not snapshot.get("title"):
                snapshot["title"] = driver.title.split(" - Jobstreet")[0].strip() or str(snapshot.get("title") or "")
            if not snapshot.get("title"):
                continue

            seen_job_uids.add(job_uid)
            snapshots.append(snapshot)
        except StaleElementReferenceException:
            continue
        finally:
            time.sleep(random.uniform(between_cards_min, between_cards_max))

    return snapshots


def collect_indeed_jobs(
    driver: WebDriver,
    keyword: str,
    settings: dict,
    seen_job_uids: set[str],
) -> list[dict[str, object]]:
    source_settings = settings.get("job_sources", {}).get("indeed", {})
    source_name = str(source_settings.get("source_name", "Indeed") or "Indeed")
    jobs_url_base = str(source_settings.get("jobs_url_base", "https://www.indeed.com/jobs") or "https://www.indeed.com/jobs")
    max_jobs = int(settings.get("max_jobs_per_keyword", 250))
    scraping = settings.get("scraping", {})
    scroll_pause_seconds = float(scraping.get("scroll_pause_seconds", 1.1))
    scroll_step_px = int(scraping.get("scroll_step_px", 640))
    between_cards_min = float(scraping.get("between_cards_min_seconds", 0.8))
    between_cards_max = float(scraping.get("between_cards_max_seconds", 1.6))
    max_job_age_days = settings.get("max_job_age_days")
    max_job_age_days = int(max_job_age_days) if isinstance(max_job_age_days, int) else None
    fromage = max(1, int(max_job_age_days or 1))

    query = urlencode(
        {
            "q": keyword,
            "l": settings.get("location", ""),
            "fromage": fromage,
            "sort": "date",
        },
    )
    search_url = f"{jobs_url_base}?{query}"
    driver.get(search_url)
    WebDriverWait(driver, 20).until(
        EC.presence_of_all_elements_located(
            (
                By.XPATH,
                "//a[contains(@href,'/viewjob?jk=') or contains(@href,'/rc/clk?jk=') or contains(@href,'jk=')]",
            ),
        ),
    )

    snapshots: list[dict[str, object]] = []
    for snapshot in collect_cards(
        driver,
        (By.XPATH, "//a[contains(@href,'/viewjob?jk=') or contains(@href,'/rc/clk?jk=') or contains(@href,'jk=')]"),
        lambda card: parse_indeed_card(card, source_name, keyword, str(settings.get("location", ""))),
        max_jobs=max_jobs,
        pause_seconds=scroll_pause_seconds,
        step_px=scroll_step_px,
    ):
        try:
            job_uid = str(snapshot.get("job_uid") or "").strip()
            if not job_uid or job_uid in seen_job_uids:
                continue

            if isinstance(max_job_age_days, int):
                age_days = parse_job_age_days(str(snapshot.get("date_posted", "")))
                if age_days is not None and age_days > max_job_age_days:
                    continue

            job_link = str(snapshot.get("job_link") or "").strip()
            if not job_link:
                continue

            driver.get(job_link)
            snapshot = collect_detail_page_data(driver, source_name, snapshot, keyword)

            if not snapshot.get("title"):
                snapshot["title"] = driver.title.split(" - Indeed")[0].strip() or str(snapshot.get("title") or "")
            if not snapshot.get("title"):
                continue

            seen_job_uids.add(job_uid)
            snapshots.append(snapshot)
        except StaleElementReferenceException:
            continue
        finally:
            time.sleep(random.uniform(between_cards_min, between_cards_max))

    return snapshots


def collect_jobs_for_source(
    source_key: str,
    driver: WebDriver,
    keyword: str,
    settings: dict,
    seen_job_uids: set[str],
) -> list[dict[str, object]]:
    if source_key == "linkedin":
        source_settings = settings.get("job_sources", {}).get("linkedin", {})
        source_name = str(source_settings.get("source_name", "LinkedIn") or "LinkedIn")
        jobs = collect_linkedin_jobs(driver, keyword, settings, seen_job_uids)
        for job in jobs:
            job["source"] = source_name
            job["job_uid"] = build_job_uid(source_name, str(job.get("job_id") or ""), str(job.get("job_link") or ""))
            if not job.get("posted_date"):
                job["posted_date"] = parse_job_posted_date(str(job.get("date_posted", "")))
            job["last_updated"] = job.get("last_updated") or utc_now_iso()
        return jobs

    if source_key == "jobstreet":
        return collect_jobstreet_jobs(driver, keyword, settings, seen_job_uids)

    if source_key == "indeed":
        return collect_indeed_jobs(driver, keyword, settings, seen_job_uids)

    return []


def enabled_sources(settings: dict) -> list[str]:
    job_sources = settings.get("job_sources", {})
    selected: list[str] = []
    for key in SOURCE_ORDER:
        source_settings = job_sources.get(key, {})
        if source_settings.get("enabled", True):
            selected.append(key)
    return selected
