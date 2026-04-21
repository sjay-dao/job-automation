from __future__ import annotations

import re
from urllib.parse import parse_qs, urlparse

from selenium.common.exceptions import NoSuchElementException
from selenium.webdriver.common.by import By
from selenium.webdriver.remote.webelement import WebElement


def safe_text(parent: WebElement, xpath: str) -> str:
    try:
        return parent.find_element(By.XPATH, xpath).text.strip()
    except NoSuchElementException:
        return ""


def first_text(parent: WebElement, xpaths: list[str]) -> str:
    for xpath in xpaths:
        try:
            elements = parent.find_elements(By.XPATH, xpath)
        except NoSuchElementException:
            continue

        for element in elements:
            text = element.text.strip()
            if text:
                return text
    return ""


def get_job_link(job_card: WebElement) -> str:
    for xpath in [
        ".//a[contains(@class,'job-card-list__title--link') and contains(@href,'/jobs/view/')]",
        ".//a[contains(@href,'/jobs/view/')]",
        ".//*[@role='link' and contains(@href,'/jobs/view/')]",
        ".//a[contains(@aria-label,'job') or contains(@aria-label,'Job')]",
    ]:
        try:
            href = job_card.find_element(By.XPATH, xpath).get_attribute("href")
            if href:
                return href.split("?")[0]
        except NoSuchElementException:
            continue
    return ""


def extract_job_id(job_link: str, fallback_text: str = "") -> str:
    if job_link:
        match = re.search(r"/jobs/view/(\d+)", job_link)
        if match:
            return match.group(1)

        query_params = parse_qs(urlparse(job_link).query)
        if "currentJobId" in query_params and query_params["currentJobId"]:
            return query_params["currentJobId"][0]

    fallback_match = re.search(r"\b(\d{8,})\b", fallback_text)
    return fallback_match.group(1) if fallback_match else ""


def is_promoted(job_card: WebElement) -> bool:
    card_text = job_card.text.lower()
    return "promoted" in card_text or "sponsored" in card_text


def parse_applicant_count(text: str) -> int | None:
    match = re.search(r"(\d[\d,]*)\+?\s+applicants?", text.lower())
    if not match:
        return None
    return int(match.group(1).replace(",", ""))


def parse_title_from_description(text: str) -> str:
    for pattern in [
        r"(?im)^\s*position:\s*(.+?)\s*$",
        r"(?im)^\s*role:\s*(.+?)\s*$",
        r"(?im)^\s*job title:\s*(.+?)\s*$",
    ]:
        match = re.search(pattern, text)
        if match:
            return match.group(1).strip()
    return ""


def parse_company_from_description(text: str) -> str:
    for pattern in [
        r"(?im)^\s*.*?\bwith\s+(.+?)!\s*$",
        r"(?im)^\s*company:\s*(.+?)\s*$",
        r"(?im)^\s*employer:\s*(.+?)\s*$",
    ]:
        match = re.search(pattern, text)
        if match:
            return match.group(1).strip()
    return ""


def parse_location_from_description(text: str) -> str:
    match = re.search(r"(?im)^\s*location:\s*(.+?)\s*$", text)
    if match:
        return match.group(1).strip()
    return ""


def extract_card_snapshot(job_card: WebElement) -> dict[str, str]:
    title = first_text(
        job_card,
        [
            ".//a[contains(@class,'job-card-list__title--link')]/span[@aria-hidden='true']",
            ".//a[contains(@class,'job-card-list__title--link')]",
            ".//h3[1]",
            ".//strong[1]",
        ],
    )
    company = first_text(
        job_card,
        [
            ".//div[contains(@class,'artdeco-entity-lockup__subtitle')]//span[1]",
            ".//*[contains(@class,'artdeco-entity-lockup__subtitle')]//span[1]",
            ".//h4[1]",
        ],
    )
    location = first_text(
        job_card,
        [
            ".//div[contains(@class,'artdeco-entity-lockup__caption')]//span[1]",
            ".//*[contains(@class,'artdeco-entity-lockup__caption')]//span[1]",
            ".//ul[contains(@class,'job-card-container__metadata-wrapper')]//li[1]//span[1]",
            ".//*[contains(@class,'location')]//span[1]",
        ],
    )
    date_posted = first_text(
        job_card,
        [
            ".//time[1]",
            ".//ul[contains(@class,'job-card-container__footer-wrapper')]//li[not(contains(@class,'footer-job-state'))]//span[1]",
        ],
    )
    job_link = get_job_link(job_card)
    job_id = (
        job_card.get_attribute("data-occludable-job-id")
        or job_card.get_attribute("data-job-id")
        or extract_job_id(job_link, job_card.text)
    )

    return {
        "title": title,
        "company": company,
        "location": location,
        "date_posted": date_posted,
        "job_link": job_link,
        "job_id": job_id,
    }


def extract_description_panel(driver) -> dict[str, str | int | None]:
    panel_text = ""
    for xpath in [
        "//*[@id='job-details' or contains(@class,'jobs-description') or @aria-label='Job details']",
        "//section[contains(@class,'jobs-search__right-rail')]",
    ]:
        elements = driver.find_elements(By.XPATH, xpath)
        if elements:
            panel_text = elements[0].text.strip()
            if panel_text:
                break

    applicants = parse_applicant_count(panel_text)
    return {
        "description": panel_text,
        "applicant_count": applicants,
        "derived_title": parse_title_from_description(panel_text),
        "derived_company": parse_company_from_description(panel_text),
        "derived_location": parse_location_from_description(panel_text),
    }
