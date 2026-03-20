#!/usr/bin/env python3
"""
PCSO Lottery Results Web Application

Flask backend API for PCSO lottery results search interface.
Integrates with the Selenium scraper to provide lottery results via REST API.

Author: Web Scraper
Version: 1.0.0
"""

import json
import logging
import sys
import time
import threading
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any
from functools import lru_cache

from flask import Flask, request, jsonify, render_template
from flask_cors import CORS
from dataclasses import dataclass, field

# Import the Selenium scraper components
from pcso_selenium_scraper import (
    PCSOSeleniumScraper,
    ScraperConfig,
    LotteryResult,
    DailyResults,
    OutputFormatter,
    setup_console_encoding
)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler('pcso_app.log', encoding='utf-8')
    ]
)
logger = logging.getLogger(__name__)

# ============================================================================
# PERFORMANCE OPTIMIZATIONS
# ============================================================================

class ResultCache:
    """Simple in-memory cache for lottery results."""
    
    def __init__(self, max_age_seconds: int = 300):  # 5 minutes default
        self._cache: Dict[str, Dict[str, Any]] = {}
        self._timestamps: Dict[str, float] = {}
        self._max_age = max_age_seconds
        self._lock = threading.Lock()
    
    def _make_key(self, from_date: str, to_date: str, game: str) -> str:
        return f"{from_date}:{to_date}:{game}"
    
    def get(self, from_date: str, to_date: str, game: str) -> Optional[List[Dict]]:
        """Get cached results if not expired."""
        key = self._make_key(from_date, to_date, game)
        with self._lock:
            if key in self._cache:
                age = time.time() - self._timestamps.get(key, 0)
                if age < self._max_age:
                    logger.info(f"Cache hit for {key} (age: {age:.1f}s)")
                    return self._cache[key]
                else:
                    # Expired - remove it
                    del self._cache[key]
                    del self._timestamps[key]
        return None
    
    def set(self, from_date: str, to_date: str, game: str, data: List[Dict]) -> None:
        """Cache the results."""
        key = self._make_key(from_date, to_date, game)
        with self._lock:
            self._cache[key] = data
            self._timestamps[key] = time.time()
    
    def clear(self) -> None:
        """Clear all cached results."""
        with self._lock:
            self._cache.clear()
            self._timestamps.clear()


class PersistentScraper:
    """Manages a persistent Selenium WebDriver for reuse."""
    
    _instance = None
    _lock = threading.Lock()
    
    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance
    
    def __init__(self):
        if not self._initialized:
            self._scraper: Optional[PCSOSeleniumScraper] = None
            self._config = ScraperConfig(
                headless=True,
                max_retries=2,  # Reduced for speed
                use_emoji=False,
                fetch_yesterday=False,
                fetch_today=False,
            )
            self._initialized = True
            self._scraper_lock = threading.Lock()
    
    def get_scraper(self) -> Optional[PCSOSeleniumScraper]:
        """Get or create a scraper instance."""
        with self._scraper_lock:
            if self._scraper is None:
                logger.info("Initializing scraper...")
                self._scraper = PCSOSeleniumScraper(self._config)
                if not self._scraper.initialize():
                    logger.error("Failed to initialize persistent scraper")
                    self._scraper = None
                    return None
                logger.info("Persistent scraper initialized")
            return self._scraper
    
    def close(self) -> None:
        """Close the scraper."""
        with self._scraper_lock:
            if self._scraper:
                self._scraper.close()
                self._scraper = None
                logger.info("Persistent scraper closed")


# Initialize cache and scraper
result_cache = ResultCache(max_age_seconds=300)  # 5 minute cache
persistent_scraper = PersistentScraper()

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler('pcso_app.log', encoding='utf-8')
    ]
)
logger = logging.getLogger(__name__)

# Initialize Flask app
app = Flask(__name__)
CORS(app)  # Enable CORS for frontend-backend communication

# ============================================================================
# DATA TRANSFORMATIONS
# ============================================================================

def transform_results_to_table_format(results: Dict[str, DailyResults], game_filter: str = "ALL") -> List[Dict[str, Any]]:
    """
    Transform scraper results to table-friendly format.
    
    Args:
        results: Dictionary of daily results from scraper
        game_filter: Filter by game name, or "ALL" for all games
        
    Returns:
        List of result dictionaries for table display
    """
    table_data: List[Dict[str, Any]] = []
    
    for date_str, daily in results.items():
        if daily.error or not daily.results:
            continue
            
        for result in daily.results:
            # Apply game filter
            if game_filter != "ALL" and result.game_name != game_filter:
                continue
                
            # Format jackpot
            jackpot = result.jackpot_prize if result.jackpot_prize else "-"
            
            # Format winners
            winners = result.winners if result.winners else "-"
            
            # Format date
            try:
                date_obj = datetime.strptime(daily.date, "%Y-%m-%d")
                formatted_date = date_obj.strftime("%B %d, %Y")
            except Exception:
                formatted_date = daily.date
            
            table_data.append({
                "game_name": result.game_name,
                "combinations": result.winning_numbers,
                "draw_date": formatted_date,
                "jackpot": jackpot,
                "winners": winners,
            })
    
    # Sort by date (newest first)
    table_data.sort(key=lambda x: x["draw_date"], reverse=True)
    
    return table_data


# ============================================================================
# API ROUTES
# ============================================================================

@app.route('/')
def index():
    """Render the main page."""
    return render_template('index.html')


@app.route('/api/lottery-games')
def get_lottery_games():
    """Return list of available lottery games."""
    games = [
        {"id": "ALL", "name": "ALL GAMES"},
        {"id": "6/58", "name": "6/58 Ultra Lotto"},
        {"id": "6/55", "name": "6/55 Grand Lotto"},
        {"id": "6/49", "name": "6/49 Super Lotto"},
        {"id": "6/45", "name": "6/45 Mega Lotto"},
        {"id": "6/42", "name": "6/42 Lotto"},
        {"id": "6D", "name": "6D Lotto"},
        {"id": "4D", "name": "4D Lotto"},
        {"id": "3D", "name": "3D Lotto"},
        {"id": "2D", "name": "2D Lotto"},
        {"id": "STL", "name": "STL (Small Town Lottery)"},
    ]
    return jsonify(games)


@app.route('/api/lottery-results', methods=['POST'])
def get_lottery_results():
    """
    API endpoint to fetch lottery results.
    
    Request body:
    {
        "from_date": "2024-01-01",
        "to_date": "2024-01-15",
        "game": "ALL" or specific game like "6/58"
    }
    
    Returns:
    {
        "success": true/false,
        "data": [...],  // Array of results
        "message": "..." // Error message if failed
    }
    """
    try:
        # Parse request
        data = request.get_json()
        
        if not data:
            return jsonify({
                "success": False,
                "data": [],
                "message": "Invalid request. Please provide search criteria."
            }), 400
        
        from_date = data.get('from_date', '')
        to_date = data.get('to_date', '')
        game_filter = data.get('game', 'ALL')
        
        # Validate dates
        if not from_date or not to_date:
            return jsonify({
                "success": False,
                "data": [],
                "message": "Please provide both FROM DATE and TO DATE."
            }), 400
        
        try:
            from_datetime = datetime.strptime(from_date, "%Y-%m-%d")
            to_datetime = datetime.strptime(to_date, "%Y-%m-%d")
        except ValueError:
            return jsonify({
                "success": False,
                "data": [],
                "message": "Invalid date format. Use YYYY-MM-DD."
            }), 400
        
        # Validate date range
        if from_datetime > to_datetime:
            return jsonify({
                "success": False,
                "data": [],
                "message": "FROM DATE cannot be after TO DATE."
            }), 400
        
        # Limit date range to prevent long scraping sessions
        max_days = 30
        if (to_datetime - from_datetime).days > max_days:
            return jsonify({
                "success": False,
                "data": [],
                "message": f"Date range cannot exceed {max_days} days."
            }), 400
        
        logger.info(f"Fetching lottery results: {from_date} to {to_date}, game: {game_filter}")
        
        # Check cache first
        cached = result_cache.get(from_date, to_date, game_filter)
        if cached is not None:
            return jsonify({
                "success": True,
                "data": cached,
                "message": f"Found {len(cached)} results (cached)"
            })
        
        # Use persistent scraper
        scraper = persistent_scraper.get_scraper()
        
        if not scraper:
            return jsonify({
                "success": False,
                "data": [],
                "message": "Failed to initialize scraper. Please try again."
            }), 500
        
        # Fetch results for date range
        results = scraper.get_results_for_date_range(from_datetime, to_datetime)
        
        # Transform to table format
        table_data = transform_results_to_table_format(results, game_filter)
        
        # Cache the results
        result_cache.set(from_date, to_date, game_filter, table_data)
        
        logger.info(f"Found {len(table_data)} results")
        
        return jsonify({
            "success": True,
            "data": table_data,
            "message": f"Found {len(table_data)} results"
        })
        
    except Exception as e:
        logger.exception("Error fetching lottery results")
        return jsonify({
            "success": False,
            "data": [],
            "message": f"An error occurred: {str(e)}"
        }), 500


@app.route('/api/latest-results')
def get_latest_results():
    """
    Get the latest lottery results (yesterday and today).
    
    Returns results for all games. Uses cache for faster responses.
    """
    try:
        # Use cache key for latest results
        today = datetime.now().strftime("%Y-%m-%d")
        yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
        
        # Check cache
        cached = result_cache.get(yesterday, today, "ALL")
        if cached is not None:
            return jsonify({
                "success": True,
                "data": cached,
                "message": f"Found {len(cached)} results (cached)"
            })
        
        # Use persistent scraper
        scraper = persistent_scraper.get_scraper()
        
        if not scraper:
            return jsonify({
                "success": False,
                "data": [],
                "message": "Failed to initialize scraper"
            }), 500
        
        # Configure for latest results
        scraper.config.fetch_yesterday = True
        scraper.config.fetch_today = True
        
        results = scraper.get_latest_results()
        table_data = transform_results_to_table_format(results, "ALL")
        
        # Cache the results
        result_cache.set(yesterday, today, "ALL", table_data)
        
        return jsonify({
            "success": True,
            "data": table_data,
            "message": f"Found {len(table_data)} results"
        })
    
    except Exception as e:
        logger.exception("Error fetching latest results")
        return jsonify({
            "success": False,
            "data": [],
            "message": f"An error occurred: {str(e)}"
        }), 500


@app.route('/api/clear-cache', methods=['POST'])
def clear_cache():
    """Clear the result cache."""
    result_cache.clear()
    return jsonify({
        "success": True,
        "message": "Cache cleared successfully"
    })


# ============================================================================
# ERROR HANDLERS
# ============================================================================

@app.errorhandler(404)
def not_found(error):
    return jsonify({
        "success": False,
        "data": [],
        "message": "Endpoint not found"
    }), 404


@app.errorhandler(500)
def internal_error(error):
    return jsonify({
        "success": False,
        "data": [],
        "message": "Internal server error"
    }), 500


# ============================================================================
# MAIN
# ============================================================================

if __name__ == '__main__':
    print("\n" + "=" * 60)
    print("PCSO Lottery Results Web Application")
    print("=" * 60)
    print("\nStarting server...")
    print("Open http://localhost:5000 in your browser\n")
    
    # Run Flask app without debug mode for better performance
    # Use threaded=True to handle multiple requests
    app.run(debug=False, host='0.0.0.0', port=5000, threaded=True)
