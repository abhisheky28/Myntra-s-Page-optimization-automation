# page_optimizer.py

import logging
import re
from typing import Dict, Any

from selenium.webdriver.remote.webdriver import WebDriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException

# --- SELECTORS FOR MYNTRA PAGE ANALYSIS ---
INTERNAL_SEARCH_SELECTOR = "input.desktop-searchBar"
DELETION_SELECTOR = "span.title-corrections"
PRODUCT_COUNT_SELECTOR = "span.title-count"
SEO_CONTAINER_SELECTOR = "div.index-seoContainer"


def perform_internal_search(driver: WebDriver, keyword: str, start_url: str) -> str:
    """
    Navigates to a starting URL, performs an internal search, and returns the cleaned result URL.

    Args:
        driver: The active Selenium WebDriver instance.
        keyword: The keyword to search for on the site.
        start_url: The initial URL to navigate to (ranking URL or fallback).

    Returns:
        The final, cleaned URL after the internal search. Returns the start_url if search fails.
    """
    logging.info(f"Performing internal search for '{keyword}' starting from {start_url}")
    try:
        driver.get(start_url)
        search_bar = WebDriverWait(driver, 15).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, INTERNAL_SEARCH_SELECTOR))
        )
        search_bar.clear()
        search_bar.send_keys(keyword)
        search_bar.send_keys(Keys.RETURN)

        # --- FIX: More robust wait condition ---
        # Wait for either the product count (success) or the corrections message (no results) to appear.
        # This confirms the search results page has loaded before we get the URL.
        wait_for_selectors = f"{PRODUCT_COUNT_SELECTOR}, {DELETION_SELECTOR}"
        WebDriverWait(driver, 15).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, wait_for_selectors))
        )
        
        # --- FIX: Capture and clean the URL *after* the page has loaded ---
        final_url = driver.current_url.split('?')[0]
        logging.info(f"Internal search complete. Cleaned URL: {final_url}")
        return final_url
        
    except TimeoutException:
        logging.error("Page did not load to a recognizable search result or 'no results' page. Using start URL as fallback.")
        return start_url.split('?')[0] # Also clean the start URL just in case
    except Exception as e:
        logging.error(f"An unexpected error occurred during internal search: {e}")
        return start_url.split('?')[0]


def check_for_deletion(driver: WebDriver) -> bool:
    """
    Checks if the page is a 'no results' page, indicating the keyword should be deleted.

    Args:
        driver: The active Selenium WebDriver instance.

    Returns:
        True if the deletion indicator is found, False otherwise.
    """
    try:
        if driver.find_elements(By.CSS_SELECTOR, DELETION_SELECTOR):
            logging.warning("DELETION CHECK: Found 'no results' indicator. Keyword should be deleted.")
            return True
    except Exception as e:
        logging.error(f"Error during deletion check: {e}")
    return False


def check_for_tm_optimization(driver: WebDriver) -> bool:
    """
    Checks for basic Title & Meta description optimization issues.

    Args:
        driver: The active Selenium WebDriver instance.

    Returns:
        True if any T&M issue is found, False otherwise.
    """
    try:
        # 1. Check for missing title or meta description
        title = driver.title
        if not title:
            logging.warning("T&M CHECK: Page <title> is missing.")
            return True

        try:
            meta_desc_element = driver.find_element(By.CSS_SELECTOR, 'meta[name="description"]')
            meta_desc = meta_desc_element.get_attribute("content") or ""
        except NoSuchElementException:
            logging.warning("T&M CHECK: <meta name='description'> tag is missing.")
            return True

        # 2. Check for placeholder character in meta description
        if "✯" in meta_desc:
            logging.warning("T&M CHECK: Found '✯' character in meta description.")
            return True

        # 3. Check length constraints
        title_len = len(title)
        meta_len = len(meta_desc)
        if not (45 <= title_len <= 70):
            logging.warning(f"T&M CHECK: Title length ({title_len}) is outside the 45-70 character range.")
            return True
        if not (145 <= meta_len <= 165):
            logging.warning(f"T&M CHECK: Meta description length ({meta_len}) is outside the 145-165 character range.")
            return True

    except Exception as e:
        logging.error(f"Error during T&M optimization check: {e}")
    return False


def is_product_count_sufficient(driver: WebDriver) -> bool:
    """
    Checks if the product count on the page is 13 or more.

    Args:
        driver: The active Selenium WebDriver instance.

    Returns:
        True if product count is >= 13, False otherwise (or if not found).
    """
    try:
        count_element = driver.find_element(By.CSS_SELECTOR, PRODUCT_COUNT_SELECTOR)
        count_text = count_element.text
        # Use regex to find any number in the string
        match = re.search(r'\d+', count_text.replace(',', ''))
        if match:
            product_count = int(match.group(0))
            logging.info(f"PRODUCT COUNT CHECK: Found {product_count} items.")
            if product_count < 13:
                logging.warning("Product count is less than 13. Stopping analysis for this page.")
                return False
            return True
        else:
            logging.warning("PRODUCT COUNT CHECK: Could not parse number from count text.")
            return False
    except NoSuchElementException:
        logging.warning("PRODUCT COUNT CHECK: Product count element not found.")
        return False # Treat as insufficient if not found
    except Exception as e:
        logging.error(f"Error during product count check: {e}")
        return False


def check_for_content_optimization(driver: WebDriver) -> bool:
    """
    Checks for the presence and word count of the main SEO content block.

    Args:
        driver: The active Selenium WebDriver instance.

    Returns:
        True if the content needs optimization, False otherwise.
    """
    try:
        seo_container = driver.find_element(By.CSS_SELECTOR, SEO_CONTAINER_SELECTOR)
        content_text = seo_container.text
        word_count = len(content_text.split())
        logging.info(f"CONTENT CHECK: Found SEO container with {word_count} words.")
        if word_count < 250:
            logging.warning("CONTENT CHECK: Word count is less than 250.")
            return True
    except NoSuchElementException:
        logging.warning("CONTENT CHECK: SEO content container not found.")
        return True # Missing container is an optimization issue
    except Exception as e:
        logging.error(f"Error during content optimization check: {e}")
    return False


def analyze_myntra_page(driver: WebDriver, keyword: str, start_url: str) -> Dict[str, Any]:
    """
    Master function to orchestrate the on-page analysis funnel.

    Args:
        driver: The active Selenium WebDriver instance.
        keyword: The keyword being analyzed.
        start_url: The URL to begin the analysis from.

    Returns:
        A dictionary with the analysis result, e.g.,
        {'status': 'Deletion', 'value': 'Yes'}
    """
    logging.info(f"--- Starting On-Page Analysis for '{keyword}' ---")

    # Step B: Keyword Deletion Check
    if check_for_deletion(driver):
        return {'status': 'Deletion', 'value': 'Yes'}

    # Step C: T&M Optimization Check
    if check_for_tm_optimization(driver):
        return {'status': 'T&M', 'value': 'Yes'}

    # Step D: Product Count Check
    if not is_product_count_sufficient(driver):
        return {'status': 'Low Product Count', 'value': 'Analysis stopped due to < 13 products.'}

    # Step E: Content Optimization Check
    if check_for_content_optimization(driver):
        return {'status': 'Content', 'value': 'Yes'}

    logging.info("All on-page checks passed. Page is considered optimized.")
    return {'status': 'Optimized', 'value': 'All checks passed'}