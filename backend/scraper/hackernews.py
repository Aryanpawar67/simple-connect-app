import re
import feedparser
from scraper.base import BaseScraper, SkillRecord

# Regex: captures words that look like tool names (CamelCase, all-caps, or known tech suffixes)
TOOL_PATTERN = re.compile(
    r'\b([A-Z][a-z]+(?:[A-Z][a-z]+)+|[A-Z]{2,}(?:[a-z]+)?|'
    r'\w+(?:\.js|\.py|\.io|DB|OS|AI|ML|QL|CD|CI|API|SDK|CLI|ORM|LLM))\b'
)

# Common words that match the pattern but are not tools
STOPWORDS = {
    "show", "ask", "tell", "this", "that", "with", "from", "into",
    "have", "been", "what", "when", "where", "which", "about", "over",
    "your", "their", "some", "more", "also", "than", "like", "just",
    "they", "then", "first", "last", "will", "would", "could", "should",
    "using", "makes", "based", "built", "open", "free", "fast", "next",
    "after", "before", "every", "many", "much", "such", "each", "both",
}


class HackerNewsScraper(BaseScraper):
    SOURCE_ID = "hackernews"

    async def scrape(self) -> list:
        records = []
        feed_url = self._source_cfg.get("feed_url", "https://hnrss.org/frontpage")
        max_items = self._source_cfg.get("max_items", 60)

        try:
            resp = await self.get(feed_url)
            feed = feedparser.parse(resp.text)
            for entry in feed.entries[:max_items]:
                title = entry.get("title", "")
                link = entry.get("link", "")
                summary = entry.get("summary", "")
                combined = f"{title} {summary}"
                for match in TOOL_PATTERN.finditer(combined):
                    name = match.group(1)
                    if len(name) < 2 or name.lower() in STOPWORDS:
                        continue
                    records.append(SkillRecord(
                        skill_name=name,
                        source=self.SOURCE_ID,
                        url=link,
                        description=title,
                        tags=[],
                        popularity=0,
                    ))
        except Exception as exc:
            print(f"[hackernews] failed: {exc}")

        return records
