import feedparser
from scraper.base import BaseScraper, SkillRecord


class ProductHuntScraper(BaseScraper):
    SOURCE_ID = "product_hunt"

    async def scrape(self) -> list:
        records = []
        feed_url = self._source_cfg.get("feed_url", "https://www.producthunt.com/feed")
        max_items = self._source_cfg.get("max_items", 50)

        try:
            resp = await self.get(feed_url)
            feed = feedparser.parse(resp.text)
            for entry in feed.entries[:max_items]:
                title = entry.get("title", "")
                link = entry.get("link", "")
                summary = entry.get("summary", "")
                if not title:
                    continue
                # Product Hunt titles are "Product Name — tagline" or "Product Name - tagline"
                product_name = title.split("—")[0].split(" - ")[0].strip()
                if not product_name:
                    continue
                records.append(SkillRecord(
                    skill_name=product_name,
                    source=self.SOURCE_ID,
                    url=link,
                    description=summary[:300],
                    tags=["product-hunt"],
                    popularity=0,
                ))
        except Exception as exc:
            print(f"[product_hunt] failed: {exc}")

        return records
