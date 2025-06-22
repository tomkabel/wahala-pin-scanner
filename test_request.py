import re
import sys

import requests
from bs4 import BeautifulSoup


# --- 1. Primary Method: BeautifulSoup Parser (Reliable and Precise) ---
def extract_exam_summary_bs(html_content: str) -> str:
    """
    Parses the HTML using BeautifulSoup to precisely extract the exam summary.
    This is the preferred method.
    """
    soup = BeautifulSoup(html_content, 'html.parser')
    
    # Extract Subject and Password
    subject = "Subject not found"
    password = "Password not found"
    container = soup.find('div', class_='itemContainer')
    if container and container.b:
        br_tag = container.b.find('br')
        if br_tag:
            br_tag.replace_with('|')
        full_text = container.b.get_text(strip=True)
        parts = full_text.split('|')
        if len(parts) == 2:
            subject = parts[0].replace('SUBJECT:', '').strip()
            password = parts[1].strip()

    # Extract TOURISM OBJ section
    obj_answers_block = ""
    first_post = soup.find('div', class_='positem')
    if first_post:
        full_text = first_post.get_text()
        lines = [line.strip() for line in full_text.splitlines() if line.strip()]
        if lines:
            header = lines[0]
            answer_lines = lines[1:]
            obj_answers_block = f"{header}\n\n" + "\n".join(answer_lines)

    # Assemble and return the final output if content was found
    if obj_answers_block:
        return f"""{subject}
{password}

{obj_answers_block}"""
    else:
        # Raise an error if the primary method fails to find content, triggering the fallback
        raise ValueError("BS parser could not find the required content blocks.")


# --- 2. Fallback Method: Raw Text Processing (Resilient) ---
def extract_via_raw_text(html_content: str) -> str:
    """
    Fallback function to extract exam info by processing the raw HTML as text.
    It works by finding start and end markers and cleaning the text in between.
    """
    lines = html_content.splitlines()
    
    start_index = -1
    end_index = -1

    # Find the start line (containing SUBJECT:)
    for i, line in enumerate(lines):
        if 'SUBJECT:' in line:
            start_index = i
            break
            
    # If a start was found, find the end line (containing '===')
    if start_index != -1:
        for i, line in enumerate(lines[start_index:], start=start_index):
            # End if we see a line with '=================================' or likely start of answers like (1), (1a), or (
            if (
                '=================================' in line
                or '=====' in line
                or '++++++' in line
                or re.match(r'\(\s*1\s*\)', line)
                or re.match(r'\(\s*1a?\s*\)', line)
                or re.match(r'^\s*\(', line)
            ):
                end_index = i
                break
    
    # If we couldn't find both markers, the fallback fails
    if start_index == -1 or end_index == -1:
        return "Fallback failed: Could not find start/end markers."

    # Slice the relevant lines
    content_lines = lines[start_index:end_index]
    
    cleaned_lines = []
    for line in content_lines:
        # First, convert <br> tags to newlines to preserve them
        line_with_newlines = re.sub(r'<br\s*/?>', '\n', line, flags=re.IGNORECASE)
        # Then, remove all other HTML tags
        no_html = re.sub(r'<.*?>', '', line_with_newlines)
        # Strip whitespace from the resulting text
        stripped = no_html.strip()
        if stripped:
            cleaned_lines.append(stripped)
            
    return "\n".join(cleaned_lines)


# --- 3. Main Wrapper Function ---
def get_exam_summary(html_content: str, use_fallback_only=False) -> str:
    """
    Tries to parse the HTML with BeautifulSoup first. If it fails, it
    uses the raw text processing fallback method.
    """
    if use_fallback_only:
        print("[*] Forcing raw text fallback method.")
        return extract_via_raw_text(html_content)
        
    try:
        # Try the precise, primary method first
        return extract_exam_summary_bs(html_content)
    except Exception as e:
        # If any error occurs, switch to the fallback
        print(f"[!] BeautifulSoup parsing failed ({type(e).__name__}). Falling back to raw text processing.")
        return extract_via_raw_text(html_content)

# --- Example Usage ---

# The raw HTML response provided in the problem
# --- CONFIGURATION (from pin_scanner.py) ---
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

# --- SUCCESS/FAILURE CONDITIONS (from pin_scanner.py) ---
FAILURE_INDICATOR_TEXT = "invalid pin"
SPECIAL_INDICATOR_TEXT = "2025"


def test_pin(pin_to_test):
    """
    Sends a single request to test a specific PIN and prints the result.
    """
    payload = {"pin": pin_to_test, "access": "Get Answers"}

    print(f"[*] Testing PIN: {pin_to_test} against {URL}")

    try:
        response = requests.post(URL, headers=HEADERS, data=payload, timeout=10)
        response.raise_for_status()  # Raise an exception for bad status codes (4xx or 5xx)
        response_text = response.text

        print(f"[*] Response Status Code: {response.status_code}")
        # For debugging, you can uncomment the next line to see the response body
        # print(f"[*] Response Body (first 250 chars): {response_text[:250]}...")

        # --- Logic from pin_scanner.py ---
        is_special_find = SPECIAL_INDICATOR_TEXT in response_text
        is_failure = FAILURE_INDICATOR_TEXT.lower() in response_text.lower()

        if is_special_find:
            print(get_exam_summary(response_text, True))

    except requests.exceptions.RequestException as e:
        print(f"[!] A network error occurred: {e}")


if __name__ == "__main__":
    if len(sys.argv) > 1:
        pin = sys.argv[1]
    else:
        pin = "1234"  # Default PIN to test if none is provided
        print(f"[*] No PIN provided. Using default test PIN: {pin}")

    test_pin(pin)
