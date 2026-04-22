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
    if not text:
        return []
    return [line.strip() for line in text.splitlines() if line.strip()]


def slugify_keyword(keyword: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", keyword.lower()).strip("-")
    return slug or "jobs"


def extract_href(card: WebElement, xpaths: list[str]) -> str:
    try:
        href = card.get_attribute("href")
        if href:
            return href.split("#")[0]
    except Exception:
        pass

    for xpath in xpaths:
        try:
            href = card.find_element(By.XPATH, xpath).get_attribute("href")
            if href:
                return href.split("#")[0]
        except Exception:
            continue
    return ""


def extract_text(card: WebElement, xpaths: list[str]) -> str:
    for xpath in xpaths:
        try:
            text = card.find_element(By.XPATH, xpath).text
            if text and str(text).strip():
                return str(text).strip()
        except Exception:
            continue
    return ""


def get_card_container(card: WebElement) -> WebElement:
    fallback = card
    for xpath in [
        "./ancestor::article[1]",
        "./ancestor::li[1]",
        "./ancestor::div[1]",
    ]:
        try:
            candidate = card.find_element(By.XPATH, xpath)
            if str(candidate.text or "").strip():
                return candidate
            fallback = candidate
        except Exception:
            continue
    return fallback


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


def is_jobstreet_age_line(line: str) -> bool:
    lowered = line.lower()
    return bool(
        re.search(r"(?i)\b(?:posted|listed)\s+.+ago\b", line)
        or re.search(r"(?i)\b\d+\s*(?:m|h|d|w)\s+ago\b", line)
        or re.search(r"(?i)\b\d+\s*(?:minute|minutes|hour|hours|day|days|week|weeks)\s+ago\b", line)
        or "just posted" in lowered
        or lowered == "new"
    )


def last_non_empty_line(lines: list[str]) -> str:
    for line in reversed(lines):
        if line:
            return line
    return ""


def extract_body_text(driver: WebDriver, timeout: int = 12) -> str:
    try:
        body = driver.find_element(By.TAG_NAME, "body")
        text = getattr(body, "text", "")
        return str(text or "").strip()
    except Exception:
        return ""


def looks_like_cloudflare_interstitial(page_text: str, page_title: str) -> bool:
    combined = f"{page_title}\n{page_text}".lower()
    if "just a moment" in combined:
        return True
    if "cloudflare" in combined and ("verification" in combined or "attention required" in combined):
        return True
    if "security service" in combined and "cloudflare" in combined:
        return True
    return False


def extract_source_detail_text(driver: WebDriver, source_name: str) -> str:
    source_key = source_name.strip().lower()
    selectors = []
    if source_key == "jobstreet":
        selectors = [
            "//*[@data-automation='jobDetailsPage']",
            "//*[@data-automation='job-detail-location']/ancestor::*[1]",
        ]
    elif source_key == "indeed":
        selectors = [
            "//*[@id='jobDescriptionText']",
            "//*[@data-testid='jobDescriptionText']",
        ]

    for selector in selectors:
        try:
            WebDriverWait(driver, 10).until(lambda drv: len(drv.find_elements(By.XPATH, selector)) > 0)
            element = driver.find_element(By.XPATH, selector)
            text = getattr(element, "text", "")
            if text and str(text).strip():
                return str(text).strip()
        except Exception:
            continue

    return extract_body_text(driver)


def find_next_page_url(driver: WebDriver, xpaths: list[str]) -> str:
    for xpath in xpaths:
        try:
            for element in driver.find_elements(By.XPATH, xpath):
                href = str(element.get_attribute("href") or "").strip()
                if href:
                    return href
        except Exception:
            continue
    return ""


def safe_get(driver: WebDriver, url: str) -> None:
    try:
        driver.get(url)
    except TimeoutException:
        pass


def looks_like_jobstreet_login_wall(driver: WebDriver) -> bool:
    try:
        page_text = extract_body_text(driver, timeout=4).lower()
    except Exception:
        page_text = ""

    try:
        page_title = (driver.title or "").lower()
    except Exception:
        page_title = ""

    try:
        current_url = (driver.current_url or "").lower()
    except Exception:
        current_url = ""

    if looks_like_cloudflare_interstitial(page_text, page_title):
        return True
    if "continue with google" in page_text or "continue with google" in page_title:
        return True
    if "sign in with google" in page_text or "sign in with google" in page_title:
        return True
    if "accounts.google.com" in current_url:
        return True
    if "google" in page_title and ("sign in" in page_title or "account" in page_title):
        return True
    return False


def wait_for_jobstreet_login(driver: WebDriver, timeout_seconds: int = 240) -> None:
    if not looks_like_jobstreet_login_wall(driver):
        return

    print(
        "[jobstreet] JobStreet is asking for Google sign-in. "
        "Complete the login in the opened browser window; scraping will resume automatically.",
        flush=True,
    )
    deadline = time.time() + timeout_seconds
    while time.time() < deadline and looks_like_jobstreet_login_wall(driver):
        time.sleep(2.0)

    if looks_like_jobstreet_login_wall(driver):
        raise RuntimeError(
            "JobStreet still appears to be signed out. "
            "Use a Chrome profile that is already logged into Google/JobStreet, "
            "or log in in the opened browser window and rerun the scraper."
        )

    print("[jobstreet] JobStreet login detected; continuing scraping.", flush=True)


def looks_like_indeed_verification_wall(driver: WebDriver) -> bool:
    try:
        page_text = extract_body_text(driver, timeout=4).lower()
    except Exception:
        page_text = ""

    try:
        page_title = (driver.title or "").lower()
    except Exception:
        page_title = ""

    if looks_like_cloudflare_interstitial(page_text, page_title):
        return True
    if "additional verification required" in page_text:
        return True
    if "cloudflare" in page_text and "verification" in page_text:
        return True
    if "additional verification required" in page_title:
        return True
    return False


def wait_for_indeed_verification(driver: WebDriver, timeout_seconds: int = 240) -> None:
    if not looks_like_indeed_verification_wall(driver):
        return

    print(
        "[indeed] Indeed is showing Cloudflare verification. "
        "Complete the verification in the browser window; scraping will resume automatically.",
        flush=True,
    )
    deadline = time.time() + timeout_seconds
    while time.time() < deadline and looks_like_indeed_verification_wall(driver):
        time.sleep(2.0)

    if looks_like_indeed_verification_wall(driver):
        raise RuntimeError(
            "Indeed is still showing Cloudflare verification. "
            "Open the browser window, complete the challenge, or try again later."
        )

    print("[indeed] Verification cleared; continuing scraping.", flush=True)


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
            ".//a[@data-automation='job-list-item-link-overlay']",
            ".//a[@data-automation='job-card-title']",
            ".//a[contains(@href,'/job/')]",
        ],
    )
    job_id = extract_jobstreet_job_id(job_link)
    title = extract_text(card, [".//*[@data-automation='job-card-title']"])
    if not title and lines:
        title = next((line for line in lines if not is_jobstreet_age_line(line) and line.lower() != "at"), "")

    company = extract_text(card, [".//*[@data-automation='jobCompany']"])
    if not company:
        company = extract_text(card, [".//a[@data-automation='jobCompany']"])
    if not company and lines:
        for idx, line in enumerate(lines):
            if is_jobstreet_age_line(line) or line.lower() == "at":
                continue
            if title and line == title:
                continue
            if re.search(r"\b(remote|hybrid|onsite|on-site|metro manila|philippines|city)\b", line, flags=re.IGNORECASE):
                continue
            if idx + 1 < len(lines) and lines[idx].lower() == "at":
                company = lines[idx + 1]
                break
            if company:
                break
            company = line

    location = extract_text(card, [".//*[@data-automation='jobCardLocation']"])
    if not location:
        location = extract_text(card, [".//*[@data-automation='jobLocation']"])
    if not location and lines:
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

    date_posted = extract_text(card, [".//*[@data-automation='jobListingDate']"])
    if not date_posted:
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
        "extracted_location": normalize_location_line(location),
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
            ".//a[@data-automation='jobTitle']",
            ".//a[@data-testid='job-card-title']",
            ".//a[contains(@class,'jcs-JobTitle')]",
            ".//a[contains(@href,'/viewjob?jk=')]",
            ".//a[contains(@href,'/rc/clk?jk=')]",
            ".//a[contains(@href,'jk=')]",
        ],
    )
    job_id = extract_indeed_job_id(job_link)

    title = extract_text(
        card,
        [
            ".//a[@data-automation='jobTitle']//span",
            ".//a[@data-testid='job-card-title']//span",
            ".//a[contains(@class,'jcs-JobTitle')]//span",
            ".//a[@data-automation='jobTitle']",
            ".//a[@data-testid='job-card-title']",
            ".//a[contains(@class,'jcs-JobTitle')]",
            ".//span[@id and starts-with(@id, 'jobTitle-')]",
        ],
    )
    if not title and lines:
        title = lines[0]

    company = extract_text(card, [".//*[@data-testid='company-name']"])
    location_text = extract_text(card, [".//*[@data-testid='text-location']"])

    for line in lines[1:6]:
        lowered = line.lower()
        if not company and lowered not in {"new", "today"} and not re.search(r"\b\d+(\.\d+)?\s+out of\s+5\b", line.lower()):
            if not re.search(r"\b(remote|hybrid|city|county|state|province|philippines)\b", lowered):
                company = line
                continue
        if not location_text and re.search(r"\b(remote|hybrid|city|county|state|province|philippines|work from home|work at home|ca\b|tx\b|ny\b|wa\b)\b", lowered):
            location_text = line

    if not location_text:
        location_text = location or ""

    date_posted = ""
    for line in lines:
        lowered = line.lower().strip()
        if lowered == "new" or "just posted" in lowered:
            date_posted = "today"
            break
        if re.search(r"(?i)\bposted\s+.+ago\b", line):
            date_posted = line
            break
        if re.search(r"(?i)\b\d+\s*(?:d|day|days|h|hr|hrs|hour|hours|m|min|mins|minute|minutes|w|week|weeks)\s+ago\b", line):
            date_posted = line
            break
    if not date_posted:
        date_posted = "today"

    return {
        "job_id": job_id,
        "job_uid": build_job_uid(source_name, job_id, job_link),
        "job_link": job_link,
        "title": title,
        "company": company,
        "location": normalize_location_line(location_text),
        "extracted_location": normalize_location_line(location_text),
        "date_posted": date_posted,
        "description": container.text.strip(),
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
    detail_text = extract_source_detail_text(driver, source_name)
    detail_date = extract_detail_date(detail_text)
    if detail_date:
        snapshot["date_posted"] = detail_date

    snapshot["posted_date"] = parse_job_posted_date(str(snapshot.get("date_posted", "")))
    snapshot["description"] = detail_text
    snapshot["source"] = source_name
    snapshot["extracted_location"] = snapshot.get("extracted_location") or snapshot.get("location") or ""
    snapshot["search_keyword"] = keyword
    snapshot["last_updated"] = utc_now_iso()
    return snapshot


def select_jobstreet_detail_panel(card: WebElement) -> None:
    try:
        overlay = card.find_element(By.XPATH, ".//a[@data-automation='job-list-item-link-overlay']")
        overlay.click()
        return
    except Exception:
        pass

    try:
        title_link = card.find_element(By.XPATH, ".//a[@data-automation='job-card-title']")
        title_link.click()
        return
    except Exception:
        pass

    try:
        card.click()
    except Exception:
        pass


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
    login_timeout_seconds = settings.get("jobstreet_login_timeout_seconds", 240)
    login_timeout_seconds = int(login_timeout_seconds) if isinstance(login_timeout_seconds, int) else 240

    search_url = f"{jobs_url_base}/{slugify_keyword(keyword)}-jobs"
    safe_get(driver, search_url)
    wait_for_jobstreet_login(driver, timeout_seconds=login_timeout_seconds)

    snapshots: list[dict[str, object]] = []
    page_turns = 0
    while len(snapshots) < max_jobs and page_turns < 20:
        WebDriverWait(driver, 20).until(EC.presence_of_all_elements_located((By.XPATH, "//article[@data-testid='job-card']")))
        page_snapshots = list(
            collect_cards(
                driver,
                (By.XPATH, "//article[@data-testid='job-card']"),
                lambda card: parse_jobstreet_card(card, source_name, keyword),
                max_jobs=max_jobs - len(snapshots),
                pause_seconds=scroll_pause_seconds,
                step_px=scroll_step_px,
            ),
        )

        for snapshot in page_snapshots:
            try:
                job_uid = str(snapshot.get("job_uid") or "").strip()
                if not job_uid or job_uid in seen_job_uids:
                    continue

                if isinstance(max_job_age_days, int):
                    age_days = parse_job_age_days(str(snapshot.get("date_posted", "")))
                    if age_days is not None and age_days > max_job_age_days:
                        continue

                current_cards = driver.find_elements(By.XPATH, "//article[@data-testid='job-card']")
                target_card = None
                for current_card in current_cards:
                    try:
                        current_job_id = str(current_card.get_attribute("data-job-id") or "").strip()
                    except Exception:
                        continue
                    if current_job_id and current_job_id == str(snapshot.get("job_id") or "").strip():
                        target_card = current_card
                        break

                if target_card is None:
                    continue

                select_jobstreet_detail_panel(target_card)
                WebDriverWait(driver, 15).until(
                    lambda drv: str(drv.execute_script("return document.body ? document.body.innerText : ''") or "").find(str(snapshot.get("title") or "").strip()) != -1
                )

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

            if len(snapshots) >= max_jobs:
                break

        if len(snapshots) >= max_jobs:
            break

        next_url = find_next_page_url(driver, ["//a[@aria-label='Next']"])
        if not next_url:
            break

        safe_get(driver, next_url)
        wait_for_jobstreet_login(driver, timeout_seconds=login_timeout_seconds)
        page_turns += 1

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
    verification_timeout_seconds = settings.get("indeed_verification_timeout_seconds", 240)
    verification_timeout_seconds = int(verification_timeout_seconds) if isinstance(verification_timeout_seconds, int) else 240

    query = urlencode(
        {
            "q": keyword,
            "l": settings.get("location", ""),
            "fromage": fromage,
            "sort": "date",
        },
    )
    search_url = f"{jobs_url_base}?{query}"
    safe_get(driver, search_url)
    wait_for_indeed_verification(driver, timeout_seconds=verification_timeout_seconds)
    card_selector = (
        By.XPATH,
        "//div[contains(@class,'tapItem') or contains(@class,'job_seen_beacon')][.//a[@data-automation='jobTitle' or @data-testid='job-card-title' or contains(@class,'jcs-JobTitle')]]",
    )
    WebDriverWait(driver, 60).until(lambda drv: len(drv.find_elements(*card_selector)) > 0)

    snapshots: list[dict[str, object]] = []
    page_turns = 0
    while len(snapshots) < max_jobs and page_turns < 20:
        WebDriverWait(driver, 60).until(lambda drv: len(drv.find_elements(*card_selector)) > 0)
        page_snapshots = list(
            collect_cards(
                driver,
                card_selector,
                lambda card: parse_indeed_card(card, source_name, keyword, str(settings.get("location", ""))),
                max_jobs=max_jobs - len(snapshots),
                pause_seconds=scroll_pause_seconds,
                step_px=scroll_step_px,
            ),
        )

        for snapshot in page_snapshots:
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

                snapshot["posted_date"] = parse_job_posted_date(str(snapshot.get("date_posted", "")))
                snapshot["description"] = str(snapshot.get("description") or "").strip() or str(snapshot.get("title") or "")
                if not snapshot.get("title"):
                    continue

                seen_job_uids.add(job_uid)
                snapshots.append(snapshot)
            except StaleElementReferenceException:
                continue
            finally:
                time.sleep(random.uniform(between_cards_min, between_cards_max))

            if len(snapshots) >= max_jobs:
                break

        if len(snapshots) >= max_jobs:
            break

        next_url = find_next_page_url(driver, ["//a[contains(@aria-label,'Next')]", "//button[contains(@aria-label,'Next')]/ancestor::a[1]"])
        if not next_url:
            break

        safe_get(driver, next_url)
        wait_for_indeed_verification(driver, timeout_seconds=verification_timeout_seconds)
        page_turns += 1

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
            if not job.get("extracted_location"):
                job["extracted_location"] = job.get("location") or ""
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
