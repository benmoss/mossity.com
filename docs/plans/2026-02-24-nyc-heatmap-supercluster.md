# NYC Heatmap Supercluster Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Replace the grid aggregation approach with supercluster.js so blocks merge into labeled cluster circles at low zoom and explode into individual blocks as the user zooms in.

**Architecture:** Load supercluster from CDN, build an index from `allBlocks` after the static JSON loads, query it by bounding box + zoom level in `doFetch`, and render cluster circles as `L.divIcon` with a block-count label (individual blocks stay as `L.circleMarker`).

**Tech Stack:** Vanilla JS, Leaflet.js, supercluster v8 (CDN)

---

### Task 1: Remove grid aggregation code and add supercluster CDN script

**Files:**
- Modify: `static/nyc-heatmap/index.html`

Three edits.

**Edit 1 — Remove `GRID_ZOOM` and `GRID_SIZE` constants**

Find and delete these two lines (currently ~310–311):
```js
const GRID_ZOOM       = 13;   // below this zoom: aggregate blocks into grid cells
const GRID_SIZE       = 0.05; // grid cell size in degrees (~3.5 miles per side)
```

**Edit 2 — Remove the `aggregateToGrid` function and its comment block**

Find and delete the entire section from `// Grid aggregation` through the closing `}` of `aggregateToGrid` (currently ~lines 551–586, including the blank line before `// Load orchestration`):

```js
// ============================================================
// Grid aggregation
// ============================================================
function aggregateToGrid(blocks, cellSize) {
  ...
}

```

**Edit 3 — Restore `doFetch` else-branch to a direct filter (no aggregation)**

The current else-branch calls `aggregateToGrid`. Replace it with a simple filter:

Find (current ~lines 628–640):
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

Replace with:
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

**Edit 4 — Add supercluster script tag**

Find the Leaflet script tag (lines ~297–301):
```html
<script
  src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"
  integrity="sha256-20nQCchB9co0qIjJZRGuk2/Z9VM+kNiyxNV1lvTlZBo="
  crossorigin=""
></script>
```

Add the supercluster script tag immediately after it:
```html
<script src="https://unpkg.com/supercluster@8/dist/supercluster.min.js"></script>
```

**Verify** no references to `GRID_ZOOM`, `GRID_SIZE`, or `aggregateToGrid` remain in the file.

**Commit:**
```bash
git add static/nyc-heatmap/index.html
git commit -m "refactor: remove grid aggregation, add supercluster CDN"
```

---

### Task 2: Add `buildClusterIndex` and wire into `loadStaticBlocks` + `doFetch`

**Files:**
- Modify: `static/nyc-heatmap/index.html`

Three edits.

**Edit 1 — Add `clusterIndex` variable alongside `allBlocks`**

Find (in the `// Static block data` section):
```js
let allBlocks = null;
```

Change to:
```js
let allBlocks    = null;
let clusterIndex = null;
```

**Edit 2 — Add `buildClusterIndex` function after `loadStaticBlocks`**

Find the `// Load orchestration` comment. Insert this entire block immediately before it:

```js
function buildClusterIndex(blocks) {
  const features = blocks.map(b => ({
    type:     'Feature',
    geometry: { type: 'Point', coordinates: [b.lng, b.lat] },
    properties: {
      total_assessed: b.total_assessed,
      lot_count:      b.lot_count,
      borocode:       b.borocode,
      sample_address: b.sample_address,
    },
  }));
  clusterIndex = new Supercluster({
    radius:  60,
    maxZoom: 14,
    map:    p => ({ total_assessed: p.total_assessed, lot_count: p.lot_count }),
    reduce: (acc, p) => {
      acc.total_assessed += p.total_assessed;
      acc.lot_count      += p.lot_count;
    },
  });
  clusterIndex.load(features);
}

```

**Edit 3 — Call `buildClusterIndex` in `loadStaticBlocks` and update `doFetch`**

In `loadStaticBlocks`, find:
```js
    allBlocks = data.blocks;
```

Change to:
```js
    allBlocks = data.blocks;
    buildClusterIndex(allBlocks);
```

Then in `doFetch`, replace the else-branch (restored in Task 1 to a plain filter):
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

With:
```js
  } else {
    if (!clusterIndex) return;
    const sw       = bounds.getSouthWest();
    const ne       = bounds.getNorthEast();
    const features = clusterIndex.getClusters(
      [sw.lng, sw.lat, ne.lng, ne.lat],
      Math.round(zoom)
    );
    const rows = features.map(f => ({
      lat:            f.geometry.coordinates[1],
      lng:            f.geometry.coordinates[0],
      total_assessed: f.properties.total_assessed,
      lot_count:      f.properties.lot_count,
      borocode:       f.properties.borocode       || null,
      sample_address: f.properties.sample_address || null,
      block:          f.properties.block          || null,
      point_count:    f.properties.cluster ? f.properties.point_count : 1,
    }));
    renderData(rows, zoom, valueType);
  }
```

**Commit:**
```bash
git add static/nyc-heatmap/index.html
git commit -m "feat: build supercluster index and query on pan/zoom"
```

---

### Task 3: Update `renderData` to render cluster circles with count labels

**Files:**
- Modify: `static/nyc-heatmap/index.html`

One edit — replace the body of the `rows.forEach` loop inside `renderData`.

**Find** the current forEach body (~lines 453–493). The entire block to replace starts at `const lat = parseFloat(r.lat);` and ends at `markersLayer.addLayer(marker);`. Replace it with:

```js
    const lat = parseFloat(r.lat);
    const lng = parseFloat(r.lng);
    if (!lat || !lng) return;

    const value = getValue(r);
    if (value <= 0) return;

    const t         = logNorm(value, min, max);
    const color     = valueToColor(t);
    const lots      = parseInt(r.lot_count, 10) || 1;
    const isCluster = (r.point_count || 1) > 1;

    let marker;
    if (isCluster) {
      const size = Math.max(16, Math.min(40, radius * 2));
      const icon = L.divIcon({
        html: `<div style="background:${color};width:${size}px;height:${size}px;border-radius:50%;display:flex;align-items:center;justify-content:center;color:white;font-weight:700;font-size:${Math.max(9, Math.round(size * 0.35))}px;border:1.5px solid rgba(0,0,0,0.3);box-shadow:0 1px 3px rgba(0,0,0,0.4)">${r.point_count}</div>`,
        className:  '',
        iconSize:   [size, size],
        iconAnchor: [size / 2, size / 2],
      });
      marker = L.marker([lat, lng], { icon });
    } else {
      marker = L.circleMarker([lat, lng], {
        radius,
        fillColor:   color,
        color:       'rgba(0,0,0,0.25)',
        weight:      0.5,
        fillOpacity: 0.82,
      });
    }

    const popup = isCluster ? `
      <div class="popup-address">${r.point_count} blocks</div>
      <hr class="popup-divider" />
      <table class="popup-table">
        <tr><td>Total assessed</td><td>${fmt(r.total_assessed)}</td></tr>
        <tr><td>Blocks</td><td>${r.point_count.toLocaleString()}</td></tr>
        <tr><td>Avg per block</td><td>${fmt(parseFloat(r.total_assessed) / r.point_count)}</td></tr>
      </table>
    ` : `
      <div class="popup-address">${r.sample_address || `Block ${r.block}`}</div>
      <hr class="popup-divider" />
      <table class="popup-table">
        <tr><td>${isLotView ? 'Assessed value' : 'Block total'}</td><td>${fmt(r.total_assessed)}</td></tr>
        ${!isLotView && lots > 1 ? `
        <tr><td>Lots in block</td><td>${lots.toLocaleString()}</td></tr>
        <tr><td>Avg per lot</td><td>${fmt(parseFloat(r.total_assessed) / lots)}</td></tr>
        ` : ''}
        <tr><td>Borough</td><td>${BOROUGH_NAMES[String(r.borocode)] || `Boro ${r.borocode}`}</td></tr>
        ${r.block != null ? `<tr><td>Block #</td><td>${r.block}</td></tr>` : ''}
      </table>
    `;

    marker.bindPopup(popup);
    markersLayer.addLayer(marker);
```

**Verify manually** — open the file directly or via `hugo server`:
- At zoom 11–12: colored circles with block counts appear across the city
- Zooming in: circles split into smaller groups, eventually individual blocks
- Click a cluster: popup shows "N blocks", total, avg per block
- Click an individual block: popup shows address, borough, block # as before
- "Color by" toggle works at all zoom levels
- Lot view (zoom ≥ 15) unchanged

**Commit:**
```bash
git add static/nyc-heatmap/index.html
git commit -m "feat: render cluster circles with block count labels"
```
