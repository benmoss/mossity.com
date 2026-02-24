# NYC Heatmap Supercluster Design

**Date:** 2026-02-24
**Status:** Approved

## Problem

The grid aggregation approach (GRID_ZOOM/GRID_SIZE) produced only ~60 cells
citywide and had cosmetic bugs ("Block undefined", "Block # | null" in popups).
Replace with supercluster.js, which does dynamic radius-based point clustering
with smooth zoom-in explode behavior.

## Changes

### Remove
- `GRID_ZOOM`, `GRID_SIZE` constants
- `aggregateToGrid` function
- Grid-zoom branch in `doFetch`

### Add
- supercluster.js from CDN (`https://unpkg.com/supercluster@8/dist/supercluster.min.js`)
- `clusterIndex` variable (Supercluster instance)
- `buildClusterIndex(blocks)` function — builds index from allBlocks after static load
- Updated `doFetch` block-zoom branch — queries index instead of filtering allBlocks
- Updated `renderData` — uses L.divIcon with count for clusters, L.circleMarker for individual blocks

## Supercluster Config

```js
const clusterIndex = new Supercluster({
  radius:  60,   // pixels — controls how aggressively nearby points merge
  maxZoom: 14,   // stop clustering at zoom 14; individual blocks appear
  map:    p => ({ total_assessed: p.total_assessed, lot_count: p.lot_count }),
  reduce: (acc, p) => {
    acc.total_assessed += p.total_assessed;
    acc.lot_count      += p.lot_count;
  },
});
```

## Data Flow

1. `loadStaticBlocks()` fetches `blocks.json` → stores in `allBlocks`
2. `buildClusterIndex(allBlocks)` converts blocks to GeoJSON features, loads into index
3. On pan/zoom (zoom 11–14): `clusterIndex.getClusters(bbox, zoom)` → normalize to flat rows → `renderData`
4. On zoom ≥ 15: live Socrata API (unchanged)

## GeoJSON Feature Shape

```js
{
  type: 'Feature',
  geometry: { type: 'Point', coordinates: [lng, lat] },
  properties: {
    total_assessed: b.total_assessed,
    lot_count:      b.lot_count,
    borocode:       b.borocode,
    sample_address: b.sample_address,
  }
}
```

## Normalized Row Shape (for renderData)

```js
{
  lat, lng,
  total_assessed,      // summed for clusters, original for individual blocks
  lot_count,           // summed for clusters
  borocode,            // original block value (null for clusters)
  sample_address,      // original block value (null for clusters)
  point_count,         // number of blocks in cluster (1 for individual blocks)
}
```

## Rendering

**Clusters** (`point_count > 1`): `L.divIcon` — styled div circle, same RdYlBu
color by value, block count centered inside.

**Individual blocks** (`point_count === 1`): `L.circleMarker` — unchanged from today.

**Popup for clusters**: total assessed, block count, avg per block. Omit
borough/address (don't aggregate meaningfully across blocks).

**Popup for individual blocks**: unchanged.

## Zoom Tiers

| Zoom | Renders | Source |
|------|---------|--------|
| < 11 | "Zoom in" message | — |
| 11–14 | Clusters + individual blocks | Supercluster index |
| ≥ 15 | Individual lots | Live Socrata API |
