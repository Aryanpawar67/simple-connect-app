import feedparser
from scraper.base import BaseScraper, SkillRecord
from scraper.hackernews import TOOL_PATTERN, STOPWORDS


class DzoneScraper(BaseScraper):
    SOURCE_ID = "dzone"

    async def scrape(self) -> list:
        records = []
        feed_url = self._source_cfg.get("feed_url", "https://feeds.dzone.com/home")
        max_items = self._source_cfg.get("max_items", 50)

        try:
            resp = await self.get(feed_url)
            feed = feedparser.parse(resp.text)
            for entry in feed.entries[:max_items]:
                title = entry.get("title", "")
                link = entry.get("link", "")
                tags = [t.get("term", "") for t in entry.get("tags", [])]
                for tag in tags:
                    if tag and len(tag) > 2:
                        records.append(SkillRecord(
                            skill_name=tag,
                            source=self.SOURCE_ID,
                            url=link,
                            description=title,
                            tags=["dzone"],
                            popularity=0,
                        ))
                for match in TOOL_PATTERN.finditer(title):
                    name = match.group(1)
                    if name.lower() not in STOPWORDS and len(name) > 2:
                        records.append(SkillRecord(
                            skill_name=name,
                            source=self.SOURCE_ID,
                            url=link,
                            description=title,
                            tags=["dzone"],
                            popularity=0,
                        ))
        except Exception as exc:
            print(f"[dzone] failed: {exc}")

        return records
