import asyncio
from scraper.base import BaseScraper, SkillRecord
from scraper.hackernews import TOOL_PATTERN, STOPWORDS


class RedditScraper(BaseScraper):
    SOURCE_ID = "reddit"
    # old.reddit.com returns JSON without requiring OAuth (www.reddit.com 403s)
    BASE_URL = "https://old.reddit.com"

    async def scrape(self) -> list:
        records = []
        subreddits = self._source_cfg.get("subreddits", [])
        max_posts = self._source_cfg.get("max_posts_per_sub", 25)
        sort = self._source_cfg.get("sort", "hot")

        for sub in subreddits:
            try:
                resp = await self.get(
                    f"{self.BASE_URL}/r/{sub}/{sort}.json",
                    params={"limit": max_posts},
                    extra_headers={
                        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
                        "Accept": "application/json, text/javascript, */*; q=0.01",
                        "Accept-Language": "en-US,en;q=0.9",
                        "Referer": "https://old.reddit.com/",
                    },
                )
                data = resp.json()
                posts = data.get("data", {}).get("children", [])
                for post in posts:
                    pd = post.get("data", {})
                    title = pd.get("title", "")
                    url = pd.get("url", "")
                    score = pd.get("score", 0)
                    for match in TOOL_PATTERN.finditer(title):
                        name = match.group(1)
                        if len(name) < 2 or name.lower() in STOPWORDS:
                            continue
                        records.append(SkillRecord(
                            skill_name=name,
                            source=self.SOURCE_ID,
                            url=url,
                            description=title,
                            tags=[sub],
                            popularity=score,
                        ))
                await asyncio.sleep(1)
            except Exception as exc:
                print(f"[reddit] sub={sub} failed: {exc}")

        return records
