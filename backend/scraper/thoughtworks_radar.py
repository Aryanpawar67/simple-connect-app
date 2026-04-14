import re
from bs4 import BeautifulSoup
from scraper.base import BaseScraper, SkillRecord

RING_SCORE = {"Adopt": 90, "Trial": 70, "Assess": 50, "Hold": 20}

# Four quadrant category pages — all are server-rendered
_CATEGORY_PAGES = [
    ("tools", "https://www.thoughtworks.com/radar/tools"),
    ("techniques", "https://www.thoughtworks.com/radar/techniques"),
    ("platforms", "https://www.thoughtworks.com/radar/platforms"),
    ("languages-and-frameworks", "https://www.thoughtworks.com/radar/languages-and-frameworks"),
]

_SKIP_NAMES = {"view blip history", "view all", "subscribe", "download", "technology radar"}


class ThoughtworksRadarScraper(BaseScraper):
    SOURCE_ID = "thoughtworks_radar"

    async def scrape(self) -> list:
        records = []

        for quadrant_slug, url in _CATEGORY_PAGES:
            try:
                resp = await self.get(url, extra_headers={"User-Agent": "Mozilla/5.0 AppleWebKit/537.36"})
                soup = BeautifulSoup(resp.text, "lxml")
                seen = set()

                for a in soup.find_all("a", href=True):
                    href = a["href"]
                    name = a.get_text(strip=True)

                    if not name or name.lower() in _SKIP_NAMES or len(name) < 2:
                        continue
                    # Only follow absolute URLs for the current quadrant (avoids sidebar duplicates)
                    expected = f"https://www.thoughtworks.com/radar/{quadrant_slug}/"
                    if not href.startswith(expected):
                        continue
                    if href in seen:
                        continue
                    seen.add(href)

                    # Walk up the DOM to find Adopt/Trial/Assess/Hold context
                    el = a
                    ring = "Unknown"
                    for _ in range(8):
                        el = el.parent
                        if not el:
                            break
                        m = re.search(r"\b(Adopt|Trial|Assess|Hold)\b", el.get_text())
                        if m:
                            ring = m.group(1)
                            break

                    records.append(SkillRecord(
                        skill_name=name,
                        source=self.SOURCE_ID,
                        url=href,
                        description=f"{quadrant_slug} — {ring}",
                        tags=[quadrant_slug, ring.lower()],
                        popularity=RING_SCORE.get(ring, 30),
                    ))

            except Exception as exc:
                print(f"[thoughtworks_radar] quadrant={quadrant_slug} failed: {exc}")

        if len(records) < 10:
            print(f"[thoughtworks_radar] WARNING: only {len(records)} records scraped")

        return records
