#!/usr/bin/env python3
"""
PCSO Lottery Results Web Scraper

A specialized web scraper for extracting Philippine Charity Sweepstakes Office
(PCSO) lottery draw results from the official PCSO website.

Features:
- Extracts latest lottery draw results for multiple game types
- Supports games: 6/58, 6/49, 6/45, 6/42, 6D, 4D, 3D, 2D
- Automatically retrieves results for yesterday and today
- Handles dynamic content loading with proper HTML parsing
- Retry logic with exponential backoff for failed requests
- User-agent headers to avoid being blocked
- Comprehensive error handling
- Clean, formatted console output

Author: Web Scraper
Version: 1.0.0
"""

import json
import time
import logging
import re
import sys
import random
from typing import Dict, List, Optional, Any, Tuple
from datetime import datetime, timedelta
from dataclasses import dataclass, field
from urllib.parse import urljoin

# Import dependencies
import requests
from bs4 import BeautifulSoup, Tag

# ============================================================================
# CONFIGURATION
# ============================================================================

# PCSO Lottery Results URL
PCSO_BASE_URL = "https://www.pcso.gov.ph"
PCSO_SEARCH_URL = "https://www.pcso.gov.ph/searchlottoresult.aspx"

# User agent to mimic a real browser
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

# Request configuration
REQUEST_TIMEOUT = 30
MAX_RETRIES = 3
RETRY_DELAY = 2.0

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
        logging.FileHandler('pcso_scraper.log', encoding='utf-8')
    ]
)
logger = logging.getLogger(__name__)


# ============================================================================
# DATA STRUCTURES
# ============================================================================

@dataclass
class LotteryResult:
    """Represents a single lottery draw result."""
    draw_date: str = ""
    draw_time: str = ""
    game_name: str = ""
    winning_numbers: str = ""
    jackpot_prize: str = ""
    winners: str = ""
    combination: str = ""  # Full combination string
    is_winner: bool = False


@dataclass
class DailyResults:
    """Represents lottery results for a single day."""
    date: str = ""
    results: List[LotteryResult] = field(default_factory=list)
    error: Optional[str] = None


# ============================================================================
# REQUEST HANDLER WITH RETRY LOGIC
# ============================================================================

class PCSORequestHandler:
    """
    Handles HTTP requests to PCSO website with retry logic.
    
    Implements exponential backoff for failed requests and manages
    cookies/sessions required by the PCSO website.
    """
    
    def __init__(self) -> None:
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": DEFAULT_USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.5",
            "Accept-Encoding": "gzip, deflate, br",
            "Connection": "keep-alive",
            "Upgrade-Insecure-Requests": "1",
            "Cache-Control": "max-age=0",
            "Referer": PCSO_BASE_URL,
        })
        
    def _calculate_delay(self, attempt: int) -> float:
        """Calculate delay with exponential backoff and jitter."""
        base_delay = RETRY_DELAY * (2 ** attempt)
        jitter = random.uniform(0, 1)
        return base_delay + jitter
    
    def fetch(self, url: str) -> Optional[requests.Response]:
        """
        Fetch a URL with retry logic and error handling.
        
        Args:
            url: The URL to fetch
            
        Returns:
            Response object if successful, None otherwise
        """
        last_exception: Optional[Exception] = None
        
        for attempt in range(MAX_RETRIES):
            try:
                logger.info(f"Fetching {url} (attempt {attempt + 1}/{MAX_RETRIES})")
                
                response = self.session.get(
                    url,
                    timeout=REQUEST_TIMEOUT,
                    allow_redirects=True,
                    verify=True
                )
                
                # Check for HTTP errors
                response.raise_for_status()
                
                logger.info(f"Successfully fetched {url} (Status: {response.status_code})")
                return response
                
            except requests.exceptions.Timeout as e:
                last_exception = e
                logger.warning(f"Timeout fetching {url}: {e}")
                
            except requests.exceptions.ConnectionError as e:
                last_exception = e
                logger.warning(f"Connection error for {url}: {e}")
                
            except requests.exceptions.HTTPError as e:
                response = e.response
                if response is not None and response.status_code == 429:
                    last_exception = e
                    logger.warning(f"Rate limited (429) for {url}")
                elif response is not None and 400 <= response.status_code < 500:
                    logger.error(f"Client error {response.status_code} for {url}, not retrying")
                    return None
                else:
                    last_exception = e
                    if response is not None:
                        logger.warning(f"HTTP error {response.status_code} for {url}")
                    else:
                        logger.warning(f"HTTP error for {url}")
            
            except requests.exceptions.RequestException as e:
                last_exception = e
                logger.warning(f"Request error for {url}: {e}")
            
            # Wait before retrying with exponential backoff
            if attempt < MAX_RETRIES - 1:
                delay = self._calculate_delay(attempt)
                logger.info(f"Waiting {delay:.2f} seconds before retry...")
                time.sleep(delay)
        
        logger.error(f"Failed to fetch {url} after {MAX_RETRIES} attempts: {last_exception}")
        return None
    
    def get_cookies(self) -> Dict[str, str]:
        """Get current session cookies."""
        return {cookie.name: cookie.value for cookie in self.session.cookies}


# ============================================================================
# HTML PARSER FOR PCSO PAGES
# ============================================================================

class PCSOLotteryParser:
    """
    Parses HTML content from PCSO website to extract lottery results.
    
    Handles the specific HTML structure of the PCSO lottery results page
    and extracts relevant lottery information.
    """
    
    def __init__(self) -> None:
        self.soup: BeautifulSoup = BeautifulSoup("", "html.parser")
        
    def parse(self, html_content: str) -> BeautifulSoup:
        """
        Parse HTML content into a BeautifulSoup object.
        
        Args:
            html_content: Raw HTML string
            
        Returns:
            BeautifulSoup object for further parsing
        """
        if not html_content:
            self.soup = BeautifulSoup("", "html.parser")
            return self.soup
        
        try:
            self.soup = BeautifulSoup(html_content, "html.parser")
            return self.soup
        except Exception as e:
            logger.warning(f"Error parsing HTML: {e}")
            self.soup = BeautifulSoup("", "html.parser")
            return self.soup
    
    def extract_results_from_page(self, html_content: str) -> List[LotteryResult]:
        """
        Extract lottery results from the HTML page.
        
        This method looks for various patterns in the PCSO page structure
        to extract lottery draw information.
        
        Args:
            html_content: Raw HTML string from PCSO website
            
        Returns:
            List of LotteryResult objects
        """
        results: List[LotteryResult] = []
        
        # Parse the HTML first
        self.parse(html_content)
        
        # Method 1: Look for result tables
        table_results = self._extract_from_tables()
        results.extend(table_results)
        
        # Method 2: Look for result cards/panels
        if not results:
            card_results = self._extract_from_cards()
            results.extend(card_results)
        
        # Method 3: Look for list items
        if not results:
            list_results = self._extract_from_lists()
            results.extend(list_results)
        
        # Method 4: Look for specific div structures
        if not results:
            div_results = self._extract_from_divs()
            results.extend(div_results)
        
        # Method 5: Search for specific game patterns in entire content
        if not results:
            pattern_results = self._extract_from_patterns(str(self.soup))
            results.extend(pattern_results)
        
        # Deduplicate results
        results = self._deduplicate_results(results)
        
        return results
    
    def _extract_from_tables(self) -> List[LotteryResult]:
        """Extract results from HTML tables."""
        results: List[LotteryResult] = []
        
        tables = self.soup.find_all("table")
        
        for table in tables:
            rows = table.find_all("tr")
            
            for row in rows:
                cells = row.find_all(["td", "th"])
                if len(cells) >= 2:
                    # Try to extract lottery info from table row
                    result = self._parse_table_row(cells)
                    if result is not None:
                        results.append(result)
        
        return results
    
    def _parse_table_row(self, cells: List[Tag]) -> Optional[LotteryResult]:
        """Parse a table row to extract lottery result."""
        try:
            # Get all text from cells
            cell_texts = [cell.get_text(strip=True) for cell in cells]
            full_text = " ".join(cell_texts)
            
            # Check if this looks like a lottery result
            game_result = self._identify_game_from_text(full_text)
            if game_result is not None:
                return game_result
                
        except Exception as e:
            logger.debug(f"Error parsing table row: {e}")
        
        return None
    
    def _extract_from_cards(self) -> List[LotteryResult]:
        """Extract results from card/panel structures."""
        results: List[LotteryResult] = []
        
        # Look for cards with lottery result classes
        cards = self.soup.find_all(["div", "section"], class_=re.compile(r'(result|card|lotto|draw)', re.I))
        
        for card in cards:
            card_text = card.get_text(strip=True)
            result = self._identify_game_from_text(card_text)
            if result is not None:
                results.append(result)
        
        return results
    
    def _extract_from_lists(self) -> List[LotteryResult]:
        """Extract results from list items."""
        results: List[LotteryResult] = []
        
        list_items = self.soup.find_all(["li", "article"])
        
        for item in list_items:
            item_text = item.get_text(strip=True)
            result = self._identify_game_from_text(item_text)
            if result is not None:
                results.append(result)
        
        return results
    
    def _extract_from_divs(self) -> List[LotteryResult]:
        """Extract results from div elements."""
        results: List[LotteryResult] = []
        
        divs = self.soup.find_all("div")
        
        for div in divs:
            div_class = div.get("class", [])
            div_id = div.get("id", "")
            
            # Skip navigation and footer elements
            class_id_str = " ".join(div_class) + " " + div_id
            if any(x in class_id_str.lower() for x in ["nav", "footer", "header", "menu"]):
                continue
            
            div_text = div.get_text(strip=True)
            
            # Only process divs with substantial lottery content
            if len(div_text) > 20 and any(game in div_text for game in LOTTERY_GAMES):
                result = self._identify_game_from_text(div_text)
                if result is not None:
                    results.append(result)
        
        return results
    
    def _extract_from_patterns(self, content: str) -> List[LotteryResult]:
        """
        Extract lottery results using regex patterns.
        
        This is a fallback method that searches for known lottery
        patterns in the raw HTML content.
        """
        results: List[LotteryResult] = []
        
        # Pattern for Ultra Lotto 6/58
        results.extend(self._extract_game_pattern(content, r'Ultra Lotto 6/58.*?(\d{1,2})[-/\s](\d{1,2})[-/\s](\d{1,2})[-/\s](\d{1,2})[-/\s](\d{1,2})[-/\s](\d{1,2})', "6/58"))
        
        # Pattern for Grand Lotto 6/55 (if present)
        results.extend(self._extract_game_pattern(content, r'Grand Lotto 6/55.*?(\d{1,2})[-/\s](\d{1,2})[-/\s](\d{1,2})[-/\s](\d{1,2})[-/\s](\d{1,2})[-/\s](\d{1,2})', "6/55"))
        
        # Pattern for Mega Lotto 6/49
        results.extend(self._extract_game_pattern(content, r'Mega Lotto 6/49.*?(\d{1,2})[-/\s](\d{1,2})[-/\s](\d{1,2})[-/\s](\d{1,2})[-/\s](\d{1,2})[-/\s](\d{1,2})', "6/49"))
        
        # Pattern for Super Lotto 6/49 (alternative name)
        results.extend(self._extract_game_pattern(content, r'Super Lotto 6/49.*?(\d{1,2})[-/\s](\d{1,2})[-/\s](\d{1,2})[-/\s](\d{1,2})[-/\s](\d{1,2})[-/\s](\d{1,2})', "6/49"))
        
        # Pattern for Lotto 6/45
        results.extend(self._extract_game_pattern(content, r'Lotto 6/45.*?(\d{1,2})[-/\s](\d{1,2})[-/\s](\d{1,2})[-/\s](\d{1,2})[-/\s](\d{1,2})[-/\s](\d{1,2})', "6/45"))
        
        # Pattern for Power Lotto 6/45 (alternative name)
        results.extend(self._extract_game_pattern(content, r'Power Lotto 6/45.*?(\d{1,2})[-/\s](\d{1,2})[-/\s](\d{1,2})[-/\s](\d{1,2})[-/\s](\d{1,2})[-/\s](\d{1,2})', "6/45"))
        
        # Pattern for Lotto 6/42
        results.extend(self._extract_game_pattern(content, r'Lotto 6/42.*?(\d{1,2})[-/\s](\d{1,2})[-/\s](\d{1,2})[-/\s](\d{1,2})[-/\s](\d{1,2})[-/\s](\d{1,2})', "6/42"))
        
        # Pattern for 6D Lotto
        results.extend(self._extract_game_pattern(content, r'6D Lotto.*?(\d)[-/\s](\d)[-/\s](\d)[-/\s](\d)[-/\s](\d)[-/\s](\d)', "6D"))
        
        # Pattern for 4D Lotto
        results.extend(self._extract_game_pattern(content, r'4D Lotto.*?(\d{4})', "4D"))
        
        # Pattern for 3D Lotto
        results.extend(self._extract_game_pattern(content, r'3D Lotto.*?(?:PM|AM)?.*?(\d{3})', "3D"))
        
        # Pattern for 2D Lotto
        results.extend(self._extract_game_pattern(content, r'2D Lotto.*?(?:PM|AM)?.*?(\d{2})', "2D"))
        
        return results
    
    def _extract_game_pattern(self, content: str, pattern: str, game_name: str) -> List[LotteryResult]:
        """Extract a specific game using regex pattern."""
        results: List[LotteryResult] = []
        
        try:
            matches = re.finditer(pattern, content, re.IGNORECASE | re.DOTALL)
            
            for match in matches:
                result = LotteryResult()
                result.game_name = game_name
                result.combination = match.group(0)
                
                # Extract numbers based on game type
                groups: Tuple[str, ...] = match.groups()
                
                if game_name in ["6/58", "6/49", "6/45", "6/42", "6/55"]:
                    # Convert tuple to list and filter valid numbers
                    number_list: List[str] = [str(g) for g in groups if g and g.isdigit()]
                    if len(number_list) >= 6:
                        numbers = number_list[:6]
                        result.winning_numbers = " - ".join(numbers)
                        
                elif game_name == "6D":
                    number_list = [str(g) for g in groups if g and g.isdigit()]
                    if len(number_list) >= 6:
                        numbers = number_list[:6]
                        result.winning_numbers = " - ".join(numbers)
                        
                elif game_name == "4D":
                    if groups and groups[0]:
                        result.winning_numbers = groups[0]
                        
                elif game_name == "3D":
                    if groups and groups[0]:
                        result.winning_numbers = groups[0]
                        
                elif game_name == "2D":
                    if groups and groups[0]:
                        result.winning_numbers = groups[0]
                
                # Extract jackpot prize if present
                jackpot_match = re.search(r'PHP\s*([\d,]+(?:\.\d{2})?)|Php\s*([\d,]+(?:\.\d{2})?)|₱\s*([\d,]+(?:\.\d{2})?)', match.group(0), re.I)
                if jackpot_match:
                    jackpot = jackpot_match.group(1) or jackpot_match.group(2) or jackpot_match.group(3)
                    result.jackpot_prize = f"PHP {jackpot}" if jackpot else ""
                
                # Extract date if present
                date_match = re.search(r'(\d{1,2})[-/\s](\d{1,2})[-/\s](\d{4})', match.group(0))
                if date_match:
                    result.draw_date = f"{date_match.group(1)}/{date_match.group(2)}/{date_match.group(3)}"
                
                if result.winning_numbers:
                    results.append(result)
                    
        except Exception as e:
            logger.debug(f"Error extracting pattern for {game_name}: {e}")
        
        return results
    
    def _identify_game_from_text(self, text: str) -> Optional[LotteryResult]:
        """
        Identify which lottery game the text refers to and extract result.
        
        Args:
            text: Text content to analyze
            
        Returns:
            LotteryResult if game identified, None otherwise
        """
        # Check each lottery game
        for game in LOTTERY_GAMES:
            if game in text:
                result = self._extract_game_info(text, game)
                if result is not None:
                    return result
        
        return None
    
    def _extract_game_info(self, text: str, game: str) -> Optional[LotteryResult]:
        """Extract detailed info for a specific game."""
        result = LotteryResult()
        result.game_name = game
        
        try:
            # Extract winning numbers based on game type
            if game in ["6/58", "6/49", "6/45", "6/42", "6/55"]:
                # Extract 6 numbers
                numbers = re.findall(r'\b(\d{1,2})\b', text)
                valid_numbers = [n for n in numbers if n and int(n) <= 58]  # Filter valid lottery numbers
                if len(valid_numbers) >= 6:
                    result.winning_numbers = " - ".join(valid_numbers[:6])
                    
            elif game == "6D":
                numbers = re.findall(r'\b(\d)\b', text)
                if len(numbers) >= 6:
                    result.winning_numbers = " - ".join(numbers[:6])
                    
            elif game == "4D":
                match = re.search(r'\b(\d{4})\b', text)
                if match:
                    result.winning_numbers = match.group(1)
                    
            elif game == "3D":
                match = re.search(r'\b(\d{3})\b', text)
                if match:
                    result.winning_numbers = match.group(1)
                    
            elif game == "2D":
                match = re.search(r'\b(\d{2})\b', text)
                if match:
                    result.winning_numbers = match.group(1)
            
            # Extract jackpot prize
            jackpot_patterns = [
                r'PHP\s*([\d,]+(?:\.\d{2})?)',
                r'Php\s*([\d,]+(?:\.\d{2})?)',
                r'₱\s*([\d,]+(?:\.\d{2})?)',
                r'Jackpot[:\s]*PHP\s*([\d,]+)',
                r'Php\s*([\d,]+)',
            ]
            
            for pattern in jackpot_patterns:
                match = re.search(pattern, text, re.I)
                if match:
                    result.jackpot_prize = f"PHP {match.group(1)}"
                    break
            
            # Extract date
            date_patterns = [
                r'(\d{1,2}/\d{1,2}/\d{4})',
                r'(\w+\s+\d{1,2},\s+\d{4})',
                r'(\d{4}-\d{2}-\d{2})',
            ]
            
            for pattern in date_patterns:
                match = re.search(pattern, text)
                if match:
                    result.draw_date = match.group(1)
                    break
            
            # Extract draw time
            time_match = re.search(r'(\d{1,2}:\d{2}\s*(?:AM|PM))', text, re.I)
            if time_match:
                result.draw_time = time_match.group(1)
            
            # Extract winner info
            winner_match = re.search(r'(\d+)\s*(?:winner|winners)', text, re.I)
            if winner_match:
                result.winners = winner_match.group(1)
                result.is_winner = True
            
            # Set combination string
            result.combination = f"{game}: {result.winning_numbers}"
            
            # Only return if we have winning numbers
            if result.winning_numbers:
                return result
                
        except Exception as e:
            logger.debug(f"Error extracting game info for {game}: {e}")
        
        return None
    
    def _deduplicate_results(self, results: List[LotteryResult]) -> List[LotteryResult]:
        """Remove duplicate lottery results."""
        seen: set = set()
        unique_results: List[LotteryResult] = []
        
        for result in results:
            # Create unique key based on game and winning numbers
            key = (result.game_name, result.winning_numbers)
            
            if key not in seen:
                seen.add(key)
                unique_results.append(result)
        
        return unique_results


# ============================================================================
# PCSO LOTTERY SCRAPER
# ============================================================================

class PCSOLotteryScraper:
    """
    Main scraper class for PCSO lottery results.
    
    Coordinates the fetching and parsing of lottery results
    from the PCSO website.
    """
    
    def __init__(self) -> None:
        self.request_handler = PCSORequestHandler()
        self.parser = PCSOLotteryParser()
        
    def get_results_for_date_range(self, start_date: datetime, end_date: datetime) -> Dict[str, DailyResults]:
        """
        Get lottery results for a date range.
        
        Args:
            start_date: Start date for results
            end_date: End date for results
            
        Returns:
            Dictionary with dates as keys and DailyResults as values
        """
        results: Dict[str, DailyResults] = {}
        
        # Calculate number of days to fetch
        current_date = start_date
        while current_date <= end_date:
            date_str = current_date.strftime("%Y-%m-%d")
            logger.info(f"Fetching results for {date_str}")
            
            daily_result = self._fetch_results_for_date(current_date)
            results[date_str] = daily_result
            
            # Small delay between requests
            time.sleep(1)
            
            # Move to next day
            current_date += timedelta(days=1)
        
        return results
    
    def _fetch_results_for_date(self, date: datetime) -> DailyResults:
        """
        Fetch lottery results for a specific date.
        
        Args:
            date: Date to fetch results for
            
        Returns:
            DailyResults object
        """
        daily_result = DailyResults()
        daily_result.date = date.strftime("%Y-%m-%d")
        
        try:
            # Try multiple URL patterns to get results
            urls_to_try = [
                # Direct search URL with date parameters
                f"{PCSO_SEARCH_URL}?date={date.strftime('%Y-%m-%d')}",
                f"{PCSO_SEARCH_URL}?drawdate={date.strftime('%Y%m%d')}",
                # Main results page
                PCSO_SEARCH_URL,
                # Alternative URLs that might have results
                f"{PCSO_BASE_URL}/lotto-result.aspx",
                f"{PCSO_BASE_URL}/lotto-results.aspx",
            ]
            
            for url in urls_to_try:
                response = self.request_handler.fetch(url)
                
                if response is not None and response.status_code == 200:
                    results = self.parser.extract_results_from_page(response.text)
                    
                    if results:
                        # Filter results for the specific date
                        filtered_results = self._filter_results_by_date(results, date)
                        daily_result.results = filtered_results if filtered_results else results
                        logger.info(f"Found {len(daily_result.results)} results for {daily_result.date}")
                        return daily_result
            
            # If no results found
            daily_result.error = f"No lottery results found for {daily_result.date}"
            logger.warning(daily_result.error)
            
        except Exception as e:
            daily_result.error = f"Error fetching results: {str(e)}"
            logger.error(daily_result.error)
        
        return daily_result
    
    def _filter_results_by_date(self, results: List[LotteryResult], target_date: datetime) -> List[LotteryResult]:
        """Filter results to match the target date."""
        filtered: List[LotteryResult] = []
        
        for result in results:
            # If result has a date, check if it matches
            if result.draw_date:
                try:
                    # Try to parse various date formats
                    date_formats = ["%m/%d/%Y", "%Y-%m-%d", "%B %d %Y", "%d %B %Y"]
                    parsed = False
                    for fmt in date_formats:
                        try:
                            result_date = datetime.strptime(result.draw_date.replace(",", ""), fmt.replace(",", ""))
                            if result_date.date() == target_date.date():
                                filtered.append(result)
                                parsed = True
                                break
                        except ValueError:
                            continue
                    if not parsed:
                        # If date parsing fails, include the result anyway
                        filtered.append(result)
                except Exception:
                    # If date parsing fails, include the result
                    filtered.append(result)
            else:
                # If no date specified, include the result
                filtered.append(result)
        
        return filtered
    
    def get_latest_results(self) -> Dict[str, DailyResults]:
        """
        Get the latest lottery results for yesterday and today.
        
        Returns:
            Dictionary with dates as keys and DailyResults as values
        """
        today = datetime.now()
        yesterday = today - timedelta(days=1)
        
        logger.info(f"Fetching lottery results for {yesterday.strftime('%Y-%m-%d')} and {today.strftime('%Y-%m-%d')}")
        
        return self.get_results_for_date_range(yesterday, today)


# ============================================================================
# OUTPUT FORMATTER
# ============================================================================

class OutputFormatter:
    """
    Formats lottery results for console output.
    
    Provides clean, readable formatting for displaying
    lottery results in the terminal.
    """
    
    # Class variable to control emoji usage
    use_emoji: bool = True
    
    @classmethod
    def set_emoji_enabled(cls, enabled: bool) -> None:
        """Enable or disable emoji in output."""
        cls.use_emoji = enabled
    
    @staticmethod
    def format_results(results: Dict[str, DailyResults]) -> str:
        """
        Format all results for display.
        
        Args:
            results: Dictionary of daily results
            
        Returns:
            Formatted string
        """
        output_lines: List[str] = []
        
        # Header
        output_lines.append("=" * 80)
        output_lines.append("PCSO LOTTERY RESULTS")
        output_lines.append("=" * 80)
        output_lines.append("")
        
        # Sort dates
        sorted_dates = sorted(results.keys(), reverse=True)
        
        for date_str in sorted_dates:
            daily = results[date_str]
            
            # Format date nicely
            try:
                date_obj = datetime.strptime(date_str, "%Y-%m-%d")
                formatted_date = date_obj.strftime("%B %d, %Y")
                
                # Determine if it's today or yesterday
                today = datetime.now().date()
                if date_obj.date() == today:
                    day_label = "TODAY"
                elif date_obj.date() == (today - timedelta(days=1)):
                    day_label = "YESTERDAY"
                else:
                    day_label = date_obj.strftime("%A").upper()
                    
            except Exception:
                formatted_date = date_str
                day_label = date_str
            
            # Section header
            output_lines.append("-" * 80)
            date_icon = "[DATE]" if not OutputFormatter.use_emoji else "📅"
            output_lines.append(f"{date_icon} {formatted_date} ({day_label})")
            output_lines.append("-" * 80)
            
            if daily.error:
                warn_icon = "[WARNING]" if not OutputFormatter.use_emoji else "⚠️"
                output_lines.append(f"{warn_icon}  {daily.error}")
                output_lines.append("")
                continue
            
            if not daily.results:
                output_lines.append("No lottery results available for this date.")
                output_lines.append("")
                continue
            
            # Display each result
            for i, result in enumerate(daily.results, 1):
                output_lines.append(OutputFormatter.format_single_result(result, i))
                output_lines.append("")
            
            output_lines.append("")
        
        return "\n".join(output_lines)
    
    @staticmethod
    def format_single_result(result: LotteryResult, index: int = 1) -> str:
        """
        Format a single lottery result.
        
        Args:
            result: LotteryResult object
            index: Optional index number
            
        Returns:
            Formatted string
        """
        lines: List[str] = []
        use_emoji = OutputFormatter.use_emoji
        
        # Game name with icon
        game_icon = OutputFormatter._get_game_icon(result.game_name) if use_emoji else f"[{result.game_name}]"
        game_header = f"{game_icon} {result.game_name}"
        
        if index > 1:
            game_header = f"  {index}. {result.game_name}"
        
        lines.append(game_header)
        lines.append("-" * 40)
        
        # Draw time
        if result.draw_time:
            time_icon = "[TIME]" if not use_emoji else "🕐"
            lines.append(f"  {time_icon} Draw Time: {result.draw_time}")
        
        # Winning numbers
        if result.winning_numbers:
            nums_icon = "[NUMS]" if not use_emoji else "🎯"
            lines.append(f"  {nums_icon} Winning Numbers: {result.winning_numbers}")
        
        # Jackpot prize
        if result.jackpot_prize:
            jackpot_icon = "[JACKPOT]" if not use_emoji else "💰"
            lines.append(f"  {jackpot_icon} Jackpot Prize: {result.jackpot_prize}")
        
        # Winners
        if result.winners:
            winner_icon = "[WINNER]" if not use_emoji else "👑"
            winner_text = "winner" if result.winners == "1" else "winners"
            lines.append(f"  {winner_icon} {result.winners} {winner_text}")
        
        # Combination (if different from winning numbers)
        if result.combination and result.combination != f"{result.game_name}: {result.winning_numbers}":
            detail_icon = "[INFO]" if not use_emoji else "📋"
            lines.append(f"  {detail_icon} Details: {result.combination}")
        
        return "\n".join(lines)
    
    @staticmethod
    def _get_game_icon(game_name: str) -> str:
        """Get emoji icon for game type."""
        icons = {
            "6/58": "🟣",      # Ultra Lotto
            "6/55": "🟣",      # Grand Lotto
            "6/49": "🔴",      # Mega Lotto
            "6/45": "🟠",      # Lotto
            "6/42": "🟡",      # Lotto
            "6D": "🟢",        # 6D
            "4D": "🔵",        # 4D
            "3D": "🔷",        # 3D
            "2D": "🔶",        # 2D
        }
        return icons.get(game_name, "🎰")
    
    @staticmethod
    def save_to_json(results: Dict[str, DailyResults], filename: str = "pcso_results.json") -> bool:
        """
        Save results to JSON file.
        
        Args:
            results: Results dictionary
            filename: Output filename
            
        Returns:
            True if successful, False otherwise
        """
        try:
            # Convert to serializable format
            serializable: Dict[str, Any] = {}
            for date_str, daily in results.items():
                serializable[date_str] = {
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
                json.dump(serializable, f, indent=2, ensure_ascii=False)
            
            logger.info(f"Results saved to {filename}")
            return True
            
        except Exception as e:
            logger.error(f"Error saving to JSON: {e}")
            return False


# ============================================================================
# MAIN EXECUTION
# ============================================================================

def setup_console_encoding() -> None:
    """Setup console encoding for proper Unicode output on Windows."""
    import sys
    # Try to set UTF-8 encoding for Windows console
    if sys.platform == "win32":
        try:
            sys.stdout.reconfigure(encoding='utf-8')
        except Exception:
            # If reconfigure fails, use alternative approach
            import io
            sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
        try:
            sys.stderr.reconfigure(encoding='utf-8')
        except Exception:
            pass


def main() -> None:
    """Main entry point for the PCSO Lottery Scraper."""
    
    # Setup console encoding for Windows
    setup_console_encoding()
    
    print("\n" + "=" * 80)
    print("PCSO LOTTERY RESULTS WEB SCRAPER")
    print("=" * 80)
    print()
    
    try:
        # Initialize scraper
        scraper = PCSOLotteryScraper()
        
        # Get results for yesterday and today
        print("Fetching lottery results...")
        print()
        
        results = scraper.get_latest_results()
        
        # Format and display results
        formatter = OutputFormatter()
        output = formatter.format_results(results)
        print(output)
        
        # Save to JSON
        formatter.save_to_json(results)
        
        # Summary
        total_results = sum(len(dr.results) for dr in results.values())
        print("=" * 80)
        print(f"Total results found: {total_results}")
        print("=" * 80)
        
    except KeyboardInterrupt:
        print("\n\nScraping interrupted by user.")
        sys.exit(0)
        
    except Exception as e:
        print(f"\n\nError: {e}")
        logger.exception("Unhandled exception in main")
        sys.exit(1)


if __name__ == "__main__":
    main()
