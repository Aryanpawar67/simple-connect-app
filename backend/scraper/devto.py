from scraper.base import BaseScraper, SkillRecord


class DevtoScraper(BaseScraper):
    SOURCE_ID = "devto"

    async def scrape(self) -> list:
        records = []
        tags = self._source_cfg.get("tags", [])
        max_articles = self._source_cfg.get("max_articles_per_tag", 20)

        for tag in tags:
            try:
                resp = await self.get(
                    "https://dev.to/api/articles",
                    params={"tag": tag, "per_page": max_articles, "top": 7}
                )
                articles = resp.json()
                for article in articles:
                    for article_tag in article.get("tag_list", []):
                        records.append(SkillRecord(
                            skill_name=article_tag,
                            source=self.SOURCE_ID,
                            url=article.get("url", ""),
                            description=article.get("title", ""),
                            tags=article.get("tag_list", []),
                            popularity=(
                                article.get("positive_reactions_count", 0)
                                + article.get("comments_count", 0)
                            ),
                        ))
            except Exception as exc:
                print(f"[devto] tag={tag} failed: {exc}")

        return records
