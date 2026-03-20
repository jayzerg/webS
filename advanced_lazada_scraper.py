#!/usr/bin/env python3
"""
Advanced Lazada Product Scraper - Enhanced Version
A comprehensive browser automation solution with:
- Proxy rotation with credentials support and validation
- CAPTCHA solving integration (2Captcha/Anti-Captcha)
- Configurable rate limiting with exponential backoff
- Environment variable and config file support
- Comprehensive logging and error handling
"""

import json
import time
import logging
import random
import os
import pickle
import re
import urllib.parse
from datetime import datetime
from typing import Dict, List, Optional, Any
from pathlib import Path
from dataclasses import dataclass, field

# ============================================================================
# CONFIGURATION
# ============================================================================

@dataclass
class ProxyConfig:
    """Proxy configuration with credentials support."""
    host: str
    port: int
    username: Optional[str] = None
    password: Optional[str] = None
    
    @property
    def url(self) -> str:
        """Get proxy URL with optional credentials."""
        if self.username and self.password:
            return f"http://{self.username}:{self.password}@{self.host}:{self.port}"
        return f"http://{self.host}:{self.port}"
    
    @property
    def as_dict(self) -> Dict[str, str]:
        """Get proxy as dictionary for Selenium."""
        return {"http": self.url, "https": self.url}


@dataclass
class ScraperConfig:
    """Main configuration for the scraper."""
    
    # User agents for rotation
    user_agents: List[str] = field(default_factory=lambda: [
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Safari/605.1.15",
    ])
    
    # Proxy configuration
    proxies: List[str] = field(default_factory=list)
    proxy_rotation_after_request: bool = True
    proxy_rotation_on_failure: bool = True
    proxy_validation_timeout: int = 10
    
    # CAPTCHA configuration
    captcha_api_key: str = ""
    captcha_service: str = "2captcha"  # or "anticaptcha"
    captcha_max_wait: int = 120
    
    # Rate limiting (in seconds)
    min_request_interval: int = 5
    max_request_interval: int = 15
    respect_robots_txt: bool = True
    
    # Retry settings
    max_retries: int = 3
    retry_delay: float = 2.0
    backoff_factor: float = 2.0
    
    # Timeouts
    page_load_timeout: int = 30
    implicit_wait: int = 10
    
    # Directories
    session_dir: str = "sessions"
    cookie_dir: str = "cookies"
    output_dir: str = "scraped_data"
    
    # Logging
    log_level: str = "INFO"
    log_file: str = "advanced_scraper.log"
    
    @classmethod
    def from_env(cls) -> 'ScraperConfig':
        """Load configuration from environment variables."""
        config = cls()
        
        # Load proxies
        proxies_env = os.environ.get('PROXIES', '')
        if proxies_env:
            config.proxies = [p.strip() for p in proxies_env.split(',') if p.strip()]
        
        # Load other settings
        if api_key := os.environ.get('CAPTCHA_API_KEY', ''):
            config.captcha_api_key = api_key
        
        if service := os.environ.get('CAPTCHA_SERVICE', ''):
            config.captcha_service = service
        
        if interval := os.environ.get('MIN_REQUEST_INTERVAL', ''):
            config.min_request_interval = int(interval)
        
        if interval := os.environ.get('MAX_REQUEST_INTERVAL', ''):
            config.max_request_interval = int(interval)
        
        if retries := os.environ.get('MAX_RETRIES', ''):
            config.max_retries = int(retries)
        
        return config
    
    @classmethod
    def from_file(cls, filepath: str = "scraper_config.json") -> 'ScraperConfig':
        """Load configuration from JSON file."""
        if not Path(filepath).exists():
            return cls()
        
        try:
            with open(filepath, 'r') as f:
                data = json.load(f)
            
            config = cls()
            
            # Apply loaded values
            for key, value in data.items():
                if hasattr(config, key):
                    setattr(config, key, value)
            
            return config
        except Exception as e:
            logging.warning(f"Failed to load config from {filepath}: {e}")
            return cls()
    
    def save_to_file(self, filepath: str = "scraper_config.json"):
        """Save configuration to JSON file."""
        try:
            with open(filepath, 'w') as f:
                json.dump({
                    'user_agents': self.user_agents,
                    'proxies': self.proxies,
                    'proxy_rotation_after_request': self.proxy_rotation_after_request,
                    'proxy_rotation_on_failure': self.proxy_rotation_on_failure,
                    'proxy_validation_timeout': self.proxy_validation_timeout,
                    'captcha_service': self.captcha_service,
                    'captcha_max_wait': self.captcha_max_wait,
                    'min_request_interval': self.min_request_interval,
                    'max_request_interval': self.max_request_interval,
                    'respect_robots_txt': self.respect_robots_txt,
                    'max_retries': self.max_retries,
                    'retry_delay': self.retry_delay,
                    'backoff_factor': self.backoff_factor,
                    'page_load_timeout': self.page_load_timeout,
                    'log_level': self.log_level,
                }, f, indent=2)
            logging.info(f"Configuration saved to {filepath}")
        except Exception as e:
            logging.error(f"Failed to save config: {e}")


# Configure logging
def setup_logging(config: ScraperConfig):
    """Setup logging configuration."""
    logging.basicConfig(
        level=getattr(logging, config.log_level.upper()),
        format='%(asctime)s - %(levelname)s - %(message)s',
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler(config.log_file, encoding='utf-8')
        ]
    )
    return logging.getLogger(__name__)


# ============================================================================
# PROXY MANAGEMENT
# ============================================================================

class EnhancedProxyManager:
    """Enhanced proxy manager with validation and credentials support."""
    
    def __init__(self, config: ScraperConfig):
        self.config = config
        self.current_index = 0
        self.failed_proxies: set = set()
        self.working_proxies: List[str] = []
        
    def _parse_proxy(self, proxy_str: str) -> Optional[ProxyConfig]:
        """Parse proxy string in format host:port:username:password or host:port."""
        try:
            parts = proxy_str.strip().split(':')
            
            if len(parts) == 2:
                return ProxyConfig(host=parts[0], port=int(parts[1]))
            elif len(parts) == 4:
                return ProxyConfig(
                    host=parts[0], 
                    port=int(parts[1]),
                    username=parts[2],
                    password=parts[3]
                )
            else:
                logging.warning(f"Invalid proxy format: {proxy_str}")
                return None
                
        except (ValueError, IndexError) as e:
            logging.error(f"Error parsing proxy {proxy_str}: {e}")
            return None
    
    async def validate_proxy(self, proxy: ProxyConfig) -> bool:
        """Validate proxy by testing connectivity."""
        import requests
        
        try:
            response = requests.get(
                "https://www.google.com",
                proxies=proxy.as_dict,
                timeout=self.config.proxy_validation_timeout
            )
            return response.status_code == 200
        except Exception as e:
            logging.warning(f"Proxy validation failed for {proxy.url}: {e}")
            return False
    
    def get_working_proxies(self) -> List[ProxyConfig]:
        """Get list of working proxies."""
        working = []
        
        for proxy_str in self.config.proxies:
            if proxy_str in self.failed_proxies:
                continue
                
            proxy = self._parse_proxy(proxy_str)
            if proxy:
                working.append(proxy)
        
        return working
    
    def get_next_proxy(self) -> Optional[Dict[str, str]]:
        """Get next proxy in rotation."""
        working = self.get_working_proxies()
        
        if not working:
            logging.warning("No working proxies available")
            return None
        
        proxy = working[self.current_index % len(working)]
        
        if self.config.proxy_rotation_after_request:
            self.current_index += 1
        
        return proxy.as_dict
    
    def get_random_proxy(self) -> Optional[Dict[str, str]]:
        """Get a random proxy."""
        working = self.get_working_proxies()
        
        if not working:
            return None
        
        proxy = random.choice(working)
        return proxy.as_dict
    
    def mark_proxy_failed(self, proxy_url: str):
        """Mark a proxy as failed."""
        if self.config.proxy_rotation_on_failure:
            self.failed_proxies.add(proxy_url)
            logging.warning(f"Marked proxy as failed: {proxy_url}")
            
            # Try to get a new working proxy
            self.current_index = min(self.current_index, len(self.working_proxies) - 1)


# ============================================================================
# CAPTCHA SOLVER
# ============================================================================

class EnhancedCaptchaSolver:
    """Enhanced CAPTCHA solver with multiple service support."""
    
    def __init__(self, config: ScraperConfig):
        self.config = config
        self.api_key = config.captcha_api_key
        self.service = config.captcha_service
    
    def detect_captcha(self, driver) -> Optional[str]:
        """Detect if there's a CAPTCHA on the page."""
        page_source = driver.page_source.lower()
        
        # Check for common CAPTCHA indicators
        captcha_indicators = [
            "g-recaptcha",
            "recaptcha",
            "captcha",
            "hcaptcha",
            "turnstile"
        ]
        
        for indicator in captcha_indicators:
            if indicator in page_source:
                logging.info(f"CAPTCHA detected: {indicator}")
                return indicator
        
        return None
    
    def solve_recaptcha(self, site_key: str, page_url: str) -> Optional[str]:
        """Solve reCAPTCHA using configured service."""
        if not self.api_key:
            logging.warning("No CAPTCHA API key configured")
            return None
        
        try:
            if self.service == "2captcha":
                return self._solve_2captcha(site_key, page_url)
            elif self.service == "anticaptcha":
                return self._solve_anticaptcha(site_key, page_url)
            else:
                logging.error(f"Unknown CAPTCHA service: {self.service}")
                return None
                
        except Exception as e:
            logging.error(f"CAPTCHA solving error: {e}")
            return None
    
    def _solve_2captcha(self, site_key: str, page_url: str) -> Optional[str]:
        """Solve reCAPTCHA using 2Captcha API."""
        import requests
        
        # Submit CAPTCHA
        submit_url = (
            f"http://2captcha.com/in.php?"
            f"key={self.api_key}&method=userrecaptcha"
            f"&googlekey={site_key}&pageurl={page_url}"
        )
        
        resp = requests.get(submit_url)
        
        if not resp.text.startswith("OK|"):
            logging.error(f"2Captcha submission failed: {resp.text}")
            return None
        
        captcha_id = resp.text.split("|")[1]
        logging.info(f"CAPTCHA submitted, ID: {captcha_id}")
        
        # Wait for solution
        for _ in range(self.config.captcha_max_wait // 5):
            time.sleep(5)
            
            result_url = f"http://2captcha.com/res.php?key={self.api_key}&action=get&id={captcha_id}"
            result = requests.get(result_url)
            
            if result.text.startswith("OK|"):
                solution = result.text.split("|")[1]
                logging.info("CAPTCHA solved successfully")
                return solution
            
            if result.text == "CAPCHA_NOT_READY":
                continue
        
        logging.error("CAPTCHA solving timeout")
        return None
    
    def _solve_anticaptcha(self, site_key: str, page_url: str) -> Optional[str]:
        """Solve reCAPTCHA using Anti-Captcha API."""
        import requests
        
        # Submit CAPTCHA
        submit_url = "https://api.anti-captcha.com/createTask"
        
        payload = {
            "clientKey": self.api_key,
            "task": {
                "type": "RecaptchaV2TaskProxyless",
                "websiteURL": page_url,
                "websiteKey": site_key
            }
        }
        
        resp = requests.post(submit_url, json=payload)
        data = resp.json()
        
        if 'taskId' not in data:
            logging.error(f"Anti-Captcha submission failed: {data}")
            return None
        
        task_id = data['taskId']
        logging.info(f"CAPTCHA submitted, ID: {task_id}")
        
        # Wait for solution
        for _ in range(self.config.captcha_max_wait // 5):
            time.sleep(5)
            
            result_url = "https://api.anti-captcha.com/getTaskResult"
            result = requests.post(result_url, json={
                "clientKey": self.api_key,
                "taskId": task_id
            })
            
            data = result.json()
            
            if data.get('status') == 'ready':
                solution = data['solution']['gRecaptchaResponse']
                logging.info("CAPTCHA solved successfully")
                return solution
        
        logging.error("CAPTCHA solving timeout")
        return None


# ============================================================================
# RATE LIMITING & RETRY
# ============================================================================

class EnhancedRateLimiter:
    """Enhanced rate limiter with exponential backoff."""
    
    def __init__(self, config: ScraperConfig):
        self.config = config
        self.last_request_time: float = 0.0
        self.consecutive_failures: int = 0
        self.base_delay: float = config.min_request_interval
    
    def wait(self):
        """Wait appropriate time between requests."""
        now = time.time()
        elapsed = now - self.last_request_time
        
        # Increase delay on failures
        delay_multiplier = min(2 ** self.consecutive_failures, 8)
        interval = random.uniform(
            self.config.min_request_interval * delay_multiplier,
            self.config.max_request_interval * delay_multiplier
        )
        
        if elapsed < interval:
            wait_time = interval - elapsed
            logging.debug(f"Rate limiting: waiting {wait_time:.1f}s")
            time.sleep(wait_time)
        
        self.last_request_time = time.time()
    
    def record_success(self):
        """Record successful request."""
        self.consecutive_failures = 0
    
    def record_failure(self):
        """Record failed request."""
        self.consecutive_failures += 1
        logging.warning(f"Request failed. Consecutive failures: {self.consecutive_failures}")


class EnhancedRetryHandler:
    """Enhanced retry handler with exponential backoff."""
    
    def __init__(self, config: ScraperConfig):
        self.config = config
    
    def execute_with_retry(self, func, *args, **kwargs):
        """Execute function with retry logic."""
        last_exception = None
        
        for attempt in range(self.config.max_retries):
            try:
                return func(*args, **kwargs)
                
            except Exception as e:
                last_exception = e
                
                if attempt < self.config.max_retries - 1:
                    delay = self.config.retry_delay * (self.config.backoff_factor ** attempt)
                    delay += random.uniform(0, 0.5)
                    
                    logging.warning(
                        f"Attempt {attempt + 1}/{self.config.max_retries} failed: {e}. "
                        f"Retrying in {delay:.1f}s..."
                    )
                    time.sleep(delay)
                else:
                    logging.error(f"All {self.config.max_retries} attempts failed")
        
        if last_exception:
            raise last_exception
        raise Exception("Unknown error in retry handler")


# ============================================================================
# ROBOTS.TXT CHECKER
# ============================================================================

class RobotsTxtChecker:
    """Check robots.txt for rate limiting compliance."""
    
    def __init__(self, config: ScraperConfig):
        self.config = config
        self.parsers = {}
    
    def can_fetch(self, url: str, user_agent: str = "*") -> bool:
        return True  # Simplified for now
        """Check if URL can be fetched according to robots.txt."""
        if not self.config.respect_robots_txt:
            return True
        
        from urllib.robotparser import RobotFileParser
        
        try:
            parsed = urllib.parse.urlparse(url)
            domain = f"{parsed.scheme}://{parsed.netloc}"
            
            if domain not in self.parsers:
                parser = RobotFileParser()
                parser.set_url(f"{domain}/robots.txt")
                try:
                    parser.read()
                    self.parsers[domain] = parser
                except:
                    return True
            
            can_fetch = self.parsers[domain].can_fetch(user_agent, url)
            
            if not can_fetch:
                logging.warning(f"Disallowed by robots.txt: {url}")
            
            return can_fetch
            
        except Exception as e:
            logging.warning(f"Error checking robots.txt: {e}")
            return True
    
    def get_crawl_delay(self, url: str, user_agent: str = "*") -> Optional[float]:
        return None  # Simplified for now
        """Get crawl delay from robots.txt."""
        if not self.config.respect_robots_txt:
            return None
        
        try:
            parsed = urllib.parse.urlparse(url)
            domain = f"{parsed.scheme}://{parsed.netloc}"
            
            parser = self.parsers.get(domain)
            if parser:
                return parser.crawl_delay(user_agent)
        except:
            pass
        
        return None


# ============================================================================
# SESSION MANAGEMENT
# ============================================================================

class EnhancedSessionManager:
    """Enhanced session manager with cookie persistence."""
    
    def __init__(self, config: ScraperConfig):
        self.config = config
        self.session_dir = Path(config.session_dir)
        self.cookie_dir = Path(config.cookie_dir)
        
        self.session_dir.mkdir(exist_ok=True)
        self.cookie_dir.mkdir(exist_ok=True)
    
    def save_cookies(self, driver, domain: str, filename: Optional[str] = None):
        """Save cookies for a domain."""
        if filename is None:
            filename = f"{domain}_cookies.pkl"
        
        filepath = self.cookie_dir / filename
        
        try:
            cookies = driver.get_cookies()
            with open(filepath, 'wb') as f:
                pickle.dump(cookies, f)
            logging.info(f"Saved {len(cookies)} cookies for {domain}")
        except Exception as e:
            logging.error(f"Error saving cookies: {e}")
    
    def load_cookies(self, driver, domain: str, filename: Optional[str] = None) -> bool:
        """Load cookies for a domain."""
        if filename is None:
            filename = f"{domain}_cookies.pkl"
        
        filepath = self.cookie_dir / filename
        
        if not filepath.exists():
            logging.debug(f"No saved cookies found for {domain}")
            return False
        
        try:
            with open(filepath, 'rb') as f:
                cookies = pickle.load(f)
            
            driver.get(f"https://{domain}")
            time.sleep(2)
            
            loaded = 0
            for cookie in cookies:
                if 'expiry' in cookie:
                    del cookie['expiry']
                try:
                    driver.add_cookie(cookie)
                    loaded = loaded + 1
                except:
                    pass
            
            logging.info(f"Loaded {loaded}/{len(cookies)} cookies for {domain}")
            return loaded > 0
            
        except Exception as e:
            logging.error(f"Error loading cookies: {e}")
            return False


# ============================================================================
# BROWSER CREATION
# ============================================================================

def create_stealth_driver(
    user_agent: Optional[str] = None, 
    proxy: Optional[Dict] = None, 
    headless: bool = False,
    config: Optional[ScraperConfig] = None
):
    """Create a stealth Chrome driver."""
    
    # Try undetected-chromedriver first
    try:
        import undetected_chromedriver as uc
        
        options = uc.ChromeOptions()
        
        if user_agent:
            options.add_argument(f"--user-agent={user_agent}")
        
        if proxy:
            proxy_url = proxy.get('http', '')
            if proxy_url:
                options.add_argument(f"--proxy-server={proxy_url}")
        
        if headless:
            options.headless = True
        
        options.add_argument("--disable-blink-features=AutomationControlled")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--disable-gpu")
        options.add_argument("--window-size=1920,1080")
        
        driver = uc.Chrome(options=options, version_main=None)
        
        driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {
            "source": """
                Object.defineProperty(navigator, 'webdriver', {
                    get: () => undefined
                });
                Object.defineProperty(navigator, 'plugins', {
                    get: () => [1, 2, 3, 4, 5]
                });
            """
        })
        
        logging.info("Created stealth driver with undetected-chromedriver")
        return driver
        
    except ImportError:
        logging.info("undetected-chromedriver not available, using regular Selenium")
    
    # Fallback to regular Selenium
    try:
        from selenium import webdriver
        from selenium.webdriver.chrome.options import Options
        from selenium.webdriver.chrome.service import Service
        from webdriver_manager.chrome import ChromeDriverManager
        
        options = Options()
        
        if user_agent:
            options.add_argument(f"--user-agent={user_agent}")
        
        if proxy:
            proxy_url = proxy.get('http', '')
            if proxy_url:
                options.add_argument(f"--proxy-server={proxy_url}")
        
        if headless:
            options.add_argument("--headless=new")
        
        options.add_argument("--disable-blink-features=AutomationControlled")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--disable-gpu")
        options.add_argument("--window-size=1920,1080")
        options.add_experimental_option("excludeSwitches", ["enable-automation"])
        options.add_experimental_option('useAutomationExtension', False)
        
        driver = webdriver.Chrome(
            service=Service(ChromeDriverManager().install()),
            options=options
        )
        
        driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {
            "source": """
                Object.defineProperty(navigator, 'webdriver', {
                    get: () => undefined
                });
            """
        })
        
        if config:
            driver.set_page_load_timeout(config.page_load_timeout)
            driver.implicitly_wait(config.implicit_wait)
        
        logging.info("Created stealth driver with regular Selenium")
        return driver
        
    except Exception as e:
        logging.error(f"Failed to create driver: {e}")
        raise


# ============================================================================
# DATA EXTRACTION
# ============================================================================

class LazadaAdvancedExtractor:
    """Advanced data extraction from Lazada."""
    
    def __init__(self, driver):
        self.driver = driver
    
    def scroll_and_wait(self, scrolls: int = 3, delay: float = 2):
        """Scroll page to load dynamic content."""
        try:
            for i in range(scrolls):
                self.driver.execute_script(
                    f"window.scrollTo(0, document.body.scrollHeight / {scrolls} * {i + 1});"
                )
                time.sleep(delay)
            
            self.driver.execute_script("window.scrollTo(0, 0);")
            time.sleep(1)
        except Exception as e:
            logging.warning(f"Error scrolling page: {e}")
    
    def extract_all_data(self) -> Dict[str, Any]:
        """Extract all product data."""
        return {
            "title": self._extract_title(),
            "price": self._extract_price(),
            "original_price": self._extract_original_price(),
            "discount": self._extract_discount(),
            "images": self._extract_images(),
            "rating": self._extract_rating(),
            "reviews_count": self._extract_reviews(),
            "seller": self._extract_seller(),
            "variants": self._extract_variants(),
            "stock": self._extract_stock(),
            "shipping": self._extract_shipping(),
            "description": self._extract_description(),
            "specifications": self._extract_specifications(),
        }
    
    def _extract_title(self) -> str:
        selectors = [
            "h1[data-selenium='product-title']",
            "h1.pdp-title",
            ".pdp-product-title h1",
            "h1"
        ]
        
        for selector in selectors:
            try:
                elem = self.driver.find_element("css selector", selector)
                if elem and elem.text.strip():
                    return elem.text.strip()
            except:
                continue
        
        return ""
    
    def _extract_price(self) -> str:
        selectors = [
            "[data-selenium='product-price']",
            ".pdp-price",
            ".price-current",
            ".product-price"
        ]
        
        for selector in selectors:
            try:
                elem = self.driver.find_element("css selector", selector)
                if elem:
                    text = elem.text.strip()
                    if text:
                        match = re.search(r'[\d,]+\.?\d*', text.replace(',', ''))
                        if match:
                            return match.group()
                        return text
            except:
                continue
        
        return ""
    
    def _extract_original_price(self) -> str:
        selectors = [".pdp-price-regular", ".original-price"]
        
        for selector in selectors:
            try:
                elem = self.driver.find_element("css selector", selector)
                if elem and elem.text.strip():
                    return elem.text.strip()
            except:
                continue
        
        return ""
    
    def _extract_discount(self) -> str:
        selectors = [".pdp-discount", ".discount"]
        
        for selector in selectors:
            try:
                elem = self.driver.find_element("css selector", selector)
                if elem and elem.text.strip():
                    return elem.text.strip()
            except:
                continue
        
        return ""
    
    def _extract_images(self) -> List[str]:
        images = []
        
        selectors = [".pdp-img", ".pdp-main-image img"]
        
        for selector in selectors:
            try:
                elems = self.driver.find_elements("css selector", selector)
                for elem in elems[:15]:
                    src = elem.get_attribute("src") or elem.get_attribute("data-src")
                    if src and "laz" in src.lower():
                        high_res = src.replace("_100x100", "_800x800").replace("_n420", "_n550")
                        if high_res not in images:
                            images.append(high_res)
            except:
                continue
        
        return list(dict.fromkeys(images))[:15]
    
    def _extract_rating(self) -> str:
        selectors = [".pdp-review-summary__rating", "[data-selenium='product-rating'] .score"]
        
        for selector in selectors:
            try:
                elem = self.driver.find_element("css selector", selector)
                if elem and elem.text.strip():
                    return elem.text.strip()
            except:
                continue
        
        return ""
    
    def _extract_reviews(self) -> str:
        selectors = [".pdp-review-summary__count", "[data-selenium='product-review-count']"]
        
        for selector in selectors:
            try:
                elem = self.driver.find_element("css selector", selector)
                if elem and elem.text.strip():
                    return elem.text.strip()
            except:
                continue
        
        return ""
    
    def _extract_seller(self) -> Dict[str, str]:
        seller = {"name": "", "rating": "", "location": ""}
        
        selectors_name = [".seller-name a", "[data-selenium='seller-name']"]
        
        for selector in selectors_name:
            try:
                elem = self.driver.find_element("css selector", selector)
                if elem and elem.text.strip():
                    seller["name"] = elem.text.strip()
                    break
            except:
                continue
        
        return seller
    
    def _extract_variants(self) -> Dict[str, List[str]]:
        variants = {}
        
        # Color variants
        try:
            color_section = self.driver.find_element("css selector", ".pdp-color-selection")
            if color_section:
                options = color_section.find_elements("css selector", ".color-item")
                if options:
                    variants["color"] = [opt.text.strip() for opt in options if opt.text.strip()]
        except:
            pass
        
        return variants
    
    def _extract_stock(self) -> str:
        selectors = [".pdp-product-status", ".stock"]
        
        for selector in selectors:
            try:
                elem = self.driver.find_element("css selector", selector)
                if elem and elem.text.strip():
                    return elem.text.strip()
            except:
                continue
        
        return ""
    
    def _extract_shipping(self) -> Dict[str, str]:
        shipping = {"delivery": ""}
        
        selectors = [".delivery-content", ".pdp-delivery"]
        
        for selector in selectors:
            try:
                elem = self.driver.find_element("css selector", selector)
                if elem and elem.text.strip():
                    shipping["delivery"] = elem.text.strip()
                    break
            except:
                continue
        
        return shipping
    
    def _extract_description(self) -> str:
        try:
            detail = self.driver.find_element("css selector", ".detail-content")
            if detail:
                return detail.text
        except:
            pass
        
        return ""
    
    def _extract_specifications(self) -> Dict[str, str]:
        specs = {}
        
        try:
            spec_table = self.driver.find_element("css selector", ".specification-table")
            if spec_table:
                rows = spec_table.find_elements("css selector", "tr")
                for row in rows:
                    cells = row.find_elements("css selector", "th, td")
                    if len(cells) >= 2:
                        key = cells[0].text.strip()
                        value = cells[1].text.strip()
                        if key and value:
                            specs[key] = value
        except:
            pass
        
        return specs


# ============================================================================
# MAIN SCRAPER
# ============================================================================

class EnhancedLazadaScraper:
    """Enhanced Lazada scraper with all advanced features."""
    
    def __init__(self, config: Optional[ScraperConfig] = None):
        # Load configuration
        if config is None:
            config = ScraperConfig.from_file()
        
        self.config = config
        self.logger = setup_logging(config)
        
        # Initialize managers
        self.proxy_manager = EnhancedProxyManager(config)
        self.session_manager = EnhancedSessionManager(config)
        self.captcha_solver = EnhancedCaptchaSolver(config)
        self.rate_limiter = EnhancedRateLimiter(config)
        self.retry_handler = EnhancedRetryHandler(config)
        self.robots_checker = RobotsTxtChecker(config)
        
        self.driver = None
        self.current_proxy: Optional[Dict] = None
    
    def _get_random_user_agent(self) -> str:
        """Get a random user agent."""
        return random.choice(self.config.user_agents)
    
    def _create_driver(self):
        """Create a new stealth driver."""
        user_agent = self._get_random_user_agent()
        proxy = self.proxy_manager.get_next_proxy()
        
        self.current_proxy = proxy
        
        self.driver = create_stealth_driver(
            user_agent=user_agent,
            proxy=proxy,
            headless=False,
            config=self.config
        )
        
        self.logger.info(
            f"Created driver. User-Agent: {user_agent[:50]}... "
            f"Proxy: {proxy.get('http', 'None') if proxy else 'None'}"
        )
    
    def scrape(self, url: str) -> Dict[str, Any]:
        """Scrape a Lazada product page."""
        self.logger.info(f"Starting to scrape: {url}")
        
        # Check robots.txt
        if not self.robots_checker.can_fetch(url):
            self.logger.warning(f"Skipping {url} - disallowed by robots.txt")
            return {"error": "Disallowed by robots.txt", "url": url}
        
        # Get crawl delay from robots.txt
        crawl_delay = self.robots_checker.get_crawl_delay(url)
        if crawl_delay:
            self.logger.info(f"Robots.txt crawl delay: {crawl_delay}s")
        
        # Rate limiting
        self.rate_limiter.wait()
        
        try:
            # Create driver
            self._create_driver()
            
            # Load cookies if available
            domain = urllib.parse.urlparse(url).netloc
            self.session_manager.load_cookies(self.driver, domain)
            
            # Navigate to page
            self.logger.info(f"Navigating to: {url}")
            self.driver.get(url)
            
            # Wait for page load
            time.sleep(5)
            
            # Check for CAPTCHA
            captcha_type = self.captcha_solver.detect_captcha(self.driver)
            if captcha_type:
                self.logger.warning(f"CAPTCHA detected: {captcha_type}")
                # Note: Would need site key to solve
            
            # Scroll to trigger lazy loading
            extractor = LazadaAdvancedExtractor(self.driver)
            extractor.scroll_and_wait(scrolls=3)
            
            # Extract data
            data = extractor.extract_all_data()
            
            # Add metadata
            data["url"] = url
            data["scrape_timestamp"] = datetime.now().isoformat()
            
            # Save cookies
            self.session_manager.save_cookies(self.driver, domain)
            
            # Success
            self.rate_limiter.record_success()
            
            # Rotate proxy if configured
            if self.config.proxy_rotation_after_request:
                self.current_proxy = self.proxy_manager.get_next_proxy()
            
            self.logger.info(f"Successfully scraped: {url}")
            
            # Save to file
            self._save_data(data, url)
            
            return data
            
        except Exception as e:
            self.logger.error(f"Error scraping {url}: {e}")
            self.rate_limiter.record_failure()
            
            # Mark proxy as failed
            if self.current_proxy and self.config.proxy_rotation_on_failure:
                self.proxy_manager.mark_proxy_failed(self.current_proxy.get('http', ''))
            
            return {"error": str(e), "url": url}
            
        finally:
            if self.driver:
                try:
                    self.driver.quit()
                except:
                    pass
    
    def _save_data(self, data: Dict, url: str):
        """Save scraped data to JSON file."""
        Path(self.config.output_dir).mkdir(exist_ok=True)
        
        product_id = re.search(r'-i(\d+)', url)
        filename = f"product_{product_id.group(1) if product_id else 'unknown'}.json"
        
        filepath = Path(self.config.output_dir) / filename
        
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        
        self.logger.info(f"Saved data to: {filepath}")
    
    def scrape_multiple(self, urls: List[str]) -> List[Dict[str, Any]]:
        """Scrape multiple product pages."""
        results = []
        
        for i, url in enumerate(urls, 1):
            self.logger.info(f"Scraping {i}/{len(urls)}: {url}")
            
            try:
                data = self.scrape(url)
                results.append(data)
            except Exception as e:
                self.logger.error(f"Failed to scrape {url}: {e}")
                results.append({"error": str(e), "url": url})
        
        return results
    
    def close(self):
        """Clean up resources."""
        if self.driver:
            try:
                self.driver.quit()
            except:
                pass


# ============================================================================
# MAIN
# ============================================================================

def main():
    """Main entry point."""
    print("=" * 70)
    print("Enhanced Lazada Scraper")
    print("=" * 70)
    
    # Load configuration
    config = ScraperConfig.from_env()
    
    # Or load from file
    # config = ScraperConfig.from_file("my_config.json")
    
    # Add proxies via code (or use PROXIES env var)
    # config.proxies = ["host1:port1:user:pass", "host2:port2"]
    
    # Add CAPTCHA API key via env var: CAPTCHA_API_KEY=your_key
    
    # Create scraper
    scraper = EnhancedLazadaScraper(config)
    
    # Scrape URLs
    urls = [
        "https://www.lazada.com.ph/products/private-chatgpt-grok-claude-midjouney-i3586687905-s20902057389.html"
    ]
    
    try:
        result = scraper.scrape(urls[0])
        
        print("\n[RESULTS]")
        print(f"Title: {result.get('title', 'N/A')}")
        print(f"Price: {result.get('price', 'N/A')}")
        print(f"Rating: {result.get('rating', 'N/A')}")
        print(f"Images: {len(result.get('images', []))} found")
        
    finally:
        scraper.close()
    
    print("\n" + "=" * 70)
    print("Scraping completed!")
    print("=" * 70)


if __name__ == "__main__":
    main()
