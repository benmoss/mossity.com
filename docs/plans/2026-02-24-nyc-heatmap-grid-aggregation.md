# NYC Heatmap Grid Aggregation Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** At zoom 11–12 aggregate the 28k in-memory blocks into a coarse lat/lng grid (~150–200 cells) so the city-scale view is readable, snapping to individual blocks when the user zooms in past zoom 13.

**Architecture:** Add two constants (`GRID_ZOOM`, `GRID_SIZE`), one pure function (`aggregateToGrid`), and a two-line change to the `doFetch` else-branch. `renderData` is unchanged — the aggregated cells have the same shape as individual blocks.

**Tech Stack:** Vanilla JS in `static/nyc-heatmap/index.html`; no new dependencies.

---

### Task 1: Add constants and `aggregateToGrid` function

**Files:**
- Modify: `static/nyc-heatmap/index.html`

Two edits to this file.

**Edit 1 — Add constants to the Config section**

Find (line ~309):
```js
const LOT_ZOOM        = 15;   // above this: show individual lots instead of blocks
```

Add two lines immediately after it:
```js
const GRID_ZOOM       = 13;   // below this zoom: aggregate blocks into grid cells
const GRID_SIZE       = 0.05; // grid cell size in degrees (~3.5 miles per side)
```

**Edit 2 — Add `aggregateToGrid` function**

Find the `// Load orchestration` comment (line ~551). Insert the following block immediately before it (leave one blank line between the new function and the comment):

```js
// ============================================================
// Grid aggregation
// ============================================================
function aggregateToGrid(blocks, cellSize) {
  const cells = new Map();
  for (const b of blocks) {
    const cellLat = Math.floor(b.lat / cellSize) * cellSize;
    const cellLng = Math.floor(b.lng / cellSize) * cellSize;
    const key     = `${cellLat},${cellLng}`;
    if (!cells.has(key)) {
      cells.set(key, {
        lats: [], lngs: [],
        total_assessed: 0,
        lot_count:      0,
        sample_address: b.sample_address,
        borocode:       b.borocode,
      });
    }
    const c = cells.get(key);
    c.lats.push(b.lat);
    c.lngs.push(b.lng);
    c.total_assessed += b.total_assessed;
    c.lot_count      += b.lot_count;
  }
  return Array.from(cells.values()).map(c => ({
    lat:            c.lats.reduce((a, v) => a + v, 0) / c.lats.length,
    lng:            c.lngs.reduce((a, v) => a + v, 0) / c.lngs.length,
    total_assessed: c.total_assessed,
    lot_count:      c.lot_count,
    sample_address: c.sample_address,
    borocode:       c.borocode,
  }));
}

```

**Step 1: Verify the edits look correct**

Read the file around lines 308–315 and 551–600 to confirm:
- `GRID_ZOOM` and `GRID_SIZE` appear after `LOT_ZOOM`
- `aggregateToGrid` is defined before `// Load orchestration`
- No syntax errors (balanced braces, correct commas)

**Step 2: Commit**

```bash
git add static/nyc-heatmap/index.html
git commit -m "feat: add aggregateToGrid function and GRID_ZOOM/GRID_SIZE constants"
```

---

### Task 2: Wire `aggregateToGrid` into `doFetch`

**Files:**
- Modify: `static/nyc-heatmap/index.html`

**Edit — Replace the block-zoom else-branch in `doFetch`**

Find the current else-branch (lines ~591–600):

```js
  } else {
    if (!allBlocks) return;
    const sw   = bounds.getSouthWest();
    const ne   = bounds.getNorthEast();
    const rows = allBlocks.filter(b =>
      b.lat >= sw.lat && b.lat <= ne.lat &&
      b.lng >= sw.lng && b.lng <= ne.lng
    );
    renderData(rows, zoom, valueType);
  }
```

Replace with:

```js
  } else {
    if (!allBlocks) return;
    const sw      = bounds.getSouthWest();
    const ne      = bounds.getNorthEast();
    const visible = allBlocks.filter(b =>
      b.lat >= sw.lat && b.lat <= ne.lat &&
      b.lng >= sw.lng && b.lng <= ne.lng
    );
    const rows = zoom < GRID_ZOOM
      ? aggregateToGrid(visible, GRID_SIZE)
      : visible;
    renderData(rows, zoom, valueType);
  }
```

**Step 1: Verify manually**

Open `static/nyc-heatmap/index.html` directly in the browser (or via `hugo server`).

- At zoom 11–12 (city view): should see ~150–200 large circles spread across the five boroughs — not thousands of overlapping dots
- Zoom in to 13+: circles should snap to individual block-level dots
- Zoom in to 15+: individual lots via live API (unchanged)
- "Color by" toggle should work at all zoom levels

**Step 2: Commit**

```bash
git add static/nyc-heatmap/index.html
git commit -m "feat: show coarse grid cells at zoom < 13, snap to blocks at zoom 13+"
```
