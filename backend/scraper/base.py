import asyncio
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import date
from typing import Optional
import httpx
import yaml


# ── Data contract ──────────────────────────────────────────────────────────────

@dataclass
class SkillRecord:
    """Single raw skill extracted by a scraper. Processor enriches this later."""
    skill_name: str                       # raw name as found in source
    source: str                           # scraper identifier (e.g. "github_trending")
    url: str = ""                         # canonical URL for this skill
    description: str = ""
    language: str = ""                    # primary language if applicable
    tags: list = field(default_factory=list)
    popularity: int = 0                   # raw signal (stars, downloads, mentions)
    date_found: date = field(default_factory=date.today)

    # These fields are filled by processor, not scrapers:
    category: str = ""
    subcategory: str = ""
    skill_type: str = ""
    confidence_score: float = 0.0
    first_seen: Optional[date] = None
    is_new: bool = True


# ── Rate limiter ───────────────────────────────────────────────────────────────

class RateLimiter:
    """Simple delay-based rate limiter. Call await limiter.acquire() before each request."""

    def __init__(self, delay_seconds: float = 1.5):
        self._delay = delay_seconds
        self._last_call: float = 0.0

    async def acquire(self):
        now = time.monotonic()
        wait = self._delay - (now - self._last_call)
        if wait > 0:
            await asyncio.sleep(wait)
        self._last_call = time.monotonic()


# ── Base scraper ───────────────────────────────────────────────────────────────

class BaseScraper(ABC):
    """
    All scrapers inherit this. Subclasses implement scrape() and return
    list[SkillRecord]. The base class provides:
      - async httpx client with headers, timeout, retry
      - rate limiter
      - config loading
    """

    SOURCE_ID: str = ""   # override in subclass, e.g. "github_trending"

    def __init__(self, config: dict):
        self._cfg = config
        self._source_cfg = config.get("sources", {}).get(self.SOURCE_ID, {})
        scraping_cfg = config.get("scraping", {})

        self._rate_limiter = RateLimiter(
            delay_seconds=config.get("rate_limits", {}).get("default_delay_seconds", 1.5)
        )
        self._timeout = scraping_cfg.get("request_timeout_seconds", 15)
        self._max_retries = scraping_cfg.get("max_retries", 3)
        self._retry_backoff = scraping_cfg.get("retry_backoff_seconds", 5)
        self._headers = {
            "User-Agent": scraping_cfg.get("user_agent", "SkillScraper/1.0"),
            "Accept": "application/json, text/html, */*",
        }

    def is_enabled(self) -> bool:
        return self._source_cfg.get("enabled", True)

    async def get(self, url: str, params: dict = None, extra_headers: dict = None) -> httpx.Response:
        """Async GET with rate limiting + exponential retry on 429/5xx."""
        await self._rate_limiter.acquire()
        headers = {**self._headers, **(extra_headers or {})}
        async with httpx.AsyncClient(
            headers=headers,
            timeout=self._timeout,
            follow_redirects=True,
        ) as client:
            for attempt in range(self._max_retries):
                try:
                    response = await client.get(url, params=params)
                    if response.status_code == 429:
                        wait = self._retry_backoff * (2 ** attempt)
                        await asyncio.sleep(wait)
                        continue
                    response.raise_for_status()
                    return response
                except (httpx.RequestError, httpx.HTTPStatusError) as exc:
                    if attempt == self._max_retries - 1:
                        raise
                    await asyncio.sleep(self._retry_backoff * (2 ** attempt))
            raise RuntimeError(f"Max retries exceeded for {url}")

    @abstractmethod
    async def scrape(self) -> list:
        """
        Fetch data from the source, extract raw SkillRecords.
        Do NOT classify or score — that happens in processor/.
        Return empty list on total failure (log the error, don't crash).
        """
        ...
