from __future__ import annotations

import time

from selenium.common.exceptions import TimeoutException
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.remote.webdriver import WebDriver
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait


def _log(message: str) -> None:
    print(f"[login] {message}", flush=True)


def _first_visible_element(
    wait: WebDriverWait,
    selectors: list[tuple[str, str]],
):
    for selector in selectors:
        try:
            element = wait.until(EC.visibility_of_element_located(selector))
            if element:
                return element
        except TimeoutException:
            continue
    return None


def _fill_input(driver: WebDriver, element, value: str, label: str) -> None:
    driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", element)
    element.click()
    element.clear()
    element.send_keys(value)
    time.sleep(0.2)

    current_value = element.get_attribute("value") or ""
    if current_value.strip():
        _log(f"filled {label} field with native input")
        return

    driver.execute_script(
        """
        const el = arguments[0];
        const value = arguments[1];
        const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set;
        setter.call(el, value);
        el.dispatchEvent(new Event('input', { bubbles: true }));
        el.dispatchEvent(new Event('change', { bubbles: true }));
        """,
        element,
        value,
    )

    current_value = element.get_attribute("value") or ""
    if not current_value.strip():
        raise RuntimeError(f"Unable to populate LinkedIn {label} field.")

    _log(f"filled {label} field with script fallback")


def _wait_for_logged_in_state(wait: WebDriverWait) -> bool:
    try:
        wait.until(
            EC.any_of(
                EC.url_contains("/feed"),
                EC.url_contains("/jobs"),
                EC.presence_of_element_located(
                    (
                        By.XPATH,
                        "//*[@role='search' or @aria-label='Search' or contains(@aria-label, 'Search')]",
                    )
                ),
            )
        )
        return True
    except TimeoutException:
        return False


def login_to_linkedin(
    driver: WebDriver,
    email: str,
    password: str,
    login_url: str,
    timeout: int = 20,
) -> None:
    wait = WebDriverWait(driver, timeout)
    _log("opening LinkedIn login page")
    driver.get(login_url)
    wait.until(lambda drv: drv.execute_script("return document.readyState") == "complete")
    time.sleep(1.5)

    if "/feed" in driver.current_url or "/jobs" in driver.current_url:
        _log("already logged in, skipping credential entry")
        return

    email_selectors = [
        (By.ID, "username"),
        (By.NAME, "session_key"),
        (By.XPATH, "//input[@autocomplete='username' or contains(@autocomplete,'username')]"),
        (By.XPATH, "//input[@aria-label='Email or phone' or @type='email' or @name='username']"),
    ]
    password_selectors = [
        (By.ID, "password"),
        (By.NAME, "session_password"),
        (By.XPATH, "//input[@autocomplete='current-password']"),
        (By.XPATH, "//input[@aria-label='Password' or @type='password']"),
    ]

    email_input = _first_visible_element(wait, email_selectors)
    password_input = _first_visible_element(wait, password_selectors)

    if email_input is None or password_input is None:
        _log("login form not detected; waiting for logged-in state or checkpoint to resolve")
        if _wait_for_logged_in_state(wait):
            _log("logged-in state detected without form interaction")
            return
        raise RuntimeError(
            "LinkedIn login form was not detected and the session did not reach a logged-in page. "
            "LinkedIn may have shown a checkpoint, CAPTCHA, or alternate sign-in flow."
        )

    _fill_input(driver, email_input, email, "email")
    _fill_input(driver, password_input, password, "password")

    submit_selectors = [
        (By.XPATH, "//button[@type='submit']"),
        (By.XPATH, "//input[@type='submit']"),
        (By.XPATH, "//button[contains(.,'Sign in') or contains(.,'Sign In')]"),
    ]
    submit_button = _first_visible_element(wait, submit_selectors)
    if submit_button is not None:
        submit_button.click()
        _log("clicked submit button")
    else:
        password_input.send_keys(Keys.RETURN)
        _log("submitted with Enter key")

    if _wait_for_logged_in_state(wait):
        _log("login completed")
        return

    _log("automatic login did not complete; waiting for manual completion")
    if _wait_for_logged_in_state(WebDriverWait(driver, timeout * 3)):
        _log("login completed after manual intervention")
        return

    raise RuntimeError(
        "LinkedIn login did not complete. Check credentials or whether a checkpoint/CAPTCHA appeared."
    )
