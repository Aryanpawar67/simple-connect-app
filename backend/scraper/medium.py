import feedparser
from scraper.base import BaseScraper, SkillRecord
from scraper.hackernews import TOOL_PATTERN, STOPWORDS


class MediumScraper(BaseScraper):
    SOURCE_ID = "medium"

    async def scrape(self) -> list:
        records = []
        tags = self._source_cfg.get("tags", [])
        max_items = self._source_cfg.get("max_items_per_tag", 15)

        for tag in tags:
            feed_url = f"https://medium.com/feed/tag/{tag}"
            try:
                resp = await self.get(feed_url)
                feed = feedparser.parse(resp.text)
                for entry in feed.entries[:max_items]:
                    title = entry.get("title", "")
                    link = entry.get("link", "")
                    for match in TOOL_PATTERN.finditer(title):
                        name = match.group(1)
                        if name.lower() not in STOPWORDS and len(name) > 2:
                            records.append(SkillRecord(
                                skill_name=name,
                                source=self.SOURCE_ID,
                                url=link,
                                description=title,
                                tags=[tag, "medium"],
                                popularity=0,
                            ))
            except Exception as exc:
                print(f"[medium] tag={tag} failed: {exc}")

        return records
