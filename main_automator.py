# main_automator.py

import time
import random
import logging
import os
import pandas as pd
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import smtplib
import traceback
from email.mime.text import MIMEText
from typing import List, Optional

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager

import config
from google_rank_finder import find_google_rank
from page_optimizer import analyze_myntra_page, perform_internal_search

# --- CONFIGURATION ---
AUTOMATOR_WORKSHEET_NAME = "kwd optimization"
FALLBACK_URL = "https://www.myntra.com"
# --- NEW: Name of the column to track progress ---
STATUS_COLUMN_NAME = "Processing Status"


# --- LOGGING & EMAIL FUNCTIONS ---
log_file_path = os.path.join(config.PROJECT_ROOT, 'main_automator.log')
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[logging.FileHandler(log_file_path, mode='w'), logging.StreamHandler()]
)

def send_error_email(subject: str, body: str):
    """Sends an email notification for critical errors or alerts."""
    if not config.ENABLE_EMAIL_NOTIFICATIONS:
        return
    recipients: List[str] = config.RECIPIENT_EMAIL
    logging.info(f"Preparing to send email alert to: {', '.join(recipients)}")
    try:
        msg = MIMEText(body, 'plain')
        msg['Subject'] = subject
        msg['From'] = config.SENDER_EMAIL
        msg['To'] = ", ".join(recipients)
        with smtplib.SMTP(config.SMTP_SERVER, config.SMTP_PORT) as server:
            server.starttls()
            server.login(config.SENDER_EMAIL, config.SENDER_PASSWORD)
            server.sendmail(config.SENDER_EMAIL, recipients, msg.as_string())
            logging.info("Email alert sent successfully.")
    except Exception as e:
        logging.critical(f"CRITICAL: FAILED TO SEND EMAIL ALERT. Error: {e}")

# --- HELPER & SETUP FUNCTIONS ---
def get_humanlike_driver() -> webdriver.Chrome:
    """Initializes and returns a configured, human-like Selenium WebDriver."""
    logging.info("Initializing human-like Chrome WebDriver...")
    options = Options()
    random_user_agent = random.choice(config.USER_AGENTS)
    logging.info(f"Using User-Agent: {random_user_agent}")
    options.add_argument(f'user-agent={random_user_agent}')
    options.add_argument(f"--user-data-dir={config.CHROME_PROFILE_PATH}")
    options.add_argument("--no-first-run")
    options.add_argument("--disable-infobars")
    options.add_argument("--disable-extensions")
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option('useAutomationExtension', False)
    service = Service(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=options)
    driver.set_page_load_timeout(60)
    return driver

def connect_to_google_sheets() -> gspread.Client:
    """Connects to the Google Sheets API and returns the client object."""
    logging.info("Connecting to Google Sheets API...")
    scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
    creds = ServiceAccountCredentials.from_json_keyfile_name(config.GCP_CREDENTIALS_PATH, scope)
    client = gspread.authorize(creds)
    logging.info("Successfully connected to Google Sheets API.")
    return client

def get_data_from_sheet(worksheet: gspread.Worksheet) -> pd.DataFrame:
    """Fetches all data from a worksheet and returns it as a DataFrame."""
    logging.info(f"Fetching data from worksheet: '{worksheet.title}'")
    records = worksheet.get_all_records()
    df = pd.DataFrame(records)
    df['original_index'] = df.index + 2
    logging.info(f"Successfully fetched {len(df)} keywords.")
    return df

# --- MAIN EXECUTION BLOCK ---
if __name__ == "__main__":
#    logging.info("Attempting to terminate any running Chrome processes...")
#    os.system("taskkill /F /IM chrome.exe >nul 2>&1")
    time.sleep(3)
    logging.info(f"--- Starting SEO Opportunity Automator for worksheet '{AUTOMATOR_WORKSHEET_NAME}' ---")
    driver = None
    try:
        gspread_client = connect_to_google_sheets()
        sheet = gspread_client.open(config.SHEET_NAME)
        worksheet = sheet.worksheet(AUTOMATOR_WORKSHEET_NAME)
        df = get_data_from_sheet(worksheet)
        
        # --- NEW: Get the column index for the status column ---
        headers = worksheet.row_values(1)
        status_col_index: Optional[int] = None
        try:
            # +1 because gspread is 1-indexed
            status_col_index = headers.index(STATUS_COLUMN_NAME) + 1
            logging.info(f"Found '{STATUS_COLUMN_NAME}' column at index {status_col_index}.")
        except ValueError:
            logging.error(f"CRITICAL: The required '{STATUS_COLUMN_NAME}' column was not found in the sheet.")
            logging.error("Please add this column to your Google Sheet and restart the script.")
            exit() # Exit the script if the column is missing

        driver = get_humanlike_driver()

        for i, (df_index, row) in enumerate(df.iterrows()):
            keyword = str(row.get('Keyword', '')).strip()
            target_url = str(row.get('Company1', '')).strip()
            original_row_index = row['original_index']
            
            # --- NEW: Check the status of the row before processing ---
            status = str(row.get(STATUS_COLUMN_NAME, '')).strip()
            if status == 'Completed':
                logging.info(f"Skipping row {original_row_index} ('{keyword}') as it is already marked 'Completed'.")
                continue

            logging.info(f"\n{'='*80}\n>>> PROCESSING {i+1}/{len(df)}: '{keyword}' (Sheet Row: {original_row_index})\n{'='*80}")

            if not keyword or not target_url:
                logging.warning(f"Skipping row {original_row_index} due to missing Keyword or Company1 URL.")
                continue

            # --- Phase 1: Google Ranking ---
            found_rank, ranking_url = find_google_rank(driver, keyword, target_url)
            
            if ranking_url:
                start_url_for_analysis = ranking_url
            else:
                start_url_for_analysis = FALLBACK_URL
            
            worksheet.update_cell(original_row_index, 3, found_rank)
            worksheet.update_cell(original_row_index, 4, ranking_url)
            logging.info(f"Updated Sheet [Rankings, Ranking URL] for row {original_row_index}.")

            # --- Phase 2: On-Page SEO Analysis ---
            page_to_analyze = perform_internal_search(driver, keyword, start_url_for_analysis)
            
            logging.info(f"Re-navigating to the cleaned URL for analysis: {page_to_analyze}")
            driver.get(page_to_analyze)
            WebDriverWait(driver, 15).until(EC.presence_of_element_located((By.TAG_NAME, "body")))
            
            analysis_result = analyze_myntra_page(driver, keyword, page_to_analyze)
            
            # --- Phase 3: Final Sheet Update ---
            analysis_status = analysis_result.get('status')
            
            worksheet.update_cell(original_row_index, 5, "")
            worksheet.update_cell(original_row_index, 6, "")
            worksheet.update_cell(original_row_index, 7, "")

            if analysis_status == 'Deletion':
                worksheet.update_cell(original_row_index, 5, keyword)
            elif analysis_status == 'T&M':
                worksheet.update_cell(original_row_index, 6, page_to_analyze)
            elif analysis_status == 'Content':
                worksheet.update_cell(original_row_index, 7, page_to_analyze)
            
            # --- NEW: Mark the row as 'Completed' after all work is done ---
            if status_col_index:
                worksheet.update_cell(original_row_index, status_col_index, 'Completed')
                logging.info(f"Marked row {original_row_index} as 'Completed'.")

            logging.info("Taking a break before the next keyword...")
            time.sleep(random.uniform(12.0, 22.0))

    except Exception as e:
        error_traceback = traceback.format_exc()
        logging.critical(f"A critical, unhandled error occurred: {e}\n{error_traceback}")
        email_body = f"The SEO Opportunity Automator script has crashed.\n\nError:\n{e}\n\nTraceback:\n{error_traceback}"
        send_error_email("SEO Automator Alert: SCRIPT CRASHED", email_body)

    finally:
        if driver:
            logging.info("Closing WebDriver.")
            driver.quit()
        logging.info("--- SEO Opportunity Automator Script Finished ---")