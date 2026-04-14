from bs4 import BeautifulSoup
from scraper.base import BaseScraper, SkillRecord


class GitHubTopicsScraper(BaseScraper):
    SOURCE_ID = "github_topics"

    async def scrape(self) -> list:
        records = []
        url = self._source_cfg.get("url", "https://github.com/topics")
        max_topics = self._source_cfg.get("max_topics", 60)

        try:
            resp = await self.get(url, extra_headers={"Accept": "text/html"})
            soup = BeautifulSoup(resp.text, "lxml")
            count = 0
            seen = set()
            # GitHub Topics page uses anchor links directly to /topics/{slug}
            for a in soup.find_all("a", href=lambda h: h and h.startswith("/topics/") and h.count("/") == 2):
                if count >= max_topics:
                    break
                href = a["href"]
                if href in seen:
                    continue
                seen.add(href)
                # Grab the visible text — may include description in child elements
                text_parts = [t.strip() for t in a.stripped_strings]
                name = text_parts[0] if text_parts else href.split("/")[-1]
                desc = " ".join(text_parts[1:])[:300] if len(text_parts) > 1 else ""
                link = f"https://github.com{href}"

                records.append(SkillRecord(
                    skill_name=name,
                    source=self.SOURCE_ID,
                    url=link,
                    description=desc[:300],
                    tags=["github-topic"],
                    popularity=0,
                ))
                count += 1
        except Exception as exc:
            print(f"[github_topics] failed: {exc}")

        return records
