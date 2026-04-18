from pathlib import Path
from datetime import date
import pandas as pd
from scraper.base import SkillRecord

COLUMNS = [
    "skill_name", "category", "subcategory", "skill_type",
    "description", "source", "url", "confidence_score",
    "language", "tags", "date_found", "first_seen", "is_new", "popularity",
]


# ---------------------------------------------------------------------------
# CSV-based fallback (used when DB is unavailable)
# ---------------------------------------------------------------------------

def load_existing_skills(sheets_dir: Path, exclude_date: date = None) -> set:
    """
    Return lowercased normalized skill_names from all previous CSV runs.
    Excludes the current run's date so re-running on the same day doesn't
    mark everything as old.
    """
    from processor.deduplicator import normalize_name
    exclude_stem = str(exclude_date) if exclude_date else None
    seen = set()
    for csv_file in sorted(sheets_dir.glob("*.csv")):
        if exclude_stem and csv_file.stem == exclude_stem:
            continue
        try:
            df = pd.read_csv(csv_file, usecols=["skill_name"], dtype=str)
            for name in df["skill_name"].dropna():
                seen.add(normalize_name(str(name)).lower())
        except Exception:
            pass
    return seen


# ---------------------------------------------------------------------------
# DataFrame builder
# ---------------------------------------------------------------------------

def records_to_dataframe(records: list) -> pd.DataFrame:
    rows = []
    for r in records:
        rows.append({
            "skill_name": r.skill_name,
            "category": r.category,
            "subcategory": r.subcategory,
            "skill_type": r.skill_type,
            "description": r.description,
            "source": r.source,
            "url": r.url,
            "confidence_score": r.confidence_score,
            "language": r.language,
            "tags": ", ".join(r.tags),
            "date_found": str(r.date_found),
            "first_seen": str(r.first_seen or r.date_found),
            "is_new": r.is_new,
            "popularity": r.popularity,
        })
    df = pd.DataFrame(rows, columns=COLUMNS)
    df = df.sort_values(
        ["is_new", "confidence_score", "popularity"],
        ascending=[False, False, False],
    ).reset_index(drop=True)
    return df


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def write_output(records: list, config: dict, run_date: date = None, db=None) -> dict:
    """
    Write to CSV and/or Excel.  Returns {format: Path}.

    is_new detection priority:
      1. DB (PostgreSQL) — accurate cross-run tracking with first_seen preserved
      2. CSV fallback    — if DB is None/unavailable, compare against prior sheets
    """
    if run_date is None:
        run_date = date.today()

    sheets_dir = Path(config["output"]["sheets_dir"])
    sheets_dir.mkdir(parents=True, exist_ok=True)
    formats = config["output"].get("formats", ["csv"])

    if db is not None:
        # --- DB path ---
        # mark_is_new sets is_new + restores first_seen for returning skills
        db.mark_is_new(records)
        for r in records:
            if r.first_seen is None:
                r.first_seen = run_date
        # Persist after marking so upsert sees the correct is_new state
        db.upsert_skills(records, run_date)
    else:
        # --- CSV fallback path ---
        existing = load_existing_skills(sheets_dir, exclude_date=run_date)
        for r in records:
            from processor.deduplicator import normalize_name
            r.is_new = normalize_name(r.skill_name).lower() not in existing
            if r.first_seen is None:
                r.first_seen = r.date_found

    df = records_to_dataframe(records)
    output_paths = {}
    stem = str(run_date)

    if "csv" in formats:
        path = sheets_dir / f"{stem}.csv"
        df.to_csv(path, index=False)
        output_paths["csv"] = path

    if "xlsx" in formats:
        path = sheets_dir / f"{stem}.xlsx"
        with pd.ExcelWriter(path, engine="openpyxl") as writer:
            df.to_excel(writer, sheet_name="Skills", index=False)
            ws = writer.sheets["Skills"]
            for col in ws.columns:
                max_len = max(len(str(cell.value or "")) for cell in col)
                ws.column_dimensions[col[0].column_letter].width = min(max_len + 2, 60)
        output_paths["xlsx"] = path

    return output_paths
