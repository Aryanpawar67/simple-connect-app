"""
One-time migration: load iMocha Gold Taxonomy xlsx → Neon taxonomy table.

Usage:
    cd backend && python migrate_taxonomy.py
"""
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
load_dotenv(Path(__file__).parent / ".env")

sys.path.insert(0, str(Path(__file__).parent))

import openpyxl
from db.taxonomy_db import create_table, bulk_insert

XLSX_PATH = Path(__file__).parent.parent / "iMocha Gold Taxonomy_v1.xlsx"
DSN = os.environ["DATABASE_URL"]


def read_sheet1(wb) -> list[dict]:
    ws = wb["Final 16 domains"]
    rows = list(ws.rows)
    result = []
    for row in rows[1:]:
        vals = [c.value for c in row]
        if not any(vals):
            continue
        result.append({
            "domain":         vals[0] or "",
            "subdomain":      vals[1] or "",
            "skill_cluster":  vals[2] or "",
            "skill_name":     vals[3] or "",
            "classification": vals[4] or "",
            "criticality":    vals[5] or "",
            "sheet":          "sheet1",
        })
    return result


def read_sheet2(wb) -> list[dict]:
    ws = wb["Domain Independent & Irrelevant"]
    rows = list(ws.rows)
    result = []
    for row in rows[1:]:
        vals = [c.value for c in row]
        if not any(vals):
            continue
        result.append({
            "domain":         vals[0] or "",
            "subdomain":      vals[1] or "",
            "skill_cluster":  vals[2] or "",
            "skill_name":     vals[3] or "",
            "classification": vals[5] or "",
            "criticality":    vals[6] or "",
            "sheet":          "sheet2",
        })
    return result


if __name__ == "__main__":
    print(f"Loading {XLSX_PATH}...")
    wb = openpyxl.load_workbook(XLSX_PATH, read_only=True, data_only=True)
    sheet1 = read_sheet1(wb)
    sheet2 = read_sheet2(wb)
    wb.close()
    print(f"  Sheet1 rows: {len(sheet1)}")
    print(f"  Sheet2 rows: {len(sheet2)}")

    print("Ensuring taxonomy table exists...")
    create_table(DSN)

    print("Inserting sheet1...")
    n1 = bulk_insert(DSN, sheet1, batch="initial")
    print(f"  Inserted: {n1}")

    print("Inserting sheet2...")
    n2 = bulk_insert(DSN, sheet2, batch="initial")
    print(f"  Inserted: {n2}")

    print(f"\nDone. Total inserted: {n1 + n2}")
