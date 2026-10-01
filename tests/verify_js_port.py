"""Verify the JavaScript port matches the Python metrics exactly.

The single-page HTML reimplements tech_spec.md §5–§8 in JavaScript, because a
server-less page has to compute in the browser. That creates a second copy of logic
the 39 checkpoints cannot protect — so this harness feeds the same inputs to both
implementations and compares the outputs.

If this ever fails, the HTML page is wrong, not the spec.

Usage
-----
    python tests/verify_js_port.py
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import metrics as M  # noqa: E402

SHOPEE = dict(commission=0.080, admin_fee=1_250, payment=0.020, affiliate=0.00)
TIKTOK = dict(commission=0.065, admin_fee=1_000, payment=0.020, affiliate=0.05)

# Fixtures chosen to exercise boundaries, not just the happy path:
# zero quantities, a SKU at exactly the critical threshold, and both channels.
CASES = [
    # (label, harga_per_unit, unit, hpp, fee_dict)
    ("shopee-typical",           12_240.0, 34, 12_050.0, SHOPEE),
    ("shopee-cheap-order",        2_000.0,  1,  2_100.0, SHOPEE),
    ("shopee-expensive",        200_000.0,  1, 150_000.0, SHOPEE),
    ("shopee-single-unit",        9_900.0,  1, 10_000.0, SHOPEE),
    ("tiktok-with-affiliate",    12_240.0, 34, 12_050.0, TIKTOK),
    ("tiktok-no-affiliate",      12_240.0, 34, 12_050.0, {**TIKTOK, "affiliate": 0.0}),
    ("healthy-margin",           20_000.0, 10, 10_000.0, SHOPEE),
    ("break-even",               11_000.0,  5, 10_000.0, SHOPEE),
    ("deep-loss",                 4_000.0,  7, 10_000.0, SHOPEE),
]


def build_js_cases() -> str:
    """Emit a small node script that runs the same cases through the port."""
    payload = []
    for label, harga, unit, hpp, fees in CASES:
        payload.append({
            "label": label,
            "harga": harga,
            "unit": unit,
            "hpp": hpp,
            "f": {
                "komisi": fees["commission"],
                "admin": fees["admin_fee"],
                "pembayaran": fees["payment"],
                "afiliasi": fees["affiliate"],
            },
        })

    return f"""
const fs = require("fs");
const kasus = {json.dumps(payload)};

// Pull the functions straight out of the shipped page so we test the real artifact.
const html = fs.readFileSync({json.dumps(str(ROOT / "simple" / "index.html"))}, "utf8");
const skrip = html.split("<script>")[1].split("</script>")[0];

// The page reads its embedded JSON via getElementById, so the stub must serve it
// back or the module-initialisation lines throw.
function blokJSON(id) {{
  const cocok = html.match(new RegExp('<script id="' + id + '"[^>]*>([\\\\s\\\\S]*?)</script>'));
  return cocok ? cocok[1] : "null";
}}

const kotak = {{}};
const elemen = {{
  "data-contoh": {{ textContent: blokJSON("data-contoh"), innerHTML: "", style: {{}} }},
  "tabel-hpp":   {{ textContent: blokJSON("tabel-hpp"),   innerHTML: "", style: {{}} }},
}};
const elemenUmum = () => ({{
  textContent: "", innerHTML: "", style: {{}},
  addEventListener() {{}}, classList: {{ add() {{}}, remove() {{}}, contains: () => false }},
  click() {{}}, focus() {{}}, value: "",
}});

new Function("window", "document", skrip + `
  // Function bodies get their own scope, so hand the functions out via a global.
  globalThis.__port = {{
    tarifVariabel, diterimaPerUnit, selisihPerUnit, klasifikasiTingkat, hargaSaran,
    runRatePerJam, jamSampaiHabis, klasifikasiStok,
    eksposurKotor, anggaranAman, statusAnggaran,
  }};
`)(
  {{}},
  {{
    getElementById: (id) => elemen[id] || elemenUmum(),
    addEventListener() {{}},
    querySelector: () => null,
    querySelectorAll: () => [],
  }}
);
const k = globalThis.__port;

const keluaran = kasus.map(c => ({{
  label: c.label,
  tarif: k.tarifVariabel(c.f),
  diterima: k.diterimaPerUnit(c.harga, c.unit, c.f),
  selisihUnit: k.selisihPerUnit(c.hpp, c.harga, c.unit, c.f),
  tingkat: k.klasifikasiTingkat(k.selisihPerUnit(c.hpp, c.harga, c.unit, c.f), c.hpp),
  hargaSaran: k.hargaSaran(c.hpp, 0.15, c.unit, c.f),
}}));

keluaran.push({{ label: "run-rate-9of168", laju: k.runRatePerJam(9, 168) }});
keluaran.push({{ label: "jam-habis-12at0.05357", jam: k.jamSampaiHabis(12, 9 / 168) }});
keluaran.push({{ label: "stok-dorman", status: k.klasifikasiStok(500, 0, 168) }});
keluaran.push({{ label: "stok-habis", status: k.klasifikasiStok(0, 0.05, 1) }});
keluaran.push({{ label: "stok-hampir", status: k.klasifikasiStok(3, 1.0, 24) }});
keluaran.push({{ label: "stok-aman", status: k.klasifikasiStok(100, 1.0, 24) }});
keluaran.push({{ label: "eksposur", nilai: k.eksposurKotor([36406, -50000, 1000]) }});
keluaran.push({{ label: "anggaran", nilai: k.anggaranAman(50000000, 18400000) }});
keluaran.push({{ label: "anggaran-status", nilai: k.statusAnggaran(50000000, 18400000) }});
keluaran.push({{ label: "anggaran-batas", nilai: k.statusAnggaran(50000000, 25000000) }});

console.log(JSON.stringify(keluaran));
"""


def main() -> int:
    node = shutil.which("node")
    if not node:
        print("node not found on PATH — cannot verify the JS port")
        return 2

    page = ROOT / "simple" / "index.html"
    if not page.exists():
        print("simple/index.html not found — run python src/build_simple.py first")
        return 1

    print(f"Verifying {len(CASES) + 10} cases: Python metrics.py vs the shipped HTML\n")

    with tempfile.TemporaryDirectory() as tmp:
        harness = Path(tmp) / "cek.js"
        harness.write_text(build_js_cases(), encoding="utf-8")
        proc = subprocess.run([node, str(harness)], capture_output=True, text=True)

    if proc.returncode != 0:
        print("node harness failed:")
        print(proc.stderr[:2000])
        return 1

    js = {row["label"]: row for row in json.loads(proc.stdout)}
    failures = []
    checked = 0

    for label, harga, unit, hpp, fees in CASES:
        got = js[label]
        expected = {
            "tarif": M.variable_rate(**fees),
            "diterima": M.seller_received_per_unit(harga, unit, **fees),
            "selisihUnit": M.under_cogs_per_unit(hpp, harga, unit, **fees),
            "tingkat": M.classify_severity(
                M.under_cogs_per_unit(hpp, harga, unit, **fees), hpp
            ).value,
            "hargaSaran": M.target_price(hpp, 0.15, unit, **fees),
        }
        if expected["tingkat"] == "OK":
            expected["tingkat"] = "PROFIT"
        elif expected["tingkat"] == "WATCH":
            expected["tingkat"] = "PANTAU"
        elif expected["tingkat"] == "AT_RISK":
            expected["tingkat"] = "BERISIKO"
        elif expected["tingkat"] == "CRITICAL":
            expected["tingkat"] = "KRITIS"

        for field, want in expected.items():
            checked += 1
            have = got[field]
            if isinstance(want, float):
                if abs(have - want) > 1e-6:
                    failures.append(f"{label}.{field}: js={have!r} py={want!r}")
            elif have != want:
                failures.append(f"{label}.{field}: js={have!r} py={want!r}")

    # Scalar cases where the two implementations must agree exactly.
    scalar = [
        ("run-rate-9of168", "laju", M.run_rate_per_hour(9, 168)),
        ("jam-habis-12at0.05357", "jam", M.hours_to_stockout(12, 9 / 168)),
        ("eksposur", "nilai", M.gross_exposure([36406, -50000, 1000])),
        ("anggaran", "nilai", M.budget_safe(50_000_000, 18_400_000)),
    ]
    translations = {
        "DORMANT": "TIDAK_TERJUAL", "OUT_OF_STOCK": "HABIS",
        "AT_RISK": "HAMPIR_HABIS", "HEALTHY": "AMAN",
    }
    status_cases = [
        ("stok-dorman", "status", M.classify_stockout(500, 0.0, 168)),
        ("stok-habis", "status", M.classify_stockout(0, 0.05, 1)),
        ("stok-hampir", "status", M.classify_stockout(3, 1.0, 24)),
        ("stok-aman", "status", M.classify_stockout(100, 1.0, 24)),
        ("anggaran-status", "nilai", M.budget_status(50_000_000, 18_400_000)),
        ("anggaran-batas", "nilai", M.budget_status(50_000_000, 25_000_000)),
    ]
    budget_labels = {"HEALTHY": "AMAN", "CAUTION": "PERHATIAN", "BREACHED": "TERLAMPAUI"}

    for label, field, want in scalar:
        checked += 1
        if abs(js[label][field] - want) > 1e-6:
            failures.append(f"{label}.{field}: js={js[label][field]!r} py={want!r}")

    for label, field, want in status_cases:
        checked += 1
        expected = translations.get(want.value, budget_labels.get(want.value, want.value))
        if js[label][field] != expected:
            failures.append(f"{label}.{field}: js={js[label][field]!r} py={expected!r}")

    print(f"{checked} values compared")
    if failures:
        print(f"\n{len(failures)} MISMATCHES — the HTML port disagrees with src/metrics.py:\n")
        for line in failures:
            print(f"  {line}")
        return 1

    print("All values identical — the JS port matches src/metrics.py.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())