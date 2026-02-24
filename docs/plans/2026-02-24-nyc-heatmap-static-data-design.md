# NYC Heatmap — Static Data Performance Design

**Date:** 2026-02-24
**Status:** Approved

## Problem

The map currently hits the NYC Open Data Socrata API on every pan and zoom — a
server-side `GROUP BY` aggregation over 850k records. Both initial load and
navigation feel slow.

## Solution

Pre-generate a static block-aggregated JSON file using the existing Python
fetcher, commit it to the repo, and load it once on page load. All block-level
rendering becomes client-side filtering of an in-memory array.

## Architecture

### Block view (zoom < 15)

- On page load, fetch `/nyc-heatmap/data/blocks.json` once (~8 MB raw / ~2–3 MB
  gzip, served by Amplify as a static asset)
- Store all ~75k blocks in memory
- On `moveend`/`zoomend`: filter by current bounds (simple lat/lng range check),
  pass to existing `renderData` — no network calls

### Lot view (zoom ≥ 15)

- Keep the existing live Socrata API call unchanged
- At this zoom level the viewport covers only a few city blocks, so the
  bounded query returns quickly
- Pre-generating all 850k lots is not practical (~100+ MB)

## Changes Required

### `scripts/nyc_heatmap_data.py`

- Change output key `"boro"` → `"borocode"` to match what the Socrata API
  returns (and what the map already reads after the recent fix)

### `static/nyc-heatmap/data/blocks.json`

- Generate by running `python scripts/nyc_heatmap_data.py` once
- Commit to repo; refresh annually when PLUTO data updates

### `static/nyc-heatmap/index.html`

- Add `loadStaticBlocks()`: fetches the JSON once, stores blocks in a module-level
  variable, shows/hides the existing loading spinner
- Replace `fetchBlocks(bounds)` calls with a bounds-filter over the in-memory array
- Keep `fetchLots(bounds)` unchanged for lot-level zoom

## Trade-offs

| | Before | After |
|---|---|---|
| Initial load | Slow (Socrata GROUP BY) | ~1–2s JSON download (once) |
| Pan/zoom (block) | Slow (new API call each time) | Instant (in-memory filter) |
| Pan/zoom (lot) | Slow | Same (still live API, small viewport) |
| Data freshness | Live | ~Annual (matches PLUTO update cadence) |
| External dependency | Required for all views | Only required for lot-level zoom |
| Repo size | +0 | +~8 MB (committed JSON) |
