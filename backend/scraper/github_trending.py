import re
from scraper.base import BaseScraper, SkillRecord

# Prefixes that indicate meta-repos, not actual skills
_SKIP_PREFIXES = ("awesome-", "learn-", "tutorial-", "how-to-", "getting-started-", "intro-to-")

def _is_meta(name: str) -> bool:
    lower = name.lower()
    return any(lower.startswith(p) for p in _SKIP_PREFIXES)


class GitHubTrendingScraper(BaseScraper):
    SOURCE_ID = "github_trending"

    _GH_HEADERS = {
        "Accept": "application/vnd.github.v3+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }

    async def scrape(self) -> list:
        records = []
        topics = self._source_cfg.get("topics", [])
        max_results = self._source_cfg.get("max_results_per_topic", 30)

        for topic in topics:
            try:
                resp = await self.get(
                    "https://api.github.com/search/repositories",
                    params={
                        "q": f"topic:{topic}",
                        "sort": "stars",
                        "order": "desc",
                        "per_page": min(max_results, 100),
                    },
                    extra_headers=self._GH_HEADERS,
                )
                data = resp.json()
                for repo in data.get("items", []):
                    repo_name = repo["name"]
                    if not _is_meta(repo_name):
                        records.append(SkillRecord(
                            skill_name=repo_name,
                            source=self.SOURCE_ID,
                            url=repo["html_url"],
                            description=repo.get("description") or "",
                            language=repo.get("language") or "",
                            tags=repo.get("topics", []),
                            popularity=repo.get("stargazers_count", 0),
                        ))
                    # Emit each topic tag as its own skill signal (filter meta names)
                    for tag in repo.get("topics", []):
                        if not _is_meta(tag):
                            records.append(SkillRecord(
                                skill_name=tag,
                                source=self.SOURCE_ID,
                                url=f"https://github.com/topics/{tag}",
                                tags=[tag],
                                popularity=repo.get("stargazers_count", 0),
                            ))
            except Exception as exc:
                print(f"[github_trending] topic={topic} failed: {exc}")

        return records
