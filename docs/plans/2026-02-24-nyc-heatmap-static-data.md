# NYC Heatmap Static Data Performance Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Replace live Socrata API calls for block-level data with a pre-built static JSON loaded once on startup, making pan/zoom instant.

**Architecture:** Run the existing Python fetcher to produce `static/nyc-heatmap/data/blocks.json` (~8 MB), commit it, then modify the map to load it once into memory and filter client-side on every pan/zoom. Lot-level zoom (≥ 15) keeps the existing live API call unchanged.

**Tech Stack:** Hugo static site, vanilla JS, Leaflet.js, Python 3 (data generation only)

---

### Task 1: Fix Python script output key (`boro` → `borocode`)

**Files:**
- Modify: `scripts/nyc_heatmap_data.py:165`

The `aggregate_by_block` function outputs `"boro"` but the map now reads `r.borocode` (fixed in a prior commit). Align the output key so the static JSON matches the live API field name.

**Step 1: Make the change**

In `scripts/nyc_heatmap_data.py`, find the `result.append({...})` block (~line 159) and change:

```python
# Before
"boro":           b["boro"],
"boro_name":      BOROUGH_NAMES.get(b["boro"], "Unknown"),

# After
"borocode":       b["boro"],
"boro_name":      BOROUGH_NAMES.get(b["boro"], "Unknown"),
```

**Step 2: Verify the change looks right**

```bash
grep -n '"boro"' scripts/nyc_heatmap_data.py
```

Expected: zero matches (all occurrences should now be `"borocode"` or internal variable names like `b["boro"]`).

**Step 3: Commit**

```bash
git add scripts/nyc_heatmap_data.py
git commit -m "fix: align Python script output key to borocode"
```

---

### Task 2: Generate the static JSON file

**Files:**
- Create: `static/nyc-heatmap/data/blocks.json`

**Step 1: Run the fetcher**

From the repo root:

```bash
python scripts/nyc_heatmap_data.py
```

This pages through all ~850k PLUTO records and writes `static/nyc-heatmap/data/blocks.json`. Expect it to take 5–15 minutes and print progress like:

```
Fetching NYC MapPLUTO data — all boroughs
  Fetched  50,000 records  (running total: 50,000)
  ...
Aggregating by block…
Blocks:             75,432
Total assessed:     $1,234,567,890,000
Saved → static/nyc-heatmap/data/blocks.json  (8.2 MB)
```

**Step 2: Spot-check the output**

```bash
python -c "
import json
d = json.load(open('static/nyc-heatmap/data/blocks.json'))
print('block count:', d['stats']['block_count'])
print('first block:', d['blocks'][0])
"
```

Expected: block count ~70–80k, first block has keys `lat`, `lng`, `total_assessed`, `lot_count`, `borocode`, `block`, `sample_address`.

**Step 3: Commit**

```bash
git add static/nyc-heatmap/data/blocks.json
git commit -m "data: add pre-generated PLUTO block data for heatmap"
```

---

### Task 3: Update the map to use static data for block view

**Files:**
- Modify: `static/nyc-heatmap/index.html`

Three changes: (a) add an in-memory store + loader, (b) replace `fetchBlocks` with a bounds filter, (c) kick off data load before the map starts rendering.

**Step 1: Add `allBlocks` variable and `loadStaticBlocks` function**

Find the `// Load orchestration` comment block (~line 549). Insert immediately before it:

```js
// ============================================================
// Static block data
// ============================================================
let allBlocks = null;

async function loadStaticBlocks() {
  document.getElementById('loading').style.display = 'flex';
  try {
    const resp = await fetch('/nyc-heatmap/data/blocks.json');
    if (!resp.ok) throw new Error(`Failed to load block data: HTTP ${resp.status}`);
    const data = await resp.json();
    allBlocks = data.blocks;
  } catch (err) {
    console.error('Could not load static block data:', err);
    const banner = document.getElementById('error-banner');
    banner.textContent = `Could not load map data: ${err.message}`;
    banner.style.display = 'block';
  } finally {
    document.getElementById('loading').style.display = 'none';
  }
}

```

**Step 2: Replace the block-view branch in `doFetch`**

Find this section in `doFetch` (~line 574):

```js
  document.getElementById('loading').style.display       = 'flex';
  document.getElementById('error-banner').style.display  = 'none';

  try {
    const bounds    = map.getBounds();
    const valueType = document.getElementById('value-type').value;
    const rows      = zoom >= LOT_ZOOM
      ? await fetchLots(bounds)
      : await fetchBlocks(bounds);
    renderData(rows, zoom, valueType);
  } catch (err) {
    console.error(err);
    const banner = document.getElementById('error-banner');
    banner.textContent = `Could not load data: ${err.message}`;
    banner.style.display = 'block';
    setTimeout(() => { banner.style.display = 'none'; }, 7000);
  } finally {
    document.getElementById('loading').style.display = 'none';
  }
```

Replace with:

```js
  document.getElementById('error-banner').style.display = 'none';

  const bounds    = map.getBounds();
  const valueType = document.getElementById('value-type').value;

  if (zoom >= LOT_ZOOM) {
    document.getElementById('loading').style.display = 'flex';
    try {
      const rows = await fetchLots(bounds);
      renderData(rows, zoom, valueType);
    } catch (err) {
      console.error(err);
      const banner = document.getElementById('error-banner');
      banner.textContent = `Could not load data: ${err.message}`;
      banner.style.display = 'block';
      setTimeout(() => { banner.style.display = 'none'; }, 7000);
    } finally {
      document.getElementById('loading').style.display = 'none';
    }
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

**Step 3: Replace the initial kickoff at the bottom**

Find (~line 602):

```js
// Kick off initial load
scheduleFetch();
```

Replace with:

```js
// Load static block data, then start rendering
loadStaticBlocks().then(scheduleFetch);
```

**Step 4: Verify manually**

Serve the site locally:

```bash
hugo server
```

Open `http://localhost:1313/nyc-heatmap/`. Confirm:
- Loading spinner appears briefly on startup (JSON download)
- Map renders block circles after load
- Panning and zooming is instant with no network calls (check DevTools Network tab — no Socrata requests at zoom < 15)
- Zooming in past level 15 still fires a Socrata request and shows individual lots
- "Color by" toggle re-renders instantly

**Step 5: Commit**

```bash
git add static/nyc-heatmap/index.html
git commit -m "perf: load block data from static JSON, eliminate per-pan API calls"
```

---

### Task 4: Clean up (remove now-unused `fetchBlocks`)

**Files:**
- Modify: `static/nyc-heatmap/index.html`

**Step 1: Delete `fetchBlocks`**

Remove the entire `fetchBlocks` function (~lines 387–407). It is no longer called.

**Step 2: Verify the page still works**

```bash
hugo server
```

Open `http://localhost:1313/nyc-heatmap/` and confirm map still loads correctly.

**Step 3: Commit**

```bash
git add static/nyc-heatmap/index.html
git commit -m "refactor: remove unused fetchBlocks (replaced by static JSON)"
```
