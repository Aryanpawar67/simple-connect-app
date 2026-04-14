from bs4 import BeautifulSoup
from scraper.base import BaseScraper, SkillRecord

# Browser-like UA increases chance of getting through LinkedIn's bot filter
_LI_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Referer": "https://www.linkedin.com/",
    "Accept-Language": "en-US,en;q=0.9",
}


class LinkedInJobsScraper(BaseScraper):
    SOURCE_ID = "linkedin_jobs"

    async def scrape(self) -> list:
        records = []
        search_terms = self._source_cfg.get("search_terms", [])
        max_results = self._source_cfg.get("max_results_per_term", 20)

        for term in search_terms:
            try:
                resp = await self.get(
                    "https://www.linkedin.com/jobs/search/",
                    params={
                        "keywords": term,
                        "location": "",
                        "f_TPR": "r604800",  # past week
                        "count": max_results,
                    },
                    extra_headers=_LI_HEADERS,
                )
                soup = BeautifulSoup(resp.text, "lxml")
                for title_el in soup.select("h3.base-search-card__title"):
                    title = title_el.get_text(strip=True)
                    if title:
                        records.append(SkillRecord(
                            skill_name=title,
                            source=self.SOURCE_ID,
                            url="https://www.linkedin.com/jobs/search/",
                            description=f"Job title from LinkedIn search: {term}",
                            tags=["job-market", "linkedin"],
                            popularity=0,
                        ))
            except Exception as exc:
                # LinkedIn blocks aggressively — log and continue, 0 records is acceptable
                print(f"[linkedin_jobs] term={term} failed (blocked?): {exc}")

        return records
