# NYC Heatmap Grid Aggregation Design

**Date:** 2026-02-24
**Status:** Approved

## Problem

At city scale (zoom 11–12), all 28,664 blocks render as individual circles,
which is visually overwhelming. The map needs coarser aggregation at low zoom
that "explodes" into individual blocks as the user zooms in.

## Solution

A third zoom tier: below a threshold zoom level, bucket the in-memory blocks
into a regular lat/lng grid and render one circle per cell. The snap from grid
to blocks happens automatically on `zoomend`.

## Zoom Tiers

| Zoom | Renders | Source |
|------|---------|--------|
| < 11 | "Zoom in" message | — |
| 11–12 | Coarse grid cells (~150–200 citywide) | `aggregateToGrid(allBlocks, 0.05)` |
| 13–14 | Individual blocks (~28k) | `allBlocks` filtered by bounds |
| ≥ 15 | Individual lots | Live Socrata API |

## New Function: `aggregateToGrid(blocks, cellSize)`

Buckets each block by snapping its lat/lng to the nearest grid cell:

```
cellKey = floor(lat / cellSize) * cellSize + "," + floor(lng / cellSize) * cellSize
```

Per cell, accumulates:
- `total_assessed` — sum of all block totals
- `lot_count` — sum of all lot counts
- `lat` / `lng` — mean of block centroids

Returns an array in the same shape as `renderData` already expects
(`lat`, `lng`, `total_assessed`, `lot_count`, `sample_address`, `borocode`).
No changes needed to `renderData`.

The "Color by" toggle (total vs avg per lot) works automatically — `renderData`
already derives avg from `total_assessed / lot_count`.

## Config Changes

Two new constants in the Config section of `index.html`:

```js
const GRID_ZOOM = 13;   // below this zoom: show grid cells instead of blocks
const GRID_SIZE = 0.05; // cell side length in degrees (~3.5 miles)
```

## `doFetch` Change

In the block-zoom else-branch, replace the direct `allBlocks.filter()` call with:

```js
const visible = allBlocks.filter(b =>
  b.lat >= sw.lat && b.lat <= ne.lat &&
  b.lng >= sw.lng && b.lng <= ne.lng
);
const rows = zoom < GRID_ZOOM
  ? aggregateToGrid(visible, GRID_SIZE)
  : visible;
renderData(rows, zoom, valueType);
```

## Trade-offs

- Grid cells are geographic squares, not natural boundaries (neighborhoods, zip codes) — acceptable given simplicity
- Cell size 0.05° is a starting point; easy to tune via `GRID_SIZE` constant
- No new data files, no dependencies
