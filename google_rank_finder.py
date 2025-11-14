# google_rank_finder.py

import time
import random
import logging
from typing import Tuple, Optional

from selenium.webdriver.remote.webdriver import WebDriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException, ElementClickInterceptedException

import config
import serp_selectors

# --- LOCAL CONSTANTS FOR GOOGLE SCRAPING ---
MAX_PAGES_TO_SCRAPE = 1
DETOUR_PROBABILITY = 0.50

DETOUR_SELECTORS = {
    "images": "a[href*='&tbm=isch']",
    "videos": "a[href*='&tbm=vid']",
    "news": "a[href*='&tbm=nws']",
    "maps": "a[href*='maps.google.com']"
}

SEARCH_INPUT_SELECTOR = "[name='q']"

DELAY_CONFIG = {
    "typing": {"min": 0.09, "max": 0.22},
    "after_page_load": {"min": 2.5, "max": 5.0},
    "serp_read": {"min": 5.0, "max": 8.5},
    "before_next_page": {"min": 2.0, "max": 4.0},
    "detour_view": {"min": 5.0, "max": 9.0}
}


def _send_captcha_alert(keyword: str):
    """
    Sends an email alert about a detected CAPTCHA.
    This is a helper function and relies on the main script's email setup.
    """
    try:
        # This is a simplified import to avoid circular dependencies.
        # The main script will have the full send_error_email function.
        from main_automator import send_error_email
        email_subject = "Ranking Automator Alert: CAPTCHA - Action Required"
        email_body = f"Hello,\n\nThe script has encountered a Google CAPTCHA and is now paused.\n\nKeyword: \"{keyword}\"\n\nPlease solve the security check in the browser. The script will automatically resume.\n\n- Automated System"
        send_error_email(email_subject, email_body)
    except ImportError:
        logging.warning("Could not import send_error_email. CAPTCHA email alert not sent.")
    except Exception as e:
        logging.error(f"Failed to send CAPTCHA alert email: {e}")


def handle_captcha(driver: WebDriver, keyword: str) -> bool:
    """
    Pauses the script and waits for a human to solve a Google CAPTCHA.

    Args:
        driver: The active Selenium WebDriver instance.
        keyword: The keyword that triggered the CAPTCHA.

    Returns:
        True if the CAPTCHA was solved within the timeout, False otherwise.
    """
    alert_sent = False
    start_time = time.time()
    logging.warning("!!! CAPTCHA DETECTED !!! Pausing script and waiting for manual intervention.")

    while time.time() - start_time < config.CAPTCHA_WAIT_TIMEOUT:
        captcha_elements = driver.find_elements(By.CSS_SELECTOR, 'iframe[title="reCAPTCHA"]')
        if not captcha_elements:
            logging.info("CAPTCHA solved! Resuming script.")
            return True

        if not alert_sent:
            print("\n" + "="*60)
            print(f"ACTION REQUIRED: Please solve the CAPTCHA in the browser.")
            print(f"The script will wait for up to {config.CAPTCHA_WAIT_TIMEOUT / 60:.0f} minutes.")
            print("It will automatically resume once the CAPTCHA is solved.")
            print("="*60 + "\n")
            _send_captcha_alert(keyword)
            alert_sent = True

        time.sleep(config.CAPTCHA_CHECK_INTERVAL)
        print(".", end="", flush=True)

    logging.error(f"CAPTCHA Timeout! Waited for {config.CAPTCHA_WAIT_TIMEOUT} seconds but CAPTCHA was not solved.")
    logging.error(f"Aborting keyword '{keyword}' and moving to the next one.")
    return False


def perform_random_detour(driver: WebDriver, target_url: str):
    """
    Performs a random human-like action on the SERP to avoid detection.

    Args:
        driver: The active Selenium WebDriver instance.
        target_url: The URL we are searching for, to avoid clicking on it.
    """
    logging.info(">>> Performing a random detour for human-like behavior...")
    detour_options = list(DETOUR_SELECTORS.keys()) + ['random_link']
    chosen_detour = random.choice(detour_options)

    try:
        if chosen_detour == 'random_link':
            logging.info(f"...Detour: Clicking a random organic link.")
            all_results = driver.find_elements(By.CSS_SELECTOR, serp_selectors.RESULT_CONTAINER)
            non_target_links = [
                res.find_element(By.CSS_SELECTOR, serp_selectors.LINK_CONTAINER)
                for res in all_results
                if target_url not in (res.find_element(By.CSS_SELECTOR, serp_selectors.LINK_CONTAINER).get_attribute('href') or '')
            ]
            if non_target_links:
                random.choice(non_target_links).click()
            else:
                logging.warning("...Could not find a non-target link for detour, skipping.")
                return
        else:
            logging.info(f"...Detour: Clicking on '{chosen_detour.capitalize()}' tab.")
            selector = DETOUR_SELECTORS[chosen_detour]
            driver.find_element(By.CSS_SELECTOR, selector).click()

        time.sleep(random.uniform(DELAY_CONFIG["detour_view"]["min"], DELAY_CONFIG["detour_view"]["max"]))
        logging.info("<<< Returning from detour.")
        driver.back()
        time.sleep(random.uniform(2.0, 4.0))

    except (NoSuchElementException, ElementClickInterceptedException):
        logging.warning(f"Could not perform detour '{chosen_detour}'. The element might not be available.")
    except Exception as e:
        logging.error(f"An unexpected error occurred during detour: {e}")


def _find_rank_on_current_page(driver: WebDriver, target_url: str, rank_offset: int) -> Tuple[Optional[int], Optional[str]]:
    """
    Scans the current SERP for the target URL and returns its rank and exact URL.

    Args:
        driver: The active Selenium WebDriver instance.
        target_url: The base domain or URL to search for.
        rank_offset: The starting rank for the current page (e.g., 0 for page 1, 10 for page 2).

    Returns:
        A tuple of (rank, found_url) if found, otherwise (None, None).
    """
    try:
        WebDriverWait(driver, 5).until(EC.presence_of_element_located((By.CSS_SELECTOR, serp_selectors.RESULT_CONTAINER)))
        all_potential_blocks = driver.find_elements(By.CSS_SELECTOR, serp_selectors.RESULT_CONTAINER)
        clean_organic_results = []
        for block in all_potential_blocks:
            try:
                if block.find_elements(By.CSS_SELECTOR, "[data-text-ad]"): continue
                h3_element = block.find_element(By.CSS_SELECTOR, "h3")
                if not h3_element.text.strip(): continue
                clean_organic_results.append(block)
            except NoSuchElementException: continue

        for rank, organic_block in enumerate(clean_organic_results, start=1 + rank_offset):
            try:
                link_element = organic_block.find_element(By.CSS_SELECTOR, serp_selectors.LINK_CONTAINER)
                actual_url = link_element.get_attribute('href')
                if actual_url and target_url in actual_url:
                    logging.info(f"SUCCESS: Found a match for '{target_url}'")
                    return rank, actual_url
            except NoSuchElementException: continue
    except Exception as e:
        logging.error(f"An error occurred while scraping the current page: {e}")
    return None, None


def find_google_rank(driver: WebDriver, keyword: str, target_url: str) -> Tuple[str, str]:
    """
    Main function to find the Google rank for a given keyword and target URL.

    Args:
        driver: The active Selenium WebDriver instance.
        keyword: The search query.
        target_url: The domain or URL to find in the search results.

    Returns:
        A tuple containing the rank (as a string) and the found URL.
        Returns ("Not Found", "") if the URL is not found within the page limit.
    """
    try:
        driver.get(config.SEARCH_URL)
        time.sleep(random.uniform(DELAY_CONFIG["after_page_load"]["min"], DELAY_CONFIG["after_page_load"]["max"]))

        search_box = WebDriverWait(driver, 10).until(EC.presence_of_element_located((By.CSS_SELECTOR, SEARCH_INPUT_SELECTOR)))
        search_box.clear()
        for char in keyword:
            search_box.send_keys(char)
            time.sleep(random.uniform(DELAY_CONFIG["typing"]["min"], DELAY_CONFIG["typing"]["max"]))
        search_box.send_keys(Keys.RETURN)
        time.sleep(random.uniform(DELAY_CONFIG["after_page_load"]["min"], DELAY_CONFIG["after_page_load"]["max"]))

        if random.random() < DETOUR_PROBABILITY:
            perform_random_detour(driver, target_url)

        current_rank_offset = 0
        for page_num in range(1, MAX_PAGES_TO_SCRAPE + 1):
            logging.info(f"--- Scraping Page {page_num} for '{keyword}' (simulating reading) ---")
            time.sleep(random.uniform(DELAY_CONFIG["serp_read"]["min"], DELAY_CONFIG["serp_read"]["max"]))

            if driver.find_elements(By.CSS_SELECTOR, 'iframe[title="reCAPTCHA"]'):
                if not handle_captcha(driver, keyword):
                    break  # Abort this keyword if CAPTCHA times out

            rank_on_page, url_on_page = _find_rank_on_current_page(driver, target_url, current_rank_offset)
            if rank_on_page is not None and url_on_page is not None:
                logging.info(f"Found at Rank {rank_on_page} on page {page_num}. URL: {url_on_page}")
                return str(rank_on_page), url_on_page

            try:
                next_button = driver.find_element(By.CSS_SELECTOR, serp_selectors.NEXT_PAGE_BUTTON)
                logging.info("Moving to next page...")
                time.sleep(random.uniform(DELAY_CONFIG["before_next_page"]["min"], DELAY_CONFIG["before_next_page"]["max"]))
                driver.execute_script("arguments[0].click();", next_button)
                current_rank_offset += 10
            except NoSuchElementException:
                logging.info("No 'Next' button found. Reached the end of results.")
                break

    except TimeoutException:
        logging.error(f"Could not find the search box for keyword '{keyword}'. Skipping.")
    except Exception as e:
        logging.error(f"An unexpected error occurred during Google search for '{keyword}': {e}")

    logging.info(f"Finished scraping for '{keyword}'. Target URL not found.")
    return "Not Found", ""