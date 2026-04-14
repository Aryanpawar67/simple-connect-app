from scraper.base import BaseScraper, SkillRecord

# Infrastructure/utility packages that are noise, not teachable skills
PYPI_SKIP_LIST = {
    "setuptools", "pip", "wheel", "six", "certifi", "charset-normalizer",
    "idna", "packaging", "typing-extensions", "urllib3", "botocore",
    "s3transfer", "jmespath", "python-dateutil", "pytz", "pyyaml",
    "cryptography", "cffi", "pycparser", "attrs", "zipp", "colorama",
    "requests", "click", "tqdm", "filelock", "platformdirs", "distlib",
    "virtualenv", "tomli", "exceptiongroup", "iniconfig", "pluggy",
    "py", "pytest", "coverage", "soupsieve", "pyparsing", "wcwidth",
}


class PypiTrendingScraper(BaseScraper):
    SOURCE_ID = "pypi_trending"

    async def scrape(self) -> list:
        records = []
        top_n = self._source_cfg.get("top_n", 500)

        try:
            resp = await self.get(
                "https://hugovk.github.io/top-pypi-packages/top-pypi-packages-30-days.min.json"
            )
            data = resp.json()
            rows = data.get("rows", [])[:top_n]

            for row in rows:
                name = row.get("project", "")
                downloads = row.get("download_count", 0)
                if not name or name.lower() in PYPI_SKIP_LIST:
                    continue
                records.append(SkillRecord(
                    skill_name=name,
                    source=self.SOURCE_ID,
                    url=f"https://pypi.org/project/{name}",
                    language="Python",
                    tags=["python", "package", "pypi"],
                    popularity=downloads,
                ))
        except Exception as exc:
            print(f"[pypi_trending] failed: {exc}")

        return records
