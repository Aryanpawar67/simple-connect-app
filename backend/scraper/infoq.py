import feedparser
from scraper.base import BaseScraper, SkillRecord
from scraper.hackernews import TOOL_PATTERN, STOPWORDS


class InfoqScraper(BaseScraper):
    SOURCE_ID = "infoq"

    async def scrape(self) -> list:
        records = []
        feed_url = self._source_cfg.get("feed_url", "https://feed.infoq.com/")
        max_items = self._source_cfg.get("max_items", 50)

        try:
            resp = await self.get(feed_url)
            feed = feedparser.parse(resp.text)
            for entry in feed.entries[:max_items]:
                title = entry.get("title", "")
                link = entry.get("link", "")
                tags = [t.get("term", "") for t in entry.get("tags", [])]
                # Emit article tags directly as skills
                for tag in tags:
                    if tag and len(tag) > 2:
                        records.append(SkillRecord(
                            skill_name=tag,
                            source=self.SOURCE_ID,
                            url=link,
                            description=title,
                            tags=["infoq"],
                            popularity=0,
                        ))
                # Also extract tool patterns from title
                for match in TOOL_PATTERN.finditer(title):
                    name = match.group(1)
                    if name.lower() not in STOPWORDS and len(name) > 2:
                        records.append(SkillRecord(
                            skill_name=name,
                            source=self.SOURCE_ID,
                            url=link,
                            description=title,
                            tags=["infoq"],
                            popularity=0,
                        ))
        except Exception as exc:
            print(f"[infoq] failed: {exc}")

        return records
