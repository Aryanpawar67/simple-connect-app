import re
import feedparser
from scraper.base import BaseScraper, SkillRecord

# Captures quoted terms, CamelCase model names, and known AI/CS suffixes
ARXIV_TOOL_PATTERN = re.compile(
    r'"([^"]{3,40})"'
    r'|([A-Z][A-Za-z0-9]{2,}(?:-[A-Z][A-Za-z0-9]+)*)'
    r'|(\w+(?:Bert|GPT|LLM|ViT|Net|GAN|VAE|Former|Mamba|CLIP)\w*)'
)

_ARXIV_STOP = {
    "We", "The", "Our", "This", "In", "To", "For", "On", "An", "A",
    "With", "By", "From", "That", "It", "Is", "Are", "Has", "Have",
    "New", "Large", "Small", "Deep", "High", "Low", "Fast", "Efficient",
}


class ArxivScraper(BaseScraper):
    SOURCE_ID = "arxiv"

    async def scrape(self) -> list:
        records = []
        feeds = self._source_cfg.get("feeds", [])
        max_items = self._source_cfg.get("max_items_per_feed", 40)

        for feed_url in feeds:
            try:
                resp = await self.get(feed_url)
                feed = feedparser.parse(resp.text)
                for entry in feed.entries[:max_items]:
                    title = entry.get("title", "")
                    link = entry.get("link", "")
                    for match in ARXIV_TOOL_PATTERN.finditer(title):
                        name = next((g for g in match.groups() if g), None)
                        if not name or len(name) < 3 or name in _ARXIV_STOP:
                            continue
                        records.append(SkillRecord(
                            skill_name=name,
                            source=self.SOURCE_ID,
                            url=link,
                            description=title,
                            tags=["research", "arxiv"],
                            popularity=0,
                        ))
            except Exception as exc:
                print(f"[arxiv] feed={feed_url} failed: {exc}")

        return records
