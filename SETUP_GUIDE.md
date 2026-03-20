# Windows Environment Variable Setup Guide

This guide explains how to set PROXIES and CAPTCHA_API_KEY environment variables on Windows for the Lazada scraper.

---

## Understanding the Proxy Format

The proxy format is: `host:port:username:password`

| Component | Description | Example |
|-----------|-------------|---------|
| `host` | Proxy server IP or hostname | `123.45.67.89` or `my-proxy.com` |
| `port` | Proxy server port number | `8080` or `3128` |
| `username` | Authentication username (optional) | `myuser` |
| `password` | Authentication password (optional) | `mypassword` |

### Example Proxy Formats:

```bash
# Without authentication
123.45.67.89:8080

# With authentication
myuser:mypassword@123.45.67.89:8080

# Multiple proxies (comma-separated)
proxy1.com:8080:user1:pass1,proxy2.com:3128:user2:pass2,proxy3.com:8080
```

---

## Method 1: Windows Command Prompt (cmd.exe)

### Setting PROXIES:

```cmd
set PROXIES=123.45.67.89:8080
```

### Setting with Authentication:

```cmd
set PROXIES=myuser:mypassword@123.45.67.89:8080
```

### Setting Multiple Proxies:

```cmd
set PROXIES=proxy1.com:8080:user1:pass1,proxy2.com:3128:user2:pass2
```

### Setting CAPTCHA_API_KEY:

```cmd
set CAPTCHA_API_KEY=your_2captcha_api_key_here
```

### Verify Variables Are Set:

```cmd
echo %PROXIES%
echo %CAPTCHA_API_KEY%
```

### Limitation:
Variables set with `set` are **temporary** - they only exist for the current command prompt session and are lost when you close the terminal.

---

## Method 2: PowerShell

### Setting Variables:

```powershell
$env:PROXIES = "123.45.67.89:8080"
$env:CAPTCHA_API_KEY = "your_api_key_here"
```

### Setting with Authentication:

```powershell
$env:PROXIES = "myuser:mypassword@123.45.67.89:8080"
```

### Verify Variables:

```powershell
Write-Host $env:PROXIES
Write-Host $env:CAPTCHA_API_KEY
```

---

## Method 3: Python os.environ (Permanent via script)

Create a Python script to set the environment variables:

```python
import os

# Set environment variables
os.environ['PROXIES'] = '123.45.67.89:8080'
os.environ['CAPTCHA_API_KEY'] = 'your_2captcha_api_key'

# Or with authentication
os.environ['PROXIES'] = 'myuser:mypassword@123.45.67.89:8080'

# Verify
print(os.environ.get('PROXIES'))
print(os.environ.get('CAPTCHA_API_KEY'))
```

Save this as `set_env.py` and run it before your scraper:

```cmd
python set_env.py
python advanced_lazada_scraper.py
```

---

## Method 4: Create a Batch Script (Permanent)

Create `run_scraper.bat`:

```batch
@echo off
REM Set your environment variables here
set PROXIES=123.45.67.89:8080
set CAPTCHA_API_KEY=your_api_key_here

REM Run the scraper
python advanced_lazada_scraper.py
```

Run it:
```cmd
run_scraper.bat
```

---

## Method 5: Windows System Settings (Permanent)

### Step-by-step:

1. Press `Win + R` to open Run dialog
2. Type `sysdm.cpl` and press Enter
3. Go to **Advanced** tab
4. Click **Environment Variables**
5. Under "User variables" or "System variables", click **New**
6. Variable name: `PROXIES`
7. Variable value: `123.45.67.89:8080`
8. Repeat for `CAPTCHA_API_KEY`
9. Click OK on all dialogs
10. **Restart your terminal** for changes to take effect

---

## Method 6: Using .env File (Recommended)

Create a `.env` file in your project folder:

```env
PROXIES=123.45.67.89:8080
CAPTCHA_API_KEY=your_2captcha_api_key
```

Then install python-dotenv:

```cmd
pip install python-dotenv
```

In your Python code:

```python
from dotenv import load_dotenv
import os

# Load .env file
load_dotenv()

# Get variables
proxies = os.getenv('PROXIES')
api_key = os.getenv('CAPTCHA_API_KEY')

print(f"Proxies: {proxies}")
print(f"API Key: {api_key}")
```

---

## Complete Setup Example

### 1. Create `.env` file:

```env
PROXIES=myproxy.com:8080:myuser:mypass123
CAPTCHA_API_KEY=1a2b3c4d5e6f7g8h9i0j
MIN_REQUEST_INTERVAL=5
MAX_REQUEST_INTERVAL=15
MAX_RETRIES=3
```

### 2. Install python-dotenv:

```cmd
pip install python-dotenv
```

### 3. Run scraper:

```cmd
python advanced_lazada_scraper.py
```

---

## Common Proxy Providers and Formats

| Provider | Format | Example |
|----------|--------|---------|
| Bright Data | host:port:username:password | `zproxy.lum-datacenter.com:12345:user:pass` |
| Oxylabs | host:port:username:password | `pr.oxylabs.io:7777:user:pass` |
| SmartProxy | host:port:username:password | `gate.smartproxy.com:7000:user:pass` |
| Microleaves | host:port:username:password | `45.67.89.10:6000:user:pass` |
| SmartDNS Proxy | host:port:username:password | `eu.smartdnsproxy.com:6060:user:pass` |

---

## Troubleshooting

### Verify proxy is working:

```python
import requests

proxies = {
    'http': 'http://user:pass@host:port',
    'https': 'http://user:pass@host:port'
}

try:
    response = requests.get('https://httpbin.org/ip', proxies=proxies, timeout=10)
    print(response.json())
except Exception as e:
    print(f"Proxy error: {e}")
```

### Check if environment variable is set:

```cmd
# In CMD
echo %PROXIES%

# In PowerShell
$env:PROXIES

# In Python
import os
print(os.environ.get('PROXIES'))
```

---

## Security Note

Never commit your API keys or proxy credentials to version control!

Add to `.gitignore`:
```
.env
*.log
sessions/
cookies/
```
