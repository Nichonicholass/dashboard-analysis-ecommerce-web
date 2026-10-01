"""Build `simple/_demo.json` — the embedded demo data for the single-page HTML.

Reads `web/public/analysis.json` (produced by `src/build_analysis.py`) and emits a
compact payload for `src/build_simple.py` to inline.

Two grain decisions matter here, both learned from testing the upload path:

1. **Everything is keyed by seller SKU** (`SS-SRC-0001`), not the internal SKU
   (`SRC-0001`). Marketplace exports only ever contain the seller SKU, so keying the
   cost table by internal SKU silently broke every uploaded file.

2. **The name map covers the whole catalogue**, not just the rows on screen, so a
   freshly uploaded SKU still gets a readable product name.

Usage
-----
    python src/generate.py           # fixture
    python src/build_analysis.py     # analysis
    python src/build_simple_data.py  # this file
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SIMPLE = ROOT / "simple"
ANALYSIS = ROOT / "web" / "public" / "analysis.json"
OUTPUT = SIMPLE / "_demo.json"

# How many of each kind to showcase as demo rows.
WORST_LOSSES = 8
HEALTHY_SAMPLE = 3


def ringkas(row: dict) -> dict:
    """Compact field names — the payload is inlined into the HTML."""
    return {
        "s": row["seller_sku"],          # seller SKU is the upload join key
        "n": row["name"],
        "c": row["channel"],
        "a": row["allocated"],
        "k": row["unit_cost"],
        "u7": row["sold_units_window"],
        "t7": row["sold_units_period"],
        "p": row["net_item_value_per_unit"],
        "r": row["seller_received_per_unit"],
        "lu": row["under_cogs_per_unit"],
        "lt": row["under_cogs_total"],
        "sev": row["severity"],
        "st": row["stockout_status"],
        "cd": row["cover_days"],
        "tp": row["recommended_price"],
    }


def main() -> int:
    if not ANALYSIS.exists():
        print(f"missing {ANALYSIS.relative_to(ROOT)} — run python src/build_analysis.py")
        return 1

    analysis = json.loads(ANALYSIS.read_text(encoding="utf-8"))
    rows = analysis["all_rows"]
    if not rows:
        print("analysis.json has no rows")
        return 1

    # Demo selection: every stock-out (so the alert path is visible), the worst
    # losses, and a few healthy rows for contrast.
    out_of_stock = [r for r in rows if r["stockout_status"] == "OUT_OF_STOCK"]
    worst = sorted(rows, key=lambda r: -r["under_cogs_total"])[:WORST_LOSSES]
    healthy = [
        r for r in rows
        if r["severity"] == "OK" and r["sold_units_period"] > 0
    ][:HEALTHY_SAMPLE]

    picked, seen = [], set()
    for row in out_of_stock + worst + healthy:
        key = (row["seller_sku"], row["channel"])
        if key not in seen:
            seen.add(key)
            picked.append(row)

    # Cost + name tables cover the full catalogue so any upload can be priced.
    hpp = {r["seller_sku"]: r["unit_cost"] for r in rows}
    nama = {r["seller_sku"]: r["name"] for r in rows}

    payload = {
        "perTanggal": analysis["data_as_of"][:10],
        "anggaran": analysis["summary"]["campaign_budget"],
        "hpp": hpp,
        "nama": nama,
        "baris": [ringkas(r) for r in picked],
    }

    OUTPUT.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    size = OUTPUT.stat().st_size

    print(f"demo data -> {OUTPUT.relative_to(ROOT)}  ({size:,} bytes)")
    print(f"  demo rows    : {len(picked)}"
          f"  (out-of-stock {len(out_of_stock)}, worst-loss {len(worst)}, healthy {len(healthy)})")
    print(f"  cost table   : {len(hpp)} seller SKUs")
    print(f"  name table   : {len(nama)} seller SKUs")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())