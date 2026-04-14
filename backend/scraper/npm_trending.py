from scraper.base import BaseScraper, SkillRecord

# Scoped package namespaces that are clearly internal tooling, not skills
_INTERNAL_SCOPES = {"boost", "types", "babel", "jest", "internal", "private"}


class NpmTrendingScraper(BaseScraper):
    SOURCE_ID = "npm_trending"

    async def scrape(self) -> list:
        records = []
        keywords = self._source_cfg.get("keywords", [])
        max_results = self._source_cfg.get("max_results_per_keyword", 20)

        for keyword in keywords:
            try:
                resp = await self.get(
                    "https://registry.npmjs.org/-/v1/search",
                    params={
                        "text": keyword,
                        "size": max_results,
                        "quality": 0.5,
                        "popularity": 0.8,
                        "maintenance": 0.5,
                    }
                )
                data = resp.json()
                for obj in data.get("objects", []):
                    pkg = obj.get("package", {})
                    name = pkg.get("name", "")
                    if not name:
                        continue
                    # Skip clearly internal scoped packages
                    if name.startswith("@") and "/" in name:
                        scope = name.split("/")[0].lstrip("@")
                        if scope in _INTERNAL_SCOPES:
                            continue
                    records.append(SkillRecord(
                        skill_name=name,
                        source=self.SOURCE_ID,
                        url=f"https://www.npmjs.com/package/{name}",
                        description=pkg.get("description", ""),
                        language="JavaScript",
                        tags=pkg.get("keywords", []) or [],
                        popularity=int(
                            obj.get("score", {}).get("detail", {}).get("popularity", 0) * 10000
                        ),
                    ))
            except Exception as exc:
                print(f"[npm_trending] keyword={keyword} failed: {exc}")

        return records
