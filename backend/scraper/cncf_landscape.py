import yaml
from scraper.base import BaseScraper, SkillRecord

# The landscape.cncf.io SPA no longer serves items.json directly.
# Use the authoritative source: the raw YAML from the CNCF GitHub repo.
_YAML_URL = "https://raw.githubusercontent.com/cncf/landscape/master/landscape.yml"


class CncfLandscapeScraper(BaseScraper):
    SOURCE_ID = "cncf_landscape"

    async def scrape(self) -> list:
        records = []
        url = self._source_cfg.get("url", _YAML_URL)

        try:
            resp = await self.get(url)
            # BaseLoader treats all scalars as strings — tolerates embedded JSON in descriptions
            data = yaml.load(resp.text, Loader=yaml.BaseLoader)
            # Structure: {landscape: [{name: category, subcategories: [{name: sub, items: [...]}]}]}
            for category in data.get("landscape", []):
                cat_name = category.get("name", "")
                for subcategory in category.get("subcategories", []):
                    sub_name = subcategory.get("name", "")
                    for item in subcategory.get("items", []):
                        name = item.get("name", "")
                        if not name:
                            continue
                        homepage = item.get("homepage_url", "") or item.get("repo_url", "") or ""
                        description = item.get("description", "") or ""
                        stars = item.get("stars") or 0

                        records.append(SkillRecord(
                            skill_name=name,
                            source=self.SOURCE_ID,
                            url=homepage,
                            description=description[:300],
                            tags=[t.lower() for t in [cat_name, sub_name] if t],
                            popularity=int(stars) if str(stars).isdigit() else 0,
                        ))
        except Exception as exc:
            print(f"[cncf_landscape] failed: {exc}")

        return records
