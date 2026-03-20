#!/usr/bin/env python3
"""
PCSO Lottery Results Selenium Scraper

A Selenium-based web scraper for extracting Philippine Charity Sweepstakes Office
(PCSO) lottery draw results from the official PCSO website.

Features:
- Selenium WebDriver with Chrome headless mode
- Page Object Model pattern for maintainability
- Explicit waits for dynamic content
- Retry logic with exponential backoff
- User-agent rotation to avoid blocking
- Unicode/emoji support for Windows console
- Comprehensive logging
- Configurable behavior

Author: Web Scraper
Version: 1.0.0
"""

import json
import logging
import random
import re
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any, Tuple

# Selenium imports
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import (
    TimeoutException,
    NoSuchElementException,
    WebDriverException,
    StaleElementReferenceException
)

# ============================================================================
# CONFIGURATION
# ============================================================================

# User agents for rotation
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Safari/605.1.15",
]

# Supported lottery games
LOTTERY_GAMES = [
    "6/58",
    "6/49",
    "6/45",
    "6/42",
    "6D",
    "4D",
    "3D",
    "2D"
]

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler('pcso_selenium_scraper.log', encoding='utf-8')
    ]
)
logger = logging.getLogger(__name__)


# ============================================================================
# CONFIGURATION CLASS
# ============================================================================

@dataclass
class ScraperConfig:
    """Configuration options for the PCSO scraper."""
    # WebDriver settings
    headless: bool = True
    window_size: str = "1920,1080"
    implicit_wait: int = 10
    page_load_timeout: int = 30
    script_timeout: int = 30
    
    # Retry settings
    max_retries: int = 3
    retry_delay: float = 2.0
    
    # Fetch settings
    fetch_yesterday: bool = True
    fetch_today: bool = True
    
    # Display settings
    use_emoji: bool = True


# ============================================================================
# DATA CLASSES
# ============================================================================

@dataclass
class LotteryResult:
    """Represents a single lottery draw result."""
    game_name: str = ""
    winning_numbers: str = ""
    draw_date: str = ""
    draw_time: str = ""
    jackpot_prize: str = ""
    winners: str = ""
    combination: str = ""
    is_winner: bool = False


@dataclass
class DailyResults:
    """Represents results for a single day."""
    date: str = ""
    error: Optional[str] = None
    results: List[LotteryResult] = field(default_factory=list)


# ============================================================================
# BASE PAGE OBJECT
# ============================================================================

class BasePage:
    """Base page object with common functionality."""
    
    def __init__(self, driver: webdriver.Chrome, config: ScraperConfig) -> None:
        """Initialize base page."""
        self.driver = driver
        self.config = config
    
    def find_element(self, by: By, value: str, timeout: Optional[int] = None) -> Optional[webdriver.remote.webelement.WebElement]:
        """Find element with explicit wait."""
        wait_time = timeout or self.config.implicit_wait
        try:
            element = WebDriverWait(self.driver, wait_time).until(
                EC.presence_of_element_located((by, value))
            )
            return element
        except TimeoutException:
            return None
    
    def find_elements(self, by: By, value: str, timeout: Optional[int] = None) -> List[webdriver.remote.webelement.WebElement]:
        """Find multiple elements with explicit wait."""
        wait_time = timeout or self.config.implicit_wait
        try:
            WebDriverWait(self.driver, wait_time).until(
                EC.presence_of_element_located((by, value))
            )
            return self.driver.find_elements(by, value)
        except TimeoutException:
            return []
    
    def click_element(self, by: By, value: str) -> bool:
        """Click element with retry."""
        try:
            element = self.find_element(by, value)
            if element:
                element.click()
                return True
        except Exception as e:
            logger.debug(f"Error clicking element: {e}")
        return False
    
    def get_text_safe(self, element: Optional[webdriver.remote.webelement.WebElement]) -> str:
        """Get text from element safely."""
        if element:
            try:
                return element.text.strip()
            except Exception:
                return ""
        return ""
    
    def get_attribute_safe(self, element: Optional[webdriver.remote.webelement.WebElement], attribute: str) -> str:
        """Get attribute from element safely."""
        if element:
            try:
                return element.get_attribute(attribute) or ""
            except Exception:
                return ""
        return ""


# ============================================================================
# LOTTERY RESULTS PAGE
# ============================================================================

class LotteryResultsPage(BasePage):
    """Page object for PCSO lottery results page."""
    
    # Locators
    LOCATORS = {
        "results_container": (By.ID, "ctl00_ContentPlaceHolder1_updatePanelResults"),
        "results_table": (By.CLASS_NAME, "table-results"),
        "result_rows": (By.CSS_SELECTOR, "table tbody tr"),
        
        # Alternative selectors
        "lotto_result": (By.CLASS_NAME, "lotto-result"),
        "result_card": (By.CLASS_NAME, "result-card"),
        "draw_result": (By.CLASS_NAME, "draw-result"),
        
        # Date picker elements
        "date_picker": (By.ID, "ctl00_ContentPlaceHolder1_txtDrawDate"),
        "search_button": (By.ID, "ctl00_ContentPlaceHolder1_btnSearch"),
        
        # Game specific elements
        "game_header": (By.CLASS_NAME, "game-header"),
        "winning_numbers": (By.CLASS_NAME, "winning-numbers"),
        "jackpot_amount": (By.CLASS_NAME, "jackpot-amount"),
        "draw_date": (By.CLASS_NAME, "draw-date"),
        "draw_time": (By.CLASS_NAME, "draw-time"),
        
        # Error messages
        "error_message": (By.CLASS_NAME, "error-message"),
        "no_results": (By.CLASS_NAME, "no-results"),
    }
    
    # URL
    BASE_URL = "https://www.pcso.gov.ph/searchlottoresult.aspx"
    
    def __init__(self, driver: webdriver.Chrome, config: ScraperConfig) -> None:
        """Initialize the lottery results page."""
        super().__init__(driver, config)
        self.current_url = self.BASE_URL
    
    def load_page(self, date: Optional[datetime] = None) -> bool:
        """Load the lottery results page."""
        try:
            url = self.BASE_URL
            if date:
                date_str = date.strftime("%Y-%m-%d")
                url = f"{self.BASE_URL}?date={date_str}"
            
            logger.info(f"Loading page: {url}")
            self.driver.get(url)
            
            # Wait for page load
            WebDriverWait(self.driver, self.config.page_load_timeout).until(
                lambda d: d.execute_script("return document.readyState") == "complete"
            )
            time.sleep(1)
            
            self.current_url = self.driver.current_url
            logger.info(f"Page loaded: {self.current_url}")
            return True
            
        except WebDriverException as e:
            logger.error(f"Failed to load page: {e}")
            return False
    
    def search_by_date(self, date: datetime) -> bool:
        """Search lottery results by date."""
        try:
            # Find date input field
            date_input = self.find_element(*self.LOCATORS["date_picker"])
            if date_input:
                # Clear and enter date
                date_input.clear()
                date_input.send_keys(date.strftime("%m/%d/%Y"))
                
                # Click search button
                search_btn = self.find_element(*self.LOCATORS["search_button"])
                if search_btn:
                    search_btn.click()
                    
                    # Wait for results
                    time.sleep(2)
                    return True
                    
        except Exception as e:
            logger.debug(f"Error searching by date: {e}")
        
        return False
    
    def extract_results(self) -> List[LotteryResult]:
        """Extract all lottery results from the page."""
        results: List[LotteryResult] = []
        
        # Try table extraction first
        table_results = self._extract_from_tables()
        results.extend(table_results)
        
        # If no table results, try card extraction
        if not results:
            card_results = self._extract_from_cards()
            results.extend(card_results)
        
        # If still no results, try page source extraction
        if not results:
            source_results = self._extract_from_page_source()
            results.extend(source_results)
        
        # Deduplicate results
        results = self._deduplicate_results(results)
        
        logger.info(f"Extracted {len(results)} results from page")
        return results
    
    def _extract_from_tables(self) -> List[LotteryResult]:
        """Extract results from HTML tables."""
        results: List[LotteryResult] = []
        
        try:
            rows = self.find_elements(*self.LOCATORS["result_rows"])
            
            for row in rows:
                try:
                    cells = row.find_elements(By.TAG_NAME, "td")
                    if len(cells) >= 2:
                        result = self._parse_table_row(cells)
                        if result is not None:
                            results.append(result)
                except Exception as e:
                    logger.debug(f"Error parsing table row: {e}")
                    
        except Exception as e:
            logger.debug(f"Error extracting from tables: {e}")
        
        return results
    
    def _parse_table_row(self, cells: List[webdriver.remote.webelement.WebElement]) -> Optional[LotteryResult]:
        """Parse a table row into a LotteryResult."""
        try:
            cell_texts = [self.get_text_safe(cell) for cell in cells]
            full_text = " ".join(cell_texts)
            
            # Try to identify jackpot and winners columns from individual cells
            jackpot_value = ""
            winners_value = ""
            
            for i, cell_text in enumerate(cell_texts):
                cell_text = cell_text.strip()
                
                # Look for jackpot - check if cell contains currency-like numbers
                if not jackpot_value:
                    jackpot_match = re.search(r'(?:PHP|Php|₱)?\s*([\d,]+\.?\d*)', cell_text, re.I)
                    if jackpot_match:
                        value = jackpot_match.group(1).strip()
                        try:
                            num_val = float(value.replace(',', ''))
                            if num_val > 1000:
                                jackpot_value = f"PHP {value}"
                        except ValueError:
                            pass
                
                # Look for winners - check if cell contains a small integer
                if not winners_value:
                    winners_match = re.search(r'^(\d+)$', cell_text)
                    if winners_match:
                        value = winners_match.group(1)
                        try:
                            num_val = int(value)
                            if 0 <= num_val <= 100:
                                winners_value = value
                        except ValueError:
                            pass
            
            # Identify game from text
            for game in LOTTERY_GAMES:
                if game in full_text:
                    result = LotteryResult()
                    result.game_name = game
                    result.jackpot_prize = jackpot_value
                    result.winners = winners_value
                    
                    # Extract numbers
                    numbers = re.findall(r'\b(\d+)\b', full_text)
                    
                    if game in ["6/58", "6/49", "6/45", "6/42"]:
                        valid_nums = [n for n in numbers if 1 <= int(n) <= int(game.split("/")[1])]
                        if len(valid_nums) >= 6:
                            result.winning_numbers = " - ".join(valid_nums[:6])
                    elif game == "6D" and len(numbers) >= 6:
                        result.winning_numbers = " - ".join(numbers[:6])
                    elif game == "4D" and numbers:
                        result.winning_numbers = numbers[0] if len(numbers[0]) == 4 else ""
                    elif game == "3D" and numbers:
                        result.winning_numbers = numbers[0] if len(numbers[0]) == 3 else ""
                    elif game == "2D" and numbers:
                        result.winning_numbers = numbers[0] if len(numbers[0]) == 2 else ""
                    
                    # Extract date
                    date_match = re.search(r'(\d{1,2}/\d{1,2}/\d{4})', full_text)
                    if date_match:
                        result.draw_date = date_match.group(1)
                    
                    # Extract time
                    time_match = re.search(r'(\d{1,2}:\d{2}\s*(?:AM|PM))', full_text, re.I)
                    if time_match:
                        result.draw_time = time_match.group(1)
                    
                    # Set combination
                    result.combination = f"{game}: {result.winning_numbers}"
                    
                    if result.winning_numbers:
                        return result
                        
        except Exception as e:
            logger.debug(f"Error parsing table row: {e}")
        
        return None
    
    def _extract_from_cards(self) -> List[LotteryResult]:
        """Extract results from card elements."""
        results: List[LotteryResult] = []
        
        try:
            card_selectors = [
                self.LOCATORS["lotto_result"],
                self.LOCATORS["result_card"],
                self.LOCATORS["draw_result"],
            ]
            
            for selector in card_selectors:
                cards = self.find_elements(*selector)
                
                for card in cards:
                    card_text = self.get_text_safe(card)
                    
                    for game in LOTTERY_GAMES:
                        if game in card_text:
                            result = self._extract_game_from_text(card_text, game)
                            if result is not None:
                                results.append(result)
                                break
                            
        except Exception as e:
            logger.debug(f"Error extracting from cards: {e}")
        
        return results
    
    def _extract_game_from_text(self, text: str, game: str) -> Optional[LotteryResult]:
        """Extract game info from text."""
        result = LotteryResult()
        result.game_name = game
        
        try:
            # Extract numbers
            numbers = re.findall(r'\b(\d+)\b', text)
            
            if game in ["6/58", "6/49", "6/45", "6/42"]:
                valid_nums = [n for n in numbers if 1 <= int(n) <= int(game.split("/")[1])]
                if len(valid_nums) >= 6:
                    result.winning_numbers = " - ".join(valid_nums[:6])
            elif game == "6D" and len(numbers) >= 6:
                result.winning_numbers = " - ".join(numbers[:6])
            elif game == "4D" and numbers and len(numbers[0]) == 4:
                result.winning_numbers = numbers[0]
            elif game == "3D" and numbers and len(numbers[0]) == 3:
                result.winning_numbers = numbers[0]
            elif game == "2D" and numbers and len(numbers[0]) == 2:
                result.winning_numbers = numbers[0]
            
            # Extract jackpot - more flexible pattern
            jackpot_patterns = [
                r'(?:Jackpot|JACKPOT| jackpot|[Jj]ackpot ?[Pp]rize)\s*:?\s*(?:PHP|Php|₱)?\s*([\d,]+(?:\.\d{2})?)',
                r'(?:PHP|Php|₱)\s*([\d,]+(?:\.\d{2})?)',
                r'₱\s*([\d,]+)',
            ]
            for pattern in jackpot_patterns:
                jackpot_match = re.search(pattern, text, re.I)
                if jackpot_match:
                    result.jackpot_prize = f"PHP {jackpot_match.group(1)}"
                    break
            
            # Extract winners
            winners_patterns = [
                r'(\d+)\s*winner',
                r'(\d+)\s*winners',
                r'[Ww]inner[s]?:?\s*(\d+)',
            ]
            for pattern in winners_patterns:
                winners_match = re.search(pattern, text)
                if winners_match:
                    result.winners = winners_match.group(1)
                    break
            
            # Extract date
            date_match = re.search(r'(\d{1,2}/\d{1,2}/\d{4})', text)
            if date_match:
                result.draw_date = date_match.group(1)
            
            # Extract time
            time_match = re.search(r'(\d{1,2}:\d{2}\s*(?:AM|PM))', text, re.I)
            if time_match:
                result.draw_time = time_match.group(1)
            
            if result.winning_numbers:
                result.combination = f"{game}: {result.winning_numbers}"
                return result
                
        except Exception as e:
            logger.debug(f"Error extracting game from text: {e}")
        
        return None
    
    def _extract_from_page_source(self) -> List[LotteryResult]:
        """Extract results using regex from page source."""
        results: List[LotteryResult] = []
        
        try:
            page_source = self.driver.page_source
            
            # Extract Ultra Lotto 6/58
            results.extend(self._extract_game_regex(
                page_source,
                r'6/58\s+Lotto.*?(\d+).*?(\d+).*?(\d+).*?(\d+).*?(\d+).*?(\d+)',
                "6/58"
            ))
            
            # Extract Mega Lotto 6/49
            results.extend(self._extract_game_regex(
                page_source,
                r'6/49\s+Lotto.*?(\d+).*?(\d+).*?(\d+).*?(\d+).*?(\d+).*?(\d+)',
                "6/49"
            ))
            
            # Extract Super Lotto 6/45
            results.extend(self._extract_game_regex(
                page_source,
                r'6/45\s+Lotto.*?(\d+).*?(\d+).*?(\d+).*?(\d+).*?(\d+).*?(\d+)',
                "6/45"
            ))
            
            # Extract Lotto 6/42
            results.extend(self._extract_game_regex(
                page_source,
                r'6/42\s+Lotto.*?(\d+).*?(\d+).*?(\d+).*?(\d+).*?(\d+).*?(\d+)',
                "6/42"
            ))
            
            # Extract 6D Lotto
            results.extend(self._extract_game_regex(
                page_source,
                r'6D\s+Lotto.*?(\d{1})\s*(\d{1})\s*(\d{1})\s*(\d{1})\s*(\d{1})\s*(\d{1})',
                "6D"
            ))
            
            # Extract 4D Lotto
            results.extend(self._extract_game_regex(
                page_source,
                r'4D\s+Lotto.*?(\d{4})',
                "4D"
            ))
            
            # Extract 3D Lotto
            results.extend(self._extract_game_regex(
                page_source,
                r'3D\s+Lotto.*?(\d{3})',
                "3D"
            ))
            
            # Extract 2D Lotto
            results.extend(self._extract_game_regex(
                page_source,
                r'2D\s+Lotto.*?(\d{2})',
                "2D"
            ))
            
        except Exception as e:
            logger.debug(f"Error extracting from page source: {e}")
        
        return results
    
    def _extract_game_regex(self, text: str, pattern: str, game: str) -> List[LotteryResult]:
        """Extract game results using regex pattern."""
        results: List[LotteryResult] = []
        
        try:
            matches = re.finditer(pattern, text, re.IGNORECASE | re.DOTALL)
            
            for match in matches:
                result = LotteryResult()
                result.game_name = game
                groups = match.groups()
                
                if game in ["6/58", "6/49", "6/45", "6/42"]:
                    number_list = [str(g) for g in groups if g and g.isdigit()]
                    if len(number_list) >= 6:
                        result.winning_numbers = " - ".join(number_list[:6])
                elif game == "6D":
                    number_list = [str(g) for g in groups if g and g.isdigit()]
                    if len(number_list) >= 6:
                        result.winning_numbers = " - ".join(number_list[:6])
                elif game == "4D" and groups and groups[0]:
                    result.winning_numbers = groups[0]
                elif game == "3D" and groups and groups[0]:
                    result.winning_numbers = groups[0]
                elif game == "2D" and groups and groups[0]:
                    result.winning_numbers = groups[0]
                
                # Extract jackpot
                jackpot_patterns = [
                    r'(?:Jackpot|JACKPOT| jackpot|[Jj]ackpot ?[Pp]rize)\s*:?\s*(?:PHP|Php|₱)?\s*([\d,]+(?:\.\d{2})?)',
                    r'(?:PHP|Php|₱)\s*([\d,]+(?:\.\d{2})?)',
                ]
                for jp_pattern in jackpot_patterns:
                    jackpot_match = re.search(jp_pattern, match.group(0), re.I)
                    if jackpot_match:
                        result.jackpot_prize = f"PHP {jackpot_match.group(1)}"
                        break
                
                # Extract winners
                winners_patterns = [
                    r'(\d+)\s*winner',
                    r'(\d+)\s*winners',
                ]
                for w_pattern in winners_patterns:
                    winners_match = re.search(w_pattern, match.group(0))
                    if winners_match:
                        result.winners = winners_match.group(1)
                        break
                
                # Extract date
                date_match = re.search(r'(\d{1,2}/\d{1,2}/\d{4})', match.group(0))
                if date_match:
                    result.draw_date = date_match.group(1)
                
                if result.winning_numbers:
                    result.combination = f"{game}: {result.winning_numbers}"
                    results.append(result)
                    
        except Exception as e:
            logger.debug(f"Error extracting {game} with regex: {e}")
        
        return results
    
    def _deduplicate_results(self, results: List[LotteryResult]) -> List[LotteryResult]:
        """Remove duplicate results."""
        seen: set = set()
        unique: List[LotteryResult] = []
        
        for result in results:
            key = (result.game_name, result.winning_numbers)
            if key not in seen:
                seen.add(key)
                unique.append(result)
        
        return unique
    
    def has_error(self) -> bool:
        """Check if page has an error message."""
        error_element = self.find_element(*self.LOCATORS["error_message"])
        return error_element is not None
    
    def has_no_results(self) -> bool:
        """Check if there are no results."""
        no_results = self.find_element(*self.LOCATORS["no_results"])
        return no_results is not None


# ============================================================================
# WEBDRIVER MANAGER
# ============================================================================

class WebDriverManager:
    """Manages WebDriver lifecycle."""
    
    def __init__(self, config: ScraperConfig) -> None:
        """Initialize the WebDriver manager."""
        self.config = config
        self.driver: Optional[webdriver.Chrome] = None
    
    def create_driver(self) -> Optional[webdriver.Chrome]:
        """Create and configure Chrome WebDriver."""
        try:
            options = self._create_options()
            
            self.driver = webdriver.Chrome(options=options)
            self.driver.implicitly_wait(self.config.implicit_wait)
            self.driver.set_page_load_timeout(self.config.page_load_timeout)
            self.driver.set_script_timeout(self.config.script_timeout)
            
            logger.info("WebDriver initialized successfully")
            return self.driver
            
        except WebDriverException as e:
            logger.error(f"Failed to create WebDriver: {e}")
            return None
    
    def _create_options(self) -> Options:
        """Create Chrome options."""
        options = Options()
        
        if self.config.headless:
            options.add_argument("--headless=new")
        
        options.add_argument(f"--window-size={self.config.window_size}")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--disable-gpu")
        options.add_argument("--disable-extensions")
        options.add_argument("--disable-logging")
        options.add_argument("--log-level=3")
        
        # Set user agent
        user_agent = self.get_random_user_agent()
        options.add_argument(f"--user-agent={user_agent}")
        
        # Additional options for stability
        options.add_argument("--disable-blink-features=AutomationControlled")
        options.add_experimental_option("excludeSwitches", ["enable-automation"])
        options.add_experimental_option("useAutomationExtension", False)
        
        return options
    
    def get_random_user_agent(self) -> str:
        """Get a random user agent."""
        return random.choice(USER_AGENTS)
    
    def quit(self) -> None:
        """Quit the WebDriver."""
        if self.driver:
            self.driver.quit()
            logger.info("WebDriver closed")


# ============================================================================
# MAIN SCRAPER CLASS
# ============================================================================

class PCSOSeleniumScraper:
    """Main scraper class for PCSO lottery results."""
    
    def __init__(self, config: Optional[ScraperConfig] = None) -> None:
        """Initialize the scraper."""
        self.config = config or ScraperConfig()
        self.driver_manager = WebDriverManager(self.config)
        self.driver = None
        self.results_page = None
    
    def _calculate_delay(self, attempt: int) -> float:
        """Calculate retry delay with exponential backoff."""
        return self.config.retry_delay * (2 ** attempt)
    
    def initialize(self) -> bool:
        """Initialize the scraper."""
        try:
            self.driver = self.driver_manager.create_driver()
            if not self.driver:
                logger.error("Failed to initialize WebDriver")
                return False
            
            self.results_page = LotteryResultsPage(self.driver, self.config)
            return True
            
        except Exception as e:
            logger.error(f"Failed to initialize: {e}")
            return False
    
    def get_results_for_date(self, date: datetime) -> DailyResults:
        """Get lottery results for a specific date."""
        daily_result = DailyResults()
        daily_result.date = date.strftime("%Y-%m-%d")
        
        for attempt in range(self.config.max_retries):
            try:
                logger.info(f"Fetching results for {daily_result.date} (attempt {attempt + 1})")
                
                if self.results_page and self.results_page.load_page(date):
                    if self.results_page.has_error():
                        logger.warning("Page has error message")
                    
                    results = self.results_page.extract_results()
                    
                    if results:
                        daily_result.results = results
                        logger.info(f"Found {len(results)} results for {daily_result.date}")
                        return daily_result
                    
                    if self.results_page.search_by_date(date):
                        time.sleep(2)
                        results = self.results_page.extract_results()
                        if results:
                            daily_result.results = results
                            logger.info(f"Found {len(results)} results after search")
                            return daily_result
                
                if attempt < self.config.max_retries - 1:
                    delay = self._calculate_delay(attempt)
                    logger.info(f"Retrying in {delay:.2f} seconds...")
                    time.sleep(delay)
                    
            except Exception as e:
                logger.error(f"Error fetching results: {e}")
                if attempt < self.config.max_retries - 1:
                    time.sleep(self._calculate_delay(attempt))
        
        daily_result.error = f"No lottery results found for {daily_result.date}"
        logger.warning(daily_result.error)
        return daily_result
    
    def get_latest_results(self) -> Dict[str, DailyResults]:
        """Get latest lottery results."""
        results: Dict[str, DailyResults] = {}
        
        today = datetime.now()
        dates_to_fetch: List[datetime] = []
        
        if self.config.fetch_yesterday:
            dates_to_fetch.append(today - timedelta(days=1))
        if self.config.fetch_today:
            dates_to_fetch.append(today)
        
        for date in dates_to_fetch:
            date_str = date.strftime("%Y-%m-%d")
            logger.info(f"Fetching results for {date_str}")
            
            daily_result = self.get_results_for_date(date)
            results[date_str] = daily_result
            
            time.sleep(1)
        
        return results
    
    def get_results_for_date_range(self, start_date: datetime, end_date: datetime) -> Dict[str, DailyResults]:
        """Get lottery results for a date range."""
        results: Dict[str, DailyResults] = {}
        
        current_date = start_date
        while current_date <= end_date:
            date_str = current_date.strftime("%Y-%m-%d")
            logger.info(f"Fetching results for {date_str}")
            
            daily_result = self.get_results_for_date(current_date)
            results[date_str] = daily_result
            
            current_date += timedelta(days=1)
            time.sleep(1)
        
        logger.info(f"Fetched results for {len(results)} days")
        return results
    
    def close(self) -> None:
        """Close the WebDriver."""
        self.driver_manager.quit()


# ============================================================================
# OUTPUT FORMATTER
# ============================================================================

class OutputFormatter:
    """Formats lottery results for output."""
    
    @classmethod
    def set_emoji_enabled(cls, enabled: bool) -> None:
        """Enable or disable emoji output."""
        cls._emoji_enabled = enabled
    
    _emoji_enabled = True
    
    @staticmethod
    def format_results(results: Dict[str, DailyResults]) -> str:
        """Format all results for display."""
        lines = []
        
        for date_str, daily in sorted(results.items(), reverse=True):
            if daily.error:
                lines.append(f"\n=== {date_str} ===")
                lines.append(f"Error: {daily.error}")
                continue
            
            if not daily.results:
                continue
            
            lines.append(f"\n=== {date_str} ===")
            
            for i, result in enumerate(daily.results, 1):
                lines.append(OutputFormatter.format_single_result(result, i))
        
        return "\n".join(lines)
    
    @staticmethod
    def format_single_result(result: LotteryResult, index: int = 1) -> str:
        """Format a single lottery result."""
        lines = []
        
        # Game header
        icon = OutputFormatter._get_game_icon(result.game_name)
        lines.append(f"\n{index}. {icon} {result.game_name}")
        
        # Winning numbers
        lines.append(f"   Winning Numbers: {result.winning_numbers}")
        
        # Draw date/time
        if result.draw_date:
            lines.append(f"   Draw Date: {result.draw_date}")
        if result.draw_time:
            lines.append(f"   Draw Time: {result.draw_time}")
        
        # Jackpot
        if result.jackpot_prize:
            jackpot_icon = "[JACKPOT]" if not OutputFormatter._emoji_enabled else "💰"
            lines.append(f"   {jackpot_icon} Jackpot Prize: {result.jackpot_prize}")
        
        # Winners
        if result.winners:
            winner_icon = "[WINNER]" if not OutputFormatter._emoji_enabled else "👑"
            winner_text = "winner" if result.winners == "1" else "winners"
            lines.append(f"   {winner_icon} {result.winners} {winner_text}")
        
        return "\n".join(lines)
    
    @staticmethod
    def _get_game_icon(game_name: str) -> str:
        """Get emoji icon for game."""
        icons = {
            "6/58": "🎰",
            "6/49": "🎱",
            "6/45": "🎲",
            "6/42": "🎯",
            "6D": "🎳",
            "4D": "🎳",
            "3D": "🎳",
            "2D": "🎳",
        }
        return icons.get(game_name, "🎰")
    
    @staticmethod
    def save_to_json(results: Dict[str, DailyResults], filename: str = "pcso_selenium_results.json") -> bool:
        """Save results to JSON file."""
        try:
            output: Dict[str, Any] = {}
            
            for date_str, daily in results.items():
                output[date_str] = {
                    "date": daily.date,
                    "error": daily.error,
                    "results": [
                        {
                            "draw_date": r.draw_date,
                            "draw_time": r.draw_time,
                            "game_name": r.game_name,
                            "winning_numbers": r.winning_numbers,
                            "jackpot_prize": r.jackpot_prize,
                            "winners": r.winners,
                            "combination": r.combination,
                            "is_winner": r.is_winner,
                        }
                        for r in daily.results
                    ]
                }
            
            with open(filename, 'w', encoding='utf-8') as f:
                json.dump(output, f, indent=2, ensure_ascii=False)
            
            logger.info(f"Results saved to {filename}")
            return True
            
        except Exception as e:
            logger.error(f"Error saving results: {e}")
            return False


def setup_console_encoding() -> None:
    """Setup console encoding for Windows."""
    if sys.platform == "win32":
        try:
            sys.stdout.reconfigure(encoding='utf-8')
        except Exception:
            pass


def main() -> None:
    """Main entry point."""
    setup_console_encoding()
    
    print("PCSO Lottery Results Scraper")
    print("=" * 40)
    
    # Configure scraper
    config = ScraperConfig()
    config.headless = True
    config.fetch_yesterday = True
    config.fetch_today = True
    
    # Create scraper
    scraper = PCSOSeleniumScraper(config)
    
    # Initialize
    if not scraper.initialize():
        logger.error("Failed to initialize scraper")
        return
    
    try:
        # Get latest results
        results = scraper.get_latest_results()
        
        # Format and print results
        formatted = OutputFormatter.format_results(results)
        print(formatted)
        
        # Save to JSON
        OutputFormatter.save_to_json(results)
        
    finally:
        scraper.close()


if __name__ == "__main__":
    main()
