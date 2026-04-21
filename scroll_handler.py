from __future__ import annotations

import random
import time
from typing import Iterable

from selenium.webdriver.common.by import By
from selenium.webdriver.remote.webelement import WebElement


def find_scroll_container(driver) -> WebElement | None:
    candidates: Iterable[tuple[str, str]] = [
        (
            By.XPATH,
            "//div[contains(@class,'jobs-search-results-list') and @role='list']",
        ),
        (
            By.XPATH,
            "//div[contains(@class,'jobs-search-results-list')]",
        ),
        (
            By.XPATH,
            "//section[contains(@class,'jobs-search-two-pane') or @aria-label='Search results']"
            "//div[contains(@style,'overflow')]",
        ),
    ]

    for by, selector in candidates:
        matches = driver.find_elements(by, selector)
        if matches:
            return matches[0]
    return None


def scroll_until_stable(
    driver,
    card_selector: tuple[str, str],
    pause_seconds: float = 1.1,
    step_px: int = 640,
) -> None:
    container = find_scroll_container(driver)
    stable_rounds = 0
    previous_count = -1
    previous_height = -1

    while stable_rounds < 3:
        cards = driver.find_elements(*card_selector)
        current_count = len(cards)

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
