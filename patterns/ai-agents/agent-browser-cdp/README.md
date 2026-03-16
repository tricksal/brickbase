# agent-browser-cdp

## Was ist das?

Minimaler CDP-Client für AI-Agent Web-Automation. Funktioniert mit jedem CDP-kompatiblen Browser — besonders mit [Lightpanda](https://github.com/lightpanda-io/browser): einem headless Browser der 11x schneller und 9x speichereffizienter als Chrome ist, speziell für AI Agents gebaut.

## Wann benutzen?

- Agent soll Webseiten lesen, scrapen oder navigieren
- Viele Seiten gleichzeitig (concurrent scraping)
- RAM/Performance wichtig (Cloud-Agents, VPS)
- Du willst Playwright/Puppeteer nicht als Dependency

## Kern-Konzept

```
Agent → CDPSession → WebSocket → CDP Browser (Lightpanda/Chrome) → Web
```

CDP (Chrome DevTools Protocol) ist das Standard-Protokoll um Browser zu steuern. Lightpanda implementiert dasselbe Protokoll — 100% kompatibel mit bestehendem Playwright/Puppeteer-Code, aber radikal effizienter.

## Warum Lightpanda statt Chrome?

| | Chrome/Chromium | Lightpanda |
|--|--|--|
| RAM | ~300 MB | ~35 MB (9x weniger) |
| Speed (100 pages) | 11x langsamer | Baseline |
| Startup | ~2-3 Sek | Instant |
| Geschrieben in | C++ | Zig |

Für AI Agents die viele Seiten verarbeiten (Research, Scraping, Testing) ist das ein enormer Unterschied.

## Dependencies

```
aiohttp       # WebSocket CDP connection
httpx         # is_cdp_ready check
lightpanda    # Browser binary (oder Docker)
```

## Quick Start

```bash
# Browser starten (Docker)
docker run -d --name lightpanda -p 9222:9222 lightpanda/browser:nightly

# Oder Binary direkt
./lightpanda --remote-debugging-port 9222
```

```python
from core import browser_session, scrape_text, scrape_multiple

# Einzelne Seite
text = scrape_text("https://example.com")

# Mehrere Seiten parallel
results = scrape_multiple([
    "https://a.com",
    "https://b.com",
    "https://c.com"
])

# Volle Kontrolle
async with browser_session("https://example.com") as browser:
    text = await browser.get_text()
    await browser.click("#button")
    await browser.type_text("#search", "query")
    await browser.screenshot("result.png")
```

## Agent Tool Integration

```python
# Als Tool für einen AI Agent:
def web_fetch_tool(url: str) -> str:
    """Fetch and return visible text from a URL."""
    return scrape_text(url)

# In einem Anthropic Tool:
tools = [{
    "name": "web_fetch",
    "description": "Fetch visible text content from a URL",
    "input_schema": {
        "type": "object",
        "properties": {"url": {"type": "string"}},
        "required": ["url"]
    }
}]

def handle_tool(name, inputs):
    if name == "web_fetch":
        return scrape_text(inputs["url"])
```

## Quelle

- Lightpanda: https://github.com/lightpanda-io/browser
- CDP Spec: https://chromedevtools.github.io/devtools-protocol/
- Extrahiert: 2026-03-16
