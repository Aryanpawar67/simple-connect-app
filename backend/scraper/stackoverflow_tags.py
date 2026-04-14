from scraper.base import BaseScraper, SkillRecord


class StackOverflowTagsScraper(BaseScraper):
    SOURCE_ID = "stackoverflow_tags"

    async def scrape(self) -> list:
        records = []
        max_tags = self._source_cfg.get("max_tags", 100)
        sort = self._source_cfg.get("sort", "activity")
        page = 1
        fetched = 0

        while fetched < max_tags:
            page_size = min(100, max_tags - fetched)
            try:
                resp = await self.get(
                    "https://api.stackexchange.com/2.3/tags",
                    params={
                        "site": "stackoverflow",
                        "sort": sort,
                        "order": "desc",
                        "pagesize": page_size,
                        "page": page,
                        "filter": "default",
                    }
                )
                data = resp.json()
                items = data.get("items", [])
                if not items:
                    break
                for tag in items:
                    records.append(SkillRecord(
                        skill_name=tag["name"],
                        source=self.SOURCE_ID,
                        url=f"https://stackoverflow.com/questions/tagged/{tag['name']}",
                        tags=[tag["name"]],
                        popularity=tag.get("count", 0),
                    ))
                fetched += len(items)
                if not data.get("has_more", False):
                    break
                page += 1
            except Exception as exc:
                print(f"[stackoverflow_tags] page={page} failed: {exc}")
                break

        return records
