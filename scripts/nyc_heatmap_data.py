#!/usr/bin/env python3
"""
NYC Property Heatmap — Data Fetcher
====================================
Downloads NYC MapPLUTO data from NYC Open Data and aggregates by block.
Outputs static/nyc-heatmap/data/blocks.json, which is loaded once by the
interactive map for block-level rendering. Re-run annually when PLUTO data
is refreshed (the dataset updates roughly once a year).

Data source:
  NYC MapPLUTO (Primary Land Use Tax Lot Output)
  https://data.cityofnewyork.us/City-Government/Primary-Land-Use-Tax-Lot-Output-PLUTO-/64uk-42ks
  ~850 000 tax lots, updated annually.

Usage:
  python scripts/nyc_heatmap_data.py [options]

Options:
  --boro {1,2,3,4,5}  Filter to one borough
                        1=Manhattan 2=Bronx 3=Brooklyn 4=Queens 5=Staten Island
  --output PATH        Destination JSON file
                        (default: static/nyc-heatmap/data/blocks.json)
  --no-aggregate       Save lot-level records instead of block aggregates

Requirements: Python 3.8+, no third-party packages needed.
"""

import argparse
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import defaultdict
from pathlib import Path

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

PLUTO_API = "https://data.cityofnewyork.us/resource/64uk-42ks.json"
BATCH_SIZE = 50_000

BOROUGH_NAMES = {
    "1": "Manhattan",
    "2": "Bronx",
    "3": "Brooklyn",
    "4": "Queens",
    "5": "Staten Island",
}


# ---------------------------------------------------------------------------
# Fetching
# ---------------------------------------------------------------------------

def fetch_batch(offset: int, boro: str | None, retries: int = 4) -> list[dict]:
    """Fetch up to BATCH_SIZE PLUTO records starting at *offset*."""
    conditions = [
        "assesstot > 0",
        "latitude  IS NOT NULL",
        "longitude IS NOT NULL",
    ]
    if boro:
        conditions.append(f"borocode = '{boro}'")

    params = {
        "$limit":  BATCH_SIZE,
        "$offset": offset,
        "$select": (
            "latitude,longitude,assesstot,assessland,"
            "block,lot,borocode,zipcode,address,landuse,unitstotal"
        ),
        "$where": " AND ".join(conditions),
        "$order": "bbl ASC",
    }

    url = f"{PLUTO_API}?{urllib.parse.urlencode(params)}"

    for attempt in range(retries):
        try:
            with urllib.request.urlopen(url, timeout=90) as resp:
                return json.loads(resp.read().decode())
        except (urllib.error.URLError, OSError) as exc:
            if attempt == retries - 1:
                raise
            wait = 2 ** (attempt + 1)
            print(f"  Retry {attempt + 1}/{retries} in {wait}s — {exc}", file=sys.stderr)
            time.sleep(wait)
    return []  # unreachable, satisfies type checker


def fetch_all(boro: str | None) -> list[dict]:
    """Page through the API until all records are retrieved."""
    all_records: list[dict] = []
    offset = 0

    while True:
        batch = fetch_batch(offset=offset, boro=boro)
        if not batch:
            break
        all_records.extend(batch)
        print(f"  Fetched {len(batch):>6,} records  (running total: {len(all_records):,})")
        if len(batch) < BATCH_SIZE:
            break
        offset += BATCH_SIZE

    return all_records


# ---------------------------------------------------------------------------
# Aggregation
# ---------------------------------------------------------------------------

def aggregate_by_block(records: list[dict]) -> list[dict]:
    """Roll lot-level records up to block level."""
    blocks: dict[str, dict] = defaultdict(lambda: {
        "lats": [], "lngs": [], "assessed": [],
        "boro": None, "block": None, "addresses": [],
    })

    skipped = 0
    for r in records:
        try:
            lat = float(r["latitude"])
            lng = float(r["longitude"])
            val = float(r["assesstot"])
        except (KeyError, TypeError, ValueError):
            skipped += 1
            continue

        if val <= 0 or lat == 0.0 or lng == 0.0:
            skipped += 1
            continue

        boro  = r.get("borocode",  "0")
        block = r.get("block", "0")
        key   = f"{boro}-{block}"
        b     = blocks[key]

        b["lats"].append(lat)
        b["lngs"].append(lng)
        b["assessed"].append(val)
        b["boro"]  = boro
        b["block"] = block
        if r.get("address") and len(b["addresses"]) < 3:
            b["addresses"].append(r["address"])

    if skipped:
        print(f"  Skipped {skipped:,} records with missing/invalid data", file=sys.stderr)

    result = []
    for b in blocks.values():
        n = len(b["lats"])
        if n == 0:
            continue
        total = sum(b["assessed"])
        result.append({
            "lat":            round(sum(b["lats"]) / n, 6),
            "lng":            round(sum(b["lngs"]) / n, 6),
            "total_assessed": round(total),
            "avg_assessed":   round(total / n),
            "lot_count":      n,
            "borocode":       b["boro"],
            "boro_name":      BOROUGH_NAMES.get(b["boro"], "Unknown"),
            "block":          b["block"],
            "sample_address": b["addresses"][0] if b["addresses"] else None,
        })

    result.sort(key=lambda x: x["total_assessed"], reverse=True)
    return result


# ---------------------------------------------------------------------------
# Stats
# ---------------------------------------------------------------------------

def compute_stats(blocks: list[dict]) -> dict:
    if not blocks:
        return {}

    totals = sorted(b["total_assessed"] for b in blocks)

    by_boro: dict[str, dict] = {}
    for name in BOROUGH_NAMES.values():
        subset = [b for b in blocks if b.get("boro_name") == name]
        by_boro[name] = {
            "block_count":    len(subset),
            "total_assessed": sum(b["total_assessed"] for b in subset),
        }

    return {
        "block_count":             len(blocks),
        "total_assessed_citywide": sum(totals),
        "median_block_total":      totals[len(totals) // 2],
        "min_block_total":         totals[0],
        "max_block_total":         totals[-1],
        "by_borough":              by_boro,
    }


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Fetch and aggregate NYC MapPLUTO property data."
    )
    parser.add_argument(
        "--boro",
        choices=["1", "2", "3", "4", "5"],
        help="Filter to one borough (1=Manhattan … 5=Staten Island)",
    )
    parser.add_argument(
        "--output",
        default="static/nyc-heatmap/data/blocks.json",
        help="Output JSON file path",
    )
    parser.add_argument(
        "--no-aggregate",
        action="store_true",
        help="Save raw lot-level records (large!) instead of block aggregates",
    )
    args = parser.parse_args()

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    boro_label = BOROUGH_NAMES.get(args.boro, "all boroughs") if args.boro else "all boroughs"
    print(f"Fetching NYC MapPLUTO data — {boro_label}")
    print(f"API: {PLUTO_API}\n")

    records = fetch_all(boro=args.boro)
    print(f"\nTotal records: {len(records):,}")

    if args.no_aggregate:
        payload = {"generated_at": _now(), "records": records}
        _write_json(output_path, payload)
        return

    print("Aggregating by block…")
    blocks = aggregate_by_block(records)
    stats  = compute_stats(blocks)

    print(f"\nBlocks:             {stats.get('block_count', 0):,}")
    print(f"Total assessed:     ${stats.get('total_assessed_citywide', 0):>20,.0f}")
    print(f"Median block total: ${stats.get('median_block_total', 0):>20,.0f}")
    print(f"Max block total:    ${stats.get('max_block_total', 0):>20,.0f}")
    print()
    for name, bstats in stats.get("by_borough", {}).items():
        if bstats["block_count"]:
            print(f"  {name:<14} {bstats['block_count']:>6,} blocks   "
                  f"${bstats['total_assessed']:>18,.0f}")

    payload = {"generated_at": _now(), "stats": stats, "blocks": blocks}
    _write_json(output_path, payload)


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _write_json(path: Path, payload: dict) -> None:
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, separators=(",", ":"))
    size_mb = path.stat().st_size / 1_000_000
    print(f"\nSaved → {path}  ({size_mb:.1f} MB)")


if __name__ == "__main__":
    main()
