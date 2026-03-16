"""
agent-browser-cdp — Lightweight headless browser control via CDP for AI agents.

Works with any CDP-compatible browser: Lightpanda (11x faster, 9x less RAM),
Chromium, or remote browser via Docker.

Brickbase Pattern: github.com/tricksal/brickbase
Source: https://github.com/lightpanda-io/browser
"""

import asyncio
import json
import subprocess
import time
from contextlib import asynccontextmanager
from typing import Any

import httpx


class CDPSession:
    """
    Minimal CDP (Chrome DevTools Protocol) client for AI agent web automation.
    Connects to any CDP-compatible browser (Lightpanda, Chrome, Puppeteer, etc.)
    """

    def __init__(self, host: str = "localhost", port: int = 9222):
        self.base_url = f"http://{host}:{port}"
        self._ws_url: str | None = None
        self._session: Any = None  # aiohttp/websocket session

    async def connect(self, url: str | None = None) -> None:
        """Connect to browser and open a tab for the given URL."""
        import aiohttp

        # List available targets
        async with aiohttp.ClientSession() as http:
            async with http.get(f"{self.base_url}/json/list") as resp:
                targets = await resp.json()

        if not targets:
            # Open new tab
            async with aiohttp.ClientSession() as http:
                async with http.get(f"{self.base_url}/json/new") as resp:
                    target = await resp.json()
        else:
            target = targets[0]

        self._ws_url = target["webSocketDebuggerUrl"]
        self._session = aiohttp.ClientSession()
        self._ws = await self._session.ws_connect(self._ws_url)
        self._msg_id = 0
        self._responses: dict[int, asyncio.Future] = {}
        asyncio.create_task(self._recv_loop())

        if url:
            await self.navigate(url)

    async def _recv_loop(self) -> None:
        async for msg in self._ws:
            data = json.loads(msg.data)
            if "id" in data:
                fut = self._responses.pop(data["id"], None)
                if fut and not fut.done():
                    fut.set_result(data.get("result", {}))

    async def send(self, method: str, params: dict | None = None) -> dict:
        """Send a CDP command and wait for the response."""
        self._msg_id += 1
        msg_id = self._msg_id
        fut: asyncio.Future = asyncio.get_event_loop().create_future()
        self._responses[msg_id] = fut
        await self._ws.send_str(json.dumps({
            "id": msg_id, "method": method, "params": params or {}
        }))
        return await asyncio.wait_for(fut, timeout=30)

    async def navigate(self, url: str) -> None:
        await self.send("Page.navigate", {"url": url})
        await self.send("Page.loadEventFired")  # Wait for page load

    async def get_text(self) -> str:
        """Get all visible text from the current page."""
        result = await self.send("Runtime.evaluate", {
            "expression": "document.body.innerText",
            "returnByValue": True
        })
        return result.get("result", {}).get("value", "")

    async def get_html(self) -> str:
        """Get full page HTML."""
        result = await self.send("Runtime.evaluate", {
            "expression": "document.documentElement.outerHTML",
            "returnByValue": True
        })
        return result.get("result", {}).get("value", "")

    async def evaluate(self, js: str) -> Any:
        """Execute JavaScript and return the result."""
        result = await self.send("Runtime.evaluate", {
            "expression": js,
            "returnByValue": True,
            "awaitPromise": True
        })
        return result.get("result", {}).get("value")

    async def click(self, selector: str) -> None:
        """Click an element by CSS selector."""
        await self.evaluate(f'document.querySelector("{selector}").click()')

    async def type_text(self, selector: str, text: str) -> None:
        """Focus an input and type text."""
        await self.evaluate(
            f'document.querySelector("{selector}").focus();'
            f'document.querySelector("{selector}").value = {json.dumps(text)};'
        )

    async def screenshot(self, path: str) -> None:
        """Capture a screenshot and save to file."""
        result = await self.send("Page.captureScreenshot", {"format": "png"})
        import base64
        with open(path, "wb") as f:
            f.write(base64.b64decode(result["data"]))

    async def close(self) -> None:
        if self._ws:
            await self._ws.close()
        if self._session:
            await self._session.close()


@asynccontextmanager
async def browser_session(url: str | None = None, cdp_port: int = 9222):
    """
    Context manager for a browser session.

    Usage:
        async with browser_session("https://example.com") as browser:
            text = await browser.get_text()
    """
    session = CDPSession(port=cdp_port)
    try:
        await session.connect(url)
        yield session
    finally:
        await session.close()


def start_lightpanda(port: int = 9222) -> subprocess.Popen:
    """
    Start a local Lightpanda browser process.
    Requires lightpanda binary in PATH or current directory.

    Returns the process (call .terminate() when done).
    """
    proc = subprocess.Popen(
        ["lightpanda", "--remote-debugging-port", str(port)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL
    )
    time.sleep(0.3)  # Brief pause for startup (much faster than Chromium)
    return proc


def is_cdp_ready(host: str = "localhost", port: int = 9222, timeout: float = 5.0) -> bool:
    """Check if a CDP browser is ready to accept connections."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            resp = httpx.get(f"http://{host}:{port}/json/version", timeout=1.0)
            if resp.status_code == 200:
                return True
        except Exception:
            pass
        time.sleep(0.1)
    return False


# --- Convenience: sync scraping for simple agent tools ---

def scrape_text(url: str, cdp_port: int = 9222) -> str:
    """
    Synchronously scrape visible text from a URL.
    Requires a running CDP browser on cdp_port.

    Usage:
        text = scrape_text("https://example.com")
    """
    async def _run():
        async with browser_session(url, cdp_port) as b:
            return await b.get_text()
    return asyncio.run(_run())


def scrape_multiple(urls: list[str], cdp_port: int = 9222) -> dict[str, str]:
    """
    Scrape multiple URLs concurrently. Returns {url: text} dict.
    Much faster than sequential scraping.

    Usage:
        results = scrape_multiple(["https://a.com", "https://b.com"])
    """
    async def _run():
        async def fetch(url):
            async with browser_session(url, cdp_port) as b:
                text = await b.get_text()
                return url, text

        tasks = [fetch(url) for url in urls]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        return {
            url: (text if not isinstance(text, Exception) else f"ERROR: {text}")
            for url, text in results
        }
    return asyncio.run(_run())


if __name__ == "__main__":
    # Quick test: scrape a page
    import sys
    url = sys.argv[1] if len(sys.argv) > 1 else "https://example.com"
    port = int(sys.argv[2]) if len(sys.argv) > 2 else 9222

    if not is_cdp_ready(port=port):
        print(f"No CDP browser on port {port}. Start with: docker run -d -p {port}:9222 lightpanda/browser:nightly")
        sys.exit(1)

    print(f"Scraping {url}...")
    text = scrape_text(url, port)
    print(text[:500])
