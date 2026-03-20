#!/usr/bin/env python3
"""
Lazada Product Scraper
Specialized scraper for Lazada product pages with comprehensive data extraction.
"""

import json
import time
import logging
from datetime import datetime
from typing import Dict, List, Optional, Any

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Try to import required packages
try:
    from selenium import webdriver  # type: ignore
    from selenium.webdriver.chrome.options import Options  # type: ignore
    from selenium.webdriver.chrome.service import Service  # type: ignore
    from selenium.webdriver.common.by import By  # type: ignore
    from selenium.webdriver.support.ui import WebDriverWait  # type: ignore
    from selenium.webdriver.support import expected_conditions as EC  # type: ignore
    from webdriver_manager.chrome import ChromeDriverManager  # type: ignore
    from bs4 import BeautifulSoup  # type: ignore
    SELENIUM_AVAILABLE = True
except ImportError as e:
    logger.error(f"Missing dependency: {e}")
    SELENIUM_AVAILABLE = False


class LazadaScraper:
    """Specialized scraper for Lazada product pages."""
    
    def __init__(self):
        self.driver: Any = None
        self.product_data: Dict[str, Any] = {}
        
    def _init_driver(self):
        """Initialize Chrome driver with anti-detection settings."""
        chrome_options = Options()
        chrome_options.add_argument("--headless")
        chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument("--disable-dev-shm-usage")
        chrome_options.add_argument("--disable-gpu")
        chrome_options.add_argument("--window-size=1920,1080")
        chrome_options.add_argument("--disable-blink-features=AutomationControlled")
        chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
        chrome_options.add_experimental_option('useAutomationExtension', False)
        chrome_options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
        
        self.driver = webdriver.Chrome(
            service=Service(ChromeDriverManager().install()),
            options=chrome_options
        )
        
        # Anti-detection measures
        self.driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {
            "source": """
                Object.defineProperty(navigator, 'webdriver', {
                    get: () => undefined
                })
            """
        })
        
    def scrape(self, url: str) -> Dict[str, Any]:
        """
        Scrape a Lazada product page.
        
        Args:
            url: Lazada product URL
            
        Returns:
            Dictionary containing all scraped product data
        """
        if not SELENIUM_AVAILABLE:
            return {"error": "Selenium not available. Please install: pip install selenium webdriver-manager"}
        
        logger.info(f"Starting scrape of: {url}")
        
        try:
            self._init_driver()
            self.driver.get(url)
            
            # Wait for page to load
            time.sleep(5)
            
            # Scroll to load dynamic content
            self._scroll_page()
            
            # Get page source after JavaScript execution
            page_source = self.driver.page_source
            soup = BeautifulSoup(page_source, "lxml")
            
            # Extract all product data
            self.product_data = {
                "url": url,
                "scrape_timestamp": datetime.now().isoformat(),
                "title": self._extract_title(soup),
                "price": self._extract_price(soup),
                "original_price": self._extract_original_price(soup),
                "discount": self._extract_discount(soup),
                "description": self._extract_description(soup),
                "specifications": self._extract_specifications(soup),
                "images": self._extract_images(soup),
                "seller": self._extract_seller(soup),
                "rating": self._extract_rating(soup),
                "reviews_count": self._extract_reviews_count(soup),
                "variants": self._extract_variants(soup),
                "stock": self._extract_stock(soup),
                "shipping": self._extract_shipping(soup),
                "breadcrumbs": self._extract_breadcrumbs(soup),
            }
            
            logger.info("Scraping completed successfully")
            result = self.product_data
            
        except Exception as e:
            logger.error(f"Error during scraping: {e}")
            result = {"error": str(e)}
            
        finally:
            if self.driver:
                self.driver.quit()
        
        return result
    
    def _scroll_page(self):
        """Scroll the page to load dynamic content."""
        try:
            # Scroll down in increments
            for i in range(3):
                self.driver.execute_script("window.scrollTo(0, document.body.scrollHeight / 3 * (i + 1));")
                time.sleep(2)
            
            # Scroll back to top
            self.driver.execute_script("window.scrollTo(0, 0);")
            time.sleep(1)
            
        except Exception as e:
            logger.warning(f"Error scrolling page: {e}")
    
    def _extract_title(self, soup: BeautifulSoup) -> str:
        """Extract product title."""
        # Try multiple selectors
        selectors = [
            ("h1", {"data-selenium": "product-title"}),
            ("h1", {"class": "pdp-title"}),
            ("h1", {}),
        ]
        
        for tag, attrs in selectors:
            elem = soup.find(tag, attrs)
            if elem:
                title = elem.get_text(strip=True)
                if title:
                    return title
        
        # Try JavaScript-rendered content
        try:
            title = self.driver.find_element(By.CSS_SELECTOR, "h1[data-selenium='product-title']")
            return title.text.strip()
        except:
            pass
        
        return ""
    
    def _extract_price(self, soup: BeautifulSoup) -> str:
        """Extract current price."""
        # Try multiple selectors
        selectors = [
            ("span", {"data-selenium": "product-price"}),
            (".pdp-price", {}),
            ("span", {"class": "price"}),
            ("div", {"class": "price-current"}),
            ("[data-selenium*='price']", {}),
        ]
        
        for tag, attrs in selectors:
            elem = soup.find(tag, attrs)
            if elem:
                price = elem.get_text(strip=True)
                if price:
                    return price
        
        # Try JavaScript - multiple selector attempts
        selectors_js = [
            "[data-selenium='product-price']",
            ".pdp-price",
            ".price-current",
            ".price .number",
            "span[class*='price']",
            "div[class*='price']"
        ]
        
        for selector in selectors_js:
            try:
                price = self.driver.find_element(By.CSS_SELECTOR, selector)
                if price and price.text.strip():
                    return price.text.strip()
            except:
                continue
            
        # Try getting from page source directly
        try:
            import re
            page = self.driver.page_source
            # Try to find price in the HTML
            price_match = re.search(r'"price"\s*:\s*"?([^",}]+)"?', page)
            if price_match:
                return price_match.group(1)
        except:
            pass
            
        return ""
    
    def _extract_original_price(self, soup: BeautifulSoup) -> str:
        """Extract original price (before discount)."""
        selectors = [
            (".pdp-price-regular", {}),
            (".original-price", {}),
            ("span", {"class": "original-price"}),
        ]
        
        for tag, attrs in selectors:
            elem = soup.find(tag, attrs)
            if elem:
                price = elem.get_text(strip=True)
                if price:
                    return price
        return ""
    
    def _extract_discount(self, soup: BeautifulSoup) -> str:
        """Extract discount percentage."""
        selectors = [
            (".pdp-discount", {}),
            (".discount", {}),
            ("span", {"class": "discount"}),
        ]
        
        for tag, attrs in selectors:
            elem = soup.find(tag, attrs)
            if elem:
                discount = elem.get_text(strip=True)
                if discount:
                    return discount
        return ""
    
    def _extract_description(self, soup: BeautifulSoup) -> str:
        """Extract product description."""
        descriptions = []
        
        # Try product details section
        detail_sections = soup.find_all("div", {"class": "detail-content"})
        for section in detail_sections:
            text = section.get_text(separator="\n", strip=True)
            if text and len(text) > 10:
                descriptions.append(text)
        
        # Try HTML description
        desc_elem = soup.find("div", {"class": "pdp-product-detail"})
        if desc_elem:
            text = desc_elem.get_text(separator="\n", strip=True)
            if text:
                descriptions.append(text)
        
        # Try JavaScript rendered
        try:
            desc_elem = self.driver.find_element(By.CSS_SELECTOR, ".detail-content")
            descriptions.append(desc_elem.text)
        except:
            pass
        
        return "\n\n".join(descriptions) if descriptions else ""
    
    def _extract_specifications(self, soup: BeautifulSoup) -> Dict[str, str]:
        """Extract product specifications."""
        specs = {}
        
        # Try specifications table
        spec_sections = soup.find_all("div", {"class": "specification-table"})
        for section in spec_sections:
            rows = section.find_all("tr")
            for row in rows:
                cells = row.find_all(["th", "td"])
                if len(cells) >= 2:
                    key = cells[0].get_text(strip=True)
                    value = cells[1].get_text(strip=True)
                    if key and value:
                        specs[key] = value
        
        # Try key-value pairs
        kv_pairs = soup.find_all("div", {"class": "spec-row"})
        for pair in kv_pairs:
            key_elem = pair.find(["span", "div"], {"class": "spec-label"})
            value_elem = pair.find(["span", "div"], {"class": "spec-value"})
            if key_elem and value_elem:
                key = key_elem.get_text(strip=True)
                value = value_elem.get_text(strip=True)
                if key and value:
                    specs[key] = value
        
        # Try JavaScript rendered
        try:
            spec_rows = self.driver.find_elements(By.CSS_SELECTOR, ".spec-row, .specification-table tr")
            for row in spec_rows[:20]:  # Limit to avoid too many specs
                try:
                    cells = row.find_elements(By.CSS_SELECTOR, "th, td")
                    if len(cells) >= 2:
                        key = cells[0].text.strip()
                        value = cells[1].text.strip()
                        if key and value:
                            specs[key] = value
                except:
                    continue
        except:
            pass
        
        return specs
    
    def _extract_images(self, soup: BeautifulSoup) -> List[str]:
        """Extract product images."""
        images = []
        
        # Try main image gallery
        gallery = soup.find_all("img", {"class": "pdp-img"})
        for img in gallery:
            src = img.get("src") or img.get("data-src")
            if src and src.startswith("http"):
                if src not in images:
                    images.append(src)
        
        # Try thumbnail images
        thumbs = soup.find_all("img", {"class": "thumbnail"})
        for thumb in thumbs:
            src = thumb.get("src") or thumb.get("data-src")
            if src and src.startswith("http"):
                full_src = src.replace("100x100", "800x800").replace("120x120", "800x800")
                if full_src not in images:
                    images.append(full_src)
        
        # Try JavaScript rendered
        try:
            img_elements = self.driver.find_elements(By.CSS_SELECTOR, ".pdp-img, .thumbnails img")
            for img in img_elements[:10]:
                try:
                    src = img.get_attribute("src") or img.get_attribute("data-src")
                    if src and "laz" in src:
                        if src not in images:
                            images.append(src)
                except:
                    continue
        except:
            pass
        
        return images[slice(0, 10)]  # Limit to 10 images
    
    def _extract_seller(self, soup: BeautifulSoup) -> Dict[str, str]:
        """Extract seller information."""
        seller = {"name": "", "rating": "", "location": "", "response_rate": ""}
        
        # Try seller info section
        seller_elem = soup.find("a", {"class": "seller-name"})
        if seller_elem:
            seller["name"] = seller_elem.get_text(strip=True)
        
        # Try seller rating
        rating_elem = soup.find("div", {"class": "seller-rating"})
        if rating_elem:
            seller["rating"] = rating_elem.get_text(strip=True)
        
        # Try location
        location_elem = soup.find("div", {"class": "seller-location"})
        if location_elem:
            seller["location"] = location_elem.get_text(strip=True)
        
        # Try JavaScript rendered
        try:
            name_elem = self.driver.find_element(By.CSS_SELECTOR, ".seller-name, [data-selenium='seller-name']")
            seller["name"] = name_elem.text.strip()
        except:
            pass
        
        try:
            rating_elem = self.driver.find_element(By.CSS_SELECTOR, ".seller-rating, .seller-info__rating")
            seller["rating"] = rating_elem.text.strip()
        except:
            pass
            
        try:
            loc_elem = self.driver.find_element(By.CSS_SELECTOR, ".seller-location, .seller-info__location")
            seller["location"] = loc_elem.text.strip()
        except:
            pass
        
        return seller
    
    def _extract_rating(self, soup: BeautifulSoup) -> str:
        """Extract product rating."""
        # Try rating element
        rating_elem = soup.find("span", {"class": "score"})
        if rating_elem:
            return rating_elem.get_text(strip=True)
        
        # Try JavaScript rendered
        try:
            rating = self.driver.find_element(By.CSS_SELECTOR, "[data-selenium='product-rating'] .score")
            return rating.text.strip()
        except:
            pass
            
        try:
            rating = self.driver.find_element(By.CSS_SELECTOR, ".pdp-review-summary__rating")
            return rating.text.strip()
        except:
            pass
            
        return ""
    
    def _extract_reviews_count(self, soup: BeautifulSoup) -> str:
        """Extract reviews count."""
        # Try reviews count element
        reviews_elem = soup.find("span", {"class": "count"})
        if reviews_elem:
            return reviews_elem.get_text(strip=True)
        
        # Try JavaScript rendered
        try:
            reviews = self.driver.find_element(By.CSS_SELECTOR, "[data-selenium='product-review-count']")
            return reviews.text.strip()
        except:
            pass
            
        try:
            reviews = self.driver.find_element(By.CSS_SELECTOR, ".pdp-review-summary__count")
            return reviews.text.strip()
        except:
            pass
            
        return ""
    
    def _extract_variants(self, soup: BeautifulSoup) -> Dict[str, List[str]]:
        """Extract product variants (size, color, etc.)."""
        variants = {}
        
        # Try variant selectors
        variant_groups = soup.find_all("div", {"class": "variant-selection"})
        
        for group in variant_groups:
            # Try to find variant name (color, size, etc.)
            label_elem = group.find("label")
            if label_elem:
                variant_name = label_elem.get_text(strip=True).lower()
                
                # Find all options
                options = []
                button_elems = group.find_all("button")
                span_elems = group.find_all("span")
                option_elems = button_elems if button_elems else span_elems
                for opt in option_elems:
                    opt_text = opt.get_text(strip=True)
                    if opt_text and opt_text not in options:
                        options.append(opt_text)
                
                if options:
                    variants[variant_name] = options
        
        # Try JavaScript rendered
        try:
            option_groups = self.driver.find_elements(By.CSS_SELECTOR, ".pdp-size-selection, .pdp-color-selection")
            for group in option_groups:
                try:
                    label = group.find_element(By.CSS_SELECTOR, "label, .selection-label")
                    variant_name = label.text.strip().lower().replace(":", "")
                    
                    options = []
                    option_elems = group.find_elements(By.CSS_SELECTOR, "button, .option")
                    for opt in option_elems[:20]:
                        try:
                            opt_text = opt.text.strip()
                            if opt_text and opt_text not in options:
                                options.append(opt_text)
                        except:
                            continue
                    
                    if options:
                        variants[variant_name] = options
                except:
                    continue
        except:
            pass
        
        return variants
    
    def _extract_stock(self, soup: BeautifulSoup) -> str:
        """Extract stock availability."""
        # Try stock element
        stock_elem = soup.find("span", {"class": "stock"})
        if stock_elem:
            return stock_elem.get_text(strip=True)
        
        # Try JavaScript rendered
        try:
            stock = self.driver.find_element(By.CSS_SELECTOR, "[data-selenium='product-quantity']")
            return stock.text.strip()
        except:
            pass
            
        try:
            stock = self.driver.find_element(By.CSS_SELECTOR, ".pdp-product-status")
            return stock.text.strip()
        except:
            pass
            
        return ""
    
    def _extract_shipping(self, soup: BeautifulSoup) -> Dict[str, str]:
        """Extract shipping information."""
        shipping = {"delivery": "", "shipping_fee": "", "free_shipping": ""}
        
        # Try delivery info
        delivery_elem = soup.find("div", {"class": "delivery"})
        if delivery_elem:
            shipping["delivery"] = delivery_elem.get_text(strip=True)
        
        # Try shipping fee
        fee_elem = soup.find("div", {"class": "shipping-fee"})
        if fee_elem:
            shipping["shipping_fee"] = fee_elem.get_text(strip=True)
        
        # Try JavaScript rendered
        try:
            delivery = self.driver.find_element(By.CSS_SELECTOR, ".delivery-content, .pdp-delivery")
            shipping["delivery"] = delivery.text.strip()
        except:
            pass
            
        try:
            fee = self.driver.find_element(By.CSS_SELECTOR, ".shipping-fee")
            shipping["shipping_fee"] = fee.text.strip()
        except:
            pass
        
        return shipping
    
    def _extract_breadcrumbs(self, soup: BeautifulSoup) -> List[str]:
        """Extract breadcrumbs."""
        breadcrumbs = []
        
        # Try breadcrumbs
        nav = soup.find("nav", {"class": "breadcrumb"})
        if nav:
            items = nav.find_all("li")
            for item in items:
                text = item.get_text(strip=True)
                if text and text not in breadcrumbs:
                    breadcrumbs.append(text)
        
        # Try JavaScript rendered
        try:
            bc_items = self.driver.find_elements(By.CSS_SELECTOR, ".breadcrumb li, .pdp-breadcrumb li")
            for item in bc_items:
                text = item.text.strip()
                if text and text not in breadcrumbs:
                    breadcrumbs.append(text)
        except:
            pass
        
        return breadcrumbs


def main():
    """Main function to run the scraper."""
    import sys
    import io
    
    # Set UTF-8 encoding for stdout
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    
    url = "https://www.lazada.com.ph/products/private-chatgpt-grok-claude-midjouney-i3586687905-s20902057389.html"
    
    print("=" * 70)
    print("Lazada Product Scraper")
    print("=" * 70)
    print(f"\nTarget URL: {url}\n")
    
    scraper = LazadaScraper()
    result = scraper.scrape(url)
    
    if "error" in result:
        print(f"ERROR: {result['error']}")
        return
    
    # Print results (without emojis for Windows compatibility)
    print("\n" + "=" * 70)
    print("SCRAPED PRODUCT DATA")
    print("=" * 70)
    
    print(f"\n[PRODUCT TITLE]")
    print(f"   {result.get('title', 'N/A')}")
    
    print(f"\n[PRICE]")
    print(f"   Current: {result.get('price', 'N/A')}")
    print(f"   Original: {result.get('original_price', 'N/A')}")
    print(f"   Discount: {result.get('discount', 'N/A')}")
    
    print(f"\n[RATING]")
    print(f"   Rating: {result.get('rating', 'N/A')}")
    print(f"   Reviews: {result.get('reviews_count', 'N/A')}")
    
    print(f"\n[SELLER]")
    seller = result.get('seller', {})
    print(f"   Name: {seller.get('name', 'N/A')}")
    print(f"   Rating: {seller.get('rating', 'N/A')}")
    print(f"   Location: {seller.get('location', 'N/A')}")
    
    print(f"\n[VARIANTS]")
    variants = result.get('variants', {})
    if variants:
        for name, options in variants.items():
            print(f"   {name.title()}: {', '.join(options)}")
    else:
        print("   No variants found")
    
    print(f"\n[STOCK]")
    print(f"   {result.get('stock', 'N/A')}")
    
    print(f"\n[SHIPPING]")
    shipping = result.get('shipping', {})
    print(f"   Delivery: {shipping.get('delivery', 'N/A')}")
    print(f"   Shipping Fee: {shipping.get('shipping_fee', 'N/A')}")
    
    print(f"\n[IMAGES] ({len(result.get('images', []))} found):")
    for i, img in enumerate(result.get('images', [])[:5], 1):
        print(f"   {i}. {img}")
    
    print(f"\n[SPECIFICATIONS]")
    specs = result.get('specifications', {})
    if specs:
        for key, value in list(specs.items())[slice(0, 10)]:
            print(f"   {key}: {value}")
    else:
        print("   No specifications found")
    
    print(f"\n[DESCRIPTION]")
    desc = result.get('description', '')
    if desc:
        print(f"   {desc[:500]}...")
    else:
        print("   No description found")
    
    print(f"\n[BREADCRUMBS]")
    bc = result.get('breadcrumbs', [])
    if bc:
        print(f"   {' > '.join(bc)}")
    else:
        print("   No breadcrumbs found")
    
    print(f"\n[Scrape Timestamp] {result.get('scrape_timestamp', 'N/A')}")
    
    # Save to JSON
    output_file = "lazada_product_data.json"
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    
    print(f"\n[SUCCESS] Data saved to: {output_file}")
    print("=" * 70)


if __name__ == "__main__":
    main()
