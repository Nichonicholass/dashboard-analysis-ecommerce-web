"""Build the single-file HTML dashboard.

Inlines the JavaScript and the two JSON blobs into `simple/_template.html`, producing
`simple/index.html` — one file, no server, no build step, no dependencies.

Usage
-----
    python src/generate.py           # 1. fixture
    python src/build_analysis.py     # 2. analysis -> web/public/analysis.json
    python src/build_simple.py       # 3. this file -> simple/index.html
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SIMPLE = ROOT / "simple"
ANALYSIS = ROOT / "web" / "public" / "analysis.json"

TEMPLATE = SIMPLE / "_template.html"
SCRIPT = SIMPLE / "_skrip.js"
DEMO = SIMPLE / "_demo.json"
OUTPUT = SIMPLE / "index.html"


def main() -> int:
    for required in (TEMPLATE, SCRIPT, DEMO, ANALYSIS):
        if not required.exists():
            print(f"missing input: {required.relative_to(ROOT)}")
            print("run python src/generate.py and python src/build_analysis.py first")
            return 1

    template = TEMPLATE.read_text(encoding="utf-8")
    script = SCRIPT.read_text(encoding="utf-8")
    demo = json.loads(DEMO.read_text(encoding="utf-8"))

    # The cost and name tables cover the whole catalogue, not just the demo rows, so
    # an upload can price and label any SKU rather than only the ones on screen.
    cost_table = demo["hpp"]
    name_table = demo.get("nama", {})

    html = template
    html = html.replace(
        "__DATA_CONTOH__",
        json.dumps(
            {
                "perTanggal": demo["perTanggal"],
                "anggaran": demo["anggaran"],
                "nama": name_table,
                "baris": demo["baris"],
            },
            ensure_ascii=False,
            separators=(",", ":"),
        ),
    )
    html = html.replace(
        "__TABEL_HPP__",
        json.dumps(cost_table, ensure_ascii=False, separators=(",", ":")),
    )
    html = html.replace("__SKRIP__", script)

    # Guard against a silently unsubstituted placeholder.
    leftovers = re.findall(r"__[A-Z_]+__", html)
    if leftovers:
        print(f"unsubstituted placeholders remain: {sorted(set(leftovers))}")
        return 1

    OUTPUT.write_text(html, encoding="utf-8")
    size = OUTPUT.stat().st_size
    print(f"built -> {OUTPUT.relative_to(ROOT)}  ({size:,} bytes, single file)")
    print(f"  demo rows : {len(demo['baris'])}")
    print(f"  cost table: {len(cost_table)} seller SKUs")
    print(f"  name table: {len(name_table)} seller SKUs")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())