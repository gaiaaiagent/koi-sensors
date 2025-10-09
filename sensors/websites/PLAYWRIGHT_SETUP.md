# Playwright Setup for Website Sensor

This guide explains how to set up and use Playwright for capturing JavaScript-rendered content from websites like regentokenomics.org.

## What Changed

The website sensor now has **optional Playwright support** for sites that use JavaScript to render content (like Notion-based sites). This allows it to:

1. **Render JavaScript**: Execute JavaScript and get the final DOM
2. **Expand toggles**: Auto-click Notion-style collapsible blocks to reveal hidden content
3. **Wait for content**: Allow time for lazy-loaded content to appear

## Installation

### 1. Install Python dependencies

```bash
cd /opt/projects/koi-sensors/sensors/websites
source venv/bin/activate
pip install playwright>=1.40.0
```

### 2. Install Playwright browsers

```bash
playwright install chromium
```

This downloads the Chromium browser (~200MB) that Playwright will use.

## Configuration

### Enabling Playwright for specific domains

Edit `config.yaml` or your website sensor configuration:

```yaml
websites:
  - url: "https://regentokenomics.org"
    check_interval: 3600

# Playwright settings
playwright_domains:
  - regentokenomics.org
playwright_expand_toggles: true  # Auto-expand Notion toggles
playwright_wait_time: 3000  # Wait 3 seconds for content to load
```

### Enabling Playwright for all sites (not recommended)

```yaml
use_playwright: true  # Use Playwright for ALL sites (slower)
```

## Testing

Test Playwright setup with the test script:

```bash
cd /opt/projects/koi-sensors/sensors/websites
source venv/bin/activate
python3 test_playwright.py
```

Expected output:
```
✅ Playwright initialized
📜 Fetching: https://regentokenomics.org/weekly-meetups/oct-7
✅ Fetched XXX characters of HTML
📝 Extracted XXX characters of text
...content preview...
✅ SUCCESS: Appears to have captured expanded content!
```

## How It Works

### 1. Domain Detection

When the sensor processes a URL, it checks if the domain is in `playwright_domains`:

```python
# regentokenomics.org URLs will use Playwright
# Other URLs will use regular HTTP
```

### 2. JavaScript Rendering

Playwright launches a headless Chromium browser and:
- Navigates to the page
- Waits for network to be idle
- Waits additional time (default: 3 seconds) for content to load

### 3. Toggle Expansion

If `playwright_expand_toggles: true`, the sensor automatically:
- Finds all collapsible/toggle elements using common selectors:
  - `details:not([open])`
  - `[class*="toggle"]`
  - `[class*="collaps"]`
  - `[aria-expanded="false"]`
- Clicks each one to expand it
- Waits for animations to complete

### 4. Content Extraction

After rendering and expanding toggles:
- Gets the full HTML with `page.content()`
- Parses with BeautifulSoup
- Extracts text using existing `extract_clean_content()` method

## Troubleshooting

### "Playwright not installed"

```bash
pip install playwright
playwright install chromium
```

### "Failed to launch browser"

Try with additional flags:
```python
playwright_headless: true
playwright_args:
  - --no-sandbox
  - --disable-setuid-sandbox
```

### "Content still seems limited"

1. Increase wait time: `playwright_wait_time: 5000` (5 seconds)
2. Check the test script output to see what's being captured
3. Verify the toggles are actually expanding (check logs for "Found X elements")

### Resource Usage

Playwright uses more resources than HTTP requests:
- **Memory**: ~100-200MB per browser instance
- **CPU**: Higher during page rendering
- **Time**: 3-10 seconds per page vs <1 second for HTTP

**Recommendation**: Only enable for domains that actually need it (like Notion-based sites).

## Performance Tips

1. **Use domain whitelist**: Only enable Playwright for sites that need it
2. **Adjust wait time**: Lower `playwright_wait_time` if content loads quickly
3. **Limit concurrent pages**: Playwright pages are reused from same browser context
4. **Monitor logs**: Watch for "Using Playwright for..." to see when it activates

## Next Steps

After setup and testing:

1. **Restart website sensor** to apply changes
2. **Watch logs** for Playwright activity:
   ```bash
   tail -f /opt/projects/koi-sensors/sensors/websites/website_sensor.log
   ```
3. **Verify content** is being captured in database
4. **Check weekly digest** to see improved content from regentokenomics.org

## Rollback

If you need to disable Playwright:

```yaml
# Remove or comment out
playwright_domains: []
# OR
use_playwright: false
```

The sensor will fall back to regular HTTP fetching automatically.
