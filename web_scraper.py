#!/usr/bin/env python3
"""
Robust Web Scraper Module

A modular web scraper with:
- robots.txt compliance checking
- Realistic user-agent headers
- Retry logic with exponential backoff
- Support for both static and dynamic content
- Clean data extraction using BeautifulSoup
- Export to JSON or CSV format
- Comprehensive error handling

Author: Web Scraper
Version: 1.0.0
"""

import json
import csv
import time
import logging
import urllib.parse
import re
from typing import Dict, List, Optional, Any, Callable, Union
from dataclasses import dataclass, field, asdict
from pathlib import Path
from urllib.robotparser import RobotFileParser
import socket
import random

# Import dependencies - type: ignore comments suppress missing package errors
# These packages must be installed: pip install requests beautifulsoup4 lxml
import requests  # type: ignore
from bs4 import BeautifulSoup  # type: ignore

# Configure logging for better debugging and monitoring
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('scraper.log', encoding='utf-8')
    ]
)
logger = logging.getLogger(__name__)


# ============================================================================
# CONFIGURATION AND DATA STRUCTURES
# ============================================================================

@dataclass
class ScrapingConfig:
    """Configuration for the web scraper."""
    user_agent: str = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    request_timeout: int = 30
    max_retries: int = 3
    retry_delay: float = 1.0
    max_redirects: int = 10
    verify_ssl: bool = True
    respect_robots_txt: bool = True
    delay_between_requests: float = 1.0
    
    # For dynamic content (Selenium)
    use_selenium: bool = False
    selenium_wait_time: int = 10


@dataclass
class ScrapedData:
    """Data structure to hold scraped information."""
    url: str
    title: str = ""
    text_content: str = ""
    links: List[Dict[str, str]] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None
    timestamp: str = ""


# ============================================================================
# ROBOTS.TXT CHECKER
# ============================================================================

class RobotsTxtChecker:
    """
    Handles robots.txt compliance checking.
    
    This class ensures that web scraping activities respect the
    website's robots.txt file, which contains the site's scraping rules.
    """
    
    def __init__(self, config: ScrapingConfig):
        self.config = config
        self._parsers: Dict[str, RobotFileParser] = {}
    
    def _get_parser(self, base_url: str) -> RobotFileParser:
        """Get or create a RobotFileParser for the given base URL."""
        parsed_url = urllib.parse.urlparse(base_url)
        domain = f"{parsed_url.scheme}://{parsed_url.netloc}"
        
        if domain not in self._parsers:
            parser = RobotFileParser()
            try:
                parser.set_url(f"{domain}/robots.txt")
                parser.read()
                self._parsers[domain] = parser
                logger.info(f"Loaded robots.txt for {domain}")
            except Exception as e:
                logger.warning(f"Could not load robots.txt for {domain}: {e}")
                # Return a permissive parser if robots.txt can't be loaded
                parser = RobotFileParser()
                self._parsers[domain] = parser
        
        return self._parsers[domain]
    
    def can_fetch(self, url: str, user_agent: str = "*") -> bool:
        """
        Check if a URL can be scraped according to robots.txt.
        
        Args:
            url: The URL to check
            user_agent: The user agent string to check for
            
        Returns:
            True if scraping is allowed, False otherwise
        """
        if not self.config.respect_robots_txt:
            return True
        
        try:
            base_url = urllib.parse.urlparse(url).netloc
            parser = self._parsers.get(base_url)
            if parser is None:
                parser = self._get_parser(url)
            
            can_fetch = parser.can_fetch(user_agent, url)
            if not can_fetch:
                logger.warning(f"Scraping disallowed by robots.txt: {url}")
            return can_fetch
        except Exception as e:
            logger.warning(f"Error checking robots.txt: {e}")
            # Default to allowing if there's an error
            return True


# ============================================================================
# REQUEST HANDLER WITH RETRY LOGIC
# ============================================================================

class RequestHandler:
    """
    Handles HTTP requests with retry logic and error handling.
    
    Implements exponential backoff for failed requests and manages
    timeouts and connection errors gracefully.
    """
    
    def __init__(self, config: ScrapingConfig):
        self.config = config
        self.session = requests.Session()
        
        # Set default headers that mimic a real browser
        self.session.headers.update({
            "User-Agent": config.user_agent,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.5",
            "Accept-Encoding": "gzip, deflate",
            "Connection": "keep-alive",
            "Upgrade-Insecure-Requests": "1",
            "Cache-Control": "max-age=0",
        })
    
    def _calculate_delay(self, attempt: int) -> float:
        """Calculate delay with exponential backoff and jitter."""
        base_delay = self.config.retry_delay * (2 ** attempt)
        jitter = random.uniform(0, 0.5)
        return base_delay + jitter
    
    def fetch(self, url: str) -> Optional[requests.Response]:
        """
        Fetch a URL with retry logic and error handling.
        
        Args:
            url: The URL to fetch
            
        Returns:
            Response object if successful, None otherwise
        """
        last_exception = None
        
        for attempt in range(self.config.max_retries):
            try:
                logger.info(f"Fetching {url} (attempt {attempt + 1}/{self.config.max_retries})")
                
                response = self.session.get(
                    url,
                    timeout=self.config.request_timeout,
                    allow_redirects=True,
                    verify=self.config.verify_ssl
                )
                
                # Check for common error status codes
                response.raise_for_status()
                
                logger.info(f"Successfully fetched {url}")
                return response
                
            except requests.exceptions.Timeout as e:
                last_exception = e
                logger.warning(f"Timeout fetching {url}: {e}")
                
            except requests.exceptions.ConnectionError as e:
                last_exception = e
                logger.warning(f"Connection error for {url}: {e}")
                
            except requests.exceptions.HTTPError as e:
                # Don't retry for client errors (4xx) except 429 (Too Many Requests)
                if response.status_code == 429:
                    last_exception = e
                    logger.warning(f"Rate limited (429) for {url}")
                elif 400 <= response.status_code < 500:
                    logger.error(f"Client error {response.status_code} for {url}, not retrying")
                    return None
                else:
                    last_exception = e
                    logger.warning(f"HTTP error {response.status_code} for {url}")
            
            except requests.exceptions.TooManyRedirects as e:
                last_exception = e
                logger.error(f"Too many redirects for {url}: {e}")
                return None
                
            except requests.exceptions.RequestException as e:
                last_exception = e
                logger.warning(f"Request error for {url}: {e}")
            
            # Wait before retrying with exponential backoff
            if attempt < self.config.max_retries - 1:
                delay = self._calculate_delay(attempt)
                logger.info(f"Waiting {delay:.2f} seconds before retry...")
                time.sleep(delay)
        
        logger.error(f"Failed to fetch {url} after {self.config.max_retries} attempts: {last_exception}")
        return None


# ============================================================================
# HTML PARSER
# ============================================================================

class HTMLParser:
    """
    Parses HTML content using BeautifulSoup.
    
    Provides methods to extract:
    - Page titles
    - Text content
    - Links
    - Custom elements via CSS selectors
    """
    
    def __init__(self, encoding: str = "utf-8"):
        self.encoding = encoding
    
    def parse(self, html_content: str) -> BeautifulSoup:
        """
        Parse HTML content into a BeautifulSoup object.
        
        Args:
            html_content: Raw HTML string
            
        Returns:
            BeautifulSoup object for further parsing
        """
        if not html_content:
            return BeautifulSoup("", "html.parser")
        
        # Try to handle encoding issues
        try:
            # Try decoding with detected encoding
            if isinstance(html_content, bytes):
                # Try UTF-8 first, then fallback to detected encoding
                try:
                    html_content = html_content.decode('utf-8')
                except UnicodeDecodeError:
                    # Use chardet or try common encodings
                    for encoding in ['latin-1', 'cp1252', 'iso-8859-1']:
                        try:
                            html_content = html_content.decode(encoding)
                            break
                        except (UnicodeDecodeError, AttributeError):
                            continue
            
            return BeautifulSoup(html_content, "html.parser")
            
        except Exception as e:
            logger.warning(f"Error parsing HTML: {e}")
            # Return empty soup if parsing fails
            return BeautifulSoup("", "html.parser")
    
    def extract_title(self, soup: BeautifulSoup) -> str:
        """Extract page title with fallbacks."""
        # Try various methods to get the title
        title = ""
        
        # Method 1: <title> tag
        title_tag = soup.find("title")
        if title_tag:
            title = title_tag.get_text(strip=True)
        
        # Method 2: <h1> tag as fallback
        if not title:
            h1_tag = soup.find("h1")
            if h1_tag:
                title = h1_tag.get_text(strip=True)
        
        # Method 3: og:title meta tag
        if not title:
            og_title = soup.find("meta", property="og:title")
            if og_title and og_title.get("content"):
                title = og_title["content"]
        
        return title
    
    def extract_text(self, soup: BeautifulSoup, 
                     selectors: Optional[List[str]] = None) -> str:
        """
        Extract text content from the page.
        
        Args:
            soup: BeautifulSoup object
            selectors: Optional list of CSS selectors to extract from
            
        Returns:
            Cleaned text content
        """
        text_parts = []
        
        if selectors:
            # Extract from specified selectors
            for selector in selectors:
                elements = soup.select(selector)
                for elem in elements:
                    text = elem.get_text(separator=" ", strip=True)
                    if text:
                        text_parts.append(text)
        else:
            # Default: extract from common content areas
            content_tags = ["article", "main", "section", "div", "p"]
            
            for tag in content_tags:
                elements = soup.find_all(tag)
                for elem in elements:
                    # Skip navigation, footer, header elements
                    if elem.name in ["div", "section"]:
                        parent_class = elem.get("class", [""])[0] if elem.get("class") else ""
                        if any(x in parent_class.lower() for x in ["nav", "footer", "header", "sidebar"]):
                            continue
                    
                    text = elem.get_text(separator=" ", strip=True)
                    if text and len(text) > 20:  # Filter out short snippets
                        text_parts.append(text)
        
        # Join and clean up text
        if text_parts:
            # Remove duplicates while preserving order
            seen = set()
            unique_parts = []
            for part in text_parts:
                normalized = " ".join(part.split())
                if normalized not in seen:
                    seen.add(normalized)
                    unique_parts.append(normalized)
            
            return "\n\n".join(unique_parts[slice(0, 10)])  # Limit to top 10 content blocks
        
        return ""
    
    def extract_links(self, soup: BeautifulSoup, 
                      base_url: str = "") -> List[Dict[str, str]]:
        """
        Extract all links from the page.
        
        Args:
            soup: BeautifulSoup object
            base_url: Base URL for resolving relative links
            
        Returns:
            List of dictionaries with link information
        """
        links = []
        seen_urls = set()
        
        for a_tag in soup.find_all("a", href=True):
            href = a_tag["href"]
            
            # Skip empty or javascript links
            if not href or href.startswith("#") or href.startswith("javascript:"):
                continue
            
            # Resolve relative URLs
            if base_url and not href.startswith(("http://", "https://")):
                try:
                    href = urllib.parse.urljoin(base_url, href)
                except Exception:
                    continue
            
            # Skip duplicate URLs
            if href in seen_urls:
                continue
            seen_urls.add(href)
            
            # Extract link text
            text = a_tag.get_text(strip=True) or ""
            
            # Extract additional attributes
            title = a_tag.get("title", "")
            
            links.append({
                "url": href,
                "text": text,
                "title": title
            })
        
        return links
    
    def extract_metadata(self, soup: BeautifulSoup, url: str) -> Dict[str, Any]:
        """Extract metadata from common meta tags."""
        metadata = {
            "description": "",
            "keywords": "",
            "author": "",
            "og_title": "",
            "og_description": "",
            "og_image": "",
            "canonical_url": "",
        }
        
        # Common meta tags to extract
        meta_mappings = {
            "description": ("meta", {"name": "description"}),
            "keywords": ("meta", {"name": "keywords"}),
            "author": ("meta", {"name": "author"}),
            "og_title": ("meta", {"property": "og:title"}),
            "og_description": ("meta", {"property": "og:description"}),
            "og_image": ("meta", {"property": "og:image"}),
        }
        
        for key, (tag, attrs) in meta_mappings.items():
            element = soup.find(tag, attrs)
            if element and element.get("content"):
                metadata[key] = element["content"]
        
        # Get canonical URL
        canonical = soup.find("link", {"rel": "canonical"})
        if canonical and canonical.get("href"):
            metadata["canonical_url"] = canonical["href"]
        else:
            metadata["canonical_url"] = url
        
        return metadata


# ============================================================================
# DYNAMIC CONTENT HANDLER (SELENIUM)
# ============================================================================

class DynamicContentHandler:
    """
    Handles dynamic content that requires JavaScript execution.
    
    Uses Selenium WebDriver to render pages with JavaScript.
    Note: Requires selenium and appropriate webdriver to be installed.
    """
    
    def __init__(self, config: ScrapingConfig):
        self.config = config
        # Type annotation for Selenium WebDriver (set after initialization)
        self.driver: Any = None
    
    def _init_driver(self):
        """Initialize the Selenium WebDriver."""
        try:
            # type: ignore - Selenium is optional, handled by ImportError below
            from selenium import webdriver  # type: ignore
            from selenium.webdriver.chrome.options import Options  # type: ignore
            from selenium.webdriver.chrome.service import Service  # type: ignore
            from webdriver_manager.chrome import ChromeDriverManager  # type: ignore
            
            chrome_options = Options()
            chrome_options.add_argument("--headless")
            chrome_options.add_argument("--no-sandbox")
            chrome_options.add_argument("--disable-dev-shm-usage")
            chrome_options.add_argument("--disable-gpu")
            chrome_options.add_argument(f"user-agent={self.config.user_agent}")
            
            self.driver = webdriver.Chrome(
                service=Service(ChromeDriverManager().install()),
                options=chrome_options
            )
            self.driver.set_page_load_timeout(self.config.request_timeout)
            
        except ImportError:
            logger.error("Selenium not installed. Install with: pip install selenium webdriver-manager")
            raise
        except Exception as e:
            logger.error(f"Failed to initialize Selenium: {e}")
            raise
    
    def fetch_dynamic(self, url: str) -> Optional[str]:
        """
        Fetch a page with JavaScript rendering.
        
        Args:
            url: URL to fetch
            
        Returns:
            Rendered HTML content or None on failure
        """
        if self.driver is None:
            self._init_driver()
        
        try:
            logger.info(f"Fetching dynamic content from: {url}")
            self.driver.get(url)
            
            # Wait for page to load
            time.sleep(self.config.selenium_wait_time)
            
            return self.driver.page_source
            
        except Exception as e:
            logger.error(f"Error fetching dynamic content: {e}")
            return None
    
    def close(self):
        """Close the WebDriver."""
        if self.driver:
            self.driver.quit()
            self.driver = None


# ============================================================================
# DATA EXPORTER
# ============================================================================

class DataExporter:
    """
    Handles exporting scraped data to various formats.
    
    Supports JSON and CSV export formats.
    """
    
    @staticmethod
    def to_json(data: List[ScrapedData], output_path: str) -> bool:
        """
        Export data to JSON file.
        
        Args:
            data: List of ScrapedData objects
            output_path: Path to output JSON file
            
        Returns:
            True if successful, False otherwise
        """
        try:
            # Convert dataclass to dict
            data_dicts = []
            for item in data:
                item_dict = {
                    "url": item.url,
                    "title": item.title,
                    "text_content": item.text_content,
                    "links": item.links,
                    "metadata": item.metadata,
                    "error": item.error,
                    "timestamp": item.timestamp
                }
                data_dicts.append(item_dict)
            
            with open(output_path, "w", encoding="utf-8") as f:
                json.dump(data_dicts, f, ensure_ascii=False, indent=2)
            
            logger.info(f"Data exported to JSON: {output_path}")
            return True
            
        except Exception as e:
            logger.error(f"Error exporting to JSON: {e}")
            return False
    
    @staticmethod
    def to_csv(data: List[ScrapedData], output_path: str) -> bool:
        """
        Export data to CSV file.
        
        Args:
            data: List of ScrapedData objects
            output_path: Path to output CSV file
            
        Returns:
            True if successful, False otherwise
        """
        try:
            with open(output_path, "w", encoding="utf-8", newline="") as f:
                writer = csv.writer(f)
                
                # Write header
                writer.writerow(["URL", "Title", "Text Content", "Link URLs", 
                                "Link Texts", "Error", "Timestamp"])
                
                # Write data rows
                for item in data:
                    # Extract link URLs and texts
                    link_urls = "; ".join([link["url"] for link in item.links])
                    link_texts = "; ".join([link["text"] for link in item.links 
                                           if link["text"]])
                    
                    # Limit text lengths to prevent very long rows
                    text_slice = slice(0, 5000)
                    writer.writerow([
                        item.url,
                        item.title,
                        item.text_content[text_slice],
                        link_urls[text_slice],
                        link_texts[text_slice],
                        item.error or "",
                        item.timestamp
                    ])
            
            logger.info(f"Data exported to CSV: {output_path}")
            return True
            
        except Exception as e:
            logger.error(f"Error exporting to CSV: {e}")
            return False


# ============================================================================
# MAIN WEB SCRAPER CLASS
# ============================================================================

class WebScraper:
    """
    Main web scraper class that coordinates all components.
    
    This is the primary interface for the web scraper. It combines
    all the components to provide a complete scraping solution.
    
    Example usage:
        scraper = WebScraper()
        
        # Simple scraping
        result = scraper.scrape("https://example.com")
        
        # Custom scraping with selectors
        result = scraper.scrape(
            "https://example.com",
            text_selectors=["article.content", "div.description"],
            link_selectors=["a.navigation", "a.post-link"]
        )
        
        # Batch scraping
        urls = ["https://example.com", "https://example.org"]
        results = scraper.scrape_multiple(urls)
        
        # Export results
        scraper.export(results, "output.json", format="json")
    """
    
    def __init__(self, config: Optional[ScrapingConfig] = None):
        """
        Initialize the web scraper.
        
        Args:
            config: ScrapingConfig object (uses defaults if not provided)
        """
        self.config = config or ScrapingConfig()
        
        # Initialize components
        self.robots_checker = RobotsTxtChecker(self.config)
        self.request_handler = RequestHandler(self.config)
        self.html_parser = HTMLParser()
        self.dynamic_handler: Optional[DynamicContentHandler] = None
        
        if self.config.use_selenium:
            try:
                self.dynamic_handler = DynamicContentHandler(self.config)
            except Exception as e:
                logger.warning(f"Could not initialize dynamic content handler: {e}")
    
    def _check_robots(self, url: str) -> bool:
        """Check if URL can be scraped according to robots.txt."""
        return self.robots_checker.can_fetch(url, self.config.user_agent)
    
    def scrape(self, url: str,
               text_selectors: Optional[List[str]] = None,
               link_selectors: Optional[List[str]] = None) -> ScrapedData:
        """
        Scrape a single URL.
        
        Args:
            url: URL to scrape
            text_selectors: Optional CSS selectors for text extraction
            link_selectors: Optional CSS selectors for link extraction
            
        Returns:
            ScrapedData object containing the scraped information
        """
        from datetime import datetime
        
        # Initialize result
        result = ScrapedData(
            url=url,
            timestamp=datetime.now().isoformat()
        )
        
        # Check robots.txt first
        if not self._check_robots(url):
            result.error = "Scraping disallowed by robots.txt"
            logger.warning(f"Skipping {url}: disallowed by robots.txt")
            return result
        
        # Respect delay between requests
        time.sleep(self.config.delay_between_requests)
        
        response: Optional[requests.Response] = None
        html_content: Optional[str] = None
        dynamic_handler = self.dynamic_handler
        
        try:
            # Fetch the page
            if self.config.use_selenium and dynamic_handler is not None:
                html_content = dynamic_handler.fetch_dynamic(url)
            else:
                response = self.request_handler.fetch(url)
                html_content = response.text if response else None
            
            if not html_content:
                result.error = "Failed to fetch page content"
                return result
            
            # Parse the HTML
            soup = self.html_parser.parse(html_content)
            
            # Extract data
            result.title = self.html_parser.extract_title(soup)
            result.text_content = self.html_parser.extract_text(soup, text_selectors)
            result.links = self.html_parser.extract_links(soup, url)
            result.metadata = self.html_parser.extract_metadata(soup, url)
            
            logger.info(f"Successfully scraped: {url}")
            
        except Exception as e:
            result.error = f"Scraping error: {str(e)}"
            logger.error(f"Error scraping {url}: {e}")
        
        return result
    
    def scrape_multiple(self, urls: List[str],
                       text_selectors: Optional[List[str]] = None,
                       link_selectors: Optional[List[str]] = None,
                       progress_callback: Optional[Callable[[int, int], None]] = None) -> List[ScrapedData]:
        """
        Scrape multiple URLs.
        
        Args:
            urls: List of URLs to scrape
            text_selectors: Optional CSS selectors for text extraction
            link_selectors: Optional CSS selectors for link extraction
            progress_callback: Optional callback for progress updates
            
        Returns:
            List of ScrapedData objects
        """
        results = []
        total = len(urls)
        
        for i, url in enumerate(urls, 1):
            logger.info(f"Scraping {i}/{total}: {url}")
            
            result = self.scrape(url, text_selectors, link_selectors)
            results.append(result)
            
            # Call progress callback if provided
            callback = progress_callback
            if callback is not None:
                assert callable(callback)  # Type narrowing for type checker
                try:
                    callback(i, total)
                except Exception as e:
                    logger.warning(f"Error in progress callback: {e}")
        
        logger.info(f"Completed scraping {total} URLs")
        return results
    
    def export(self, data: List[ScrapedData], 
               output_path: str, 
               format: str = "json") -> bool:
        """
        Export scraped data to a file.
        
        Args:
            data: List of ScrapedData objects
            output_path: Path to output file
            format: Export format ("json" or "csv")
            
        Returns:
            True if successful, False otherwise
        """
        if format.lower() == "json":
            return DataExporter.to_json(data, output_path)
        elif format.lower() == "csv":
            return DataExporter.to_csv(data, output_path)
        else:
            logger.error(f"Unsupported export format: {format}")
            return False
    
    def close(self):
        """Clean up resources."""
        handler = self.dynamic_handler
        if handler is not None:
            handler.close()


# ============================================================================
# DEMONSTRATION AND TESTING
# ============================================================================

def demo():
    """
    Demonstration of the web scraper functionality.
    """
    print("=" * 60)
    print("Web Scraper Demo")
    print("=" * 60)
    
    # Create scraper with custom configuration
    config = ScrapingConfig(
        request_timeout=20,
        max_retries=3,
        retry_delay=1.0,
        delay_between_requests=0.5,
        respect_robots_txt=True
    )
    
    scraper = WebScraper(config)
    
    # Example 1: Scrape a simple page
    print("\n1. Scraping a simple page...")
    result = scraper.scrape("https://example.com")
    
    print(f"   URL: {result.url}")
    print(f"   Title: {result.title}")
    text_preview = result.text_content[slice(0, 100)] + "..." if result.text_content else "(empty)"
    print(f"   Text preview: {text_preview}")
    print(f"   Number of links: {len(result.links)}")
    if result.error:
        print(f"   Error: {result.error}")
    
    # Example 2: Scrape with custom selectors
    print("\n2. Scraping with custom text selectors...")
    result2 = scraper.scrape(
        "https://example.com",
        text_selectors=["p", "div.content"],
        link_selectors=["a"]
    )
    print(f"   Title: {result2.title}")
    print(f"   Text length: {len(result2.text_content)} characters")
    
    # Example 3: Export to JSON
    print("\n3. Exporting to JSON...")
    scraper.export([result, result2], "scraped_data.json", format="json")
    print("   Data exported to scraped_data.json")
    
    # Example 4: Export to CSV
    print("\n4. Exporting to CSV...")
    scraper.export([result, result2], "scraped_data.csv", format="csv")
    print("   Data exported to scraped_data.csv")
    
    # Clean up
    scraper.close()
    
    print("\n" + "=" * 60)
    print("Demo completed!")
    print("=" * 60)


if __name__ == "__main__":
    demo()
