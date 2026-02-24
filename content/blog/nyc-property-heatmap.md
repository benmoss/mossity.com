+++
title = "NYC Property Values: Block by Block"
date = "2026-02-24T00:00:00-05:00"

description = "An interactive heatmap of NYC assessed property values at block-level resolution, built with Leaflet.js and NYC Open Data's MapPLUTO dataset."

+++

**[→ Open the interactive map](/nyc-heatmap/)**

NYC's Department of Finance publishes assessed values for every one of the city's ~850,000 tax lots through the [MapPLUTO dataset](https://data.cityofnewyork.us/City-Government/Primary-Land-Use-Tax-Lot-Output-PLUTO-/64uk-42ks) on NYC Open Data. The map above pulls that data live and colors each block by its total assessed value on a logarithmic scale (blue = low, red = high).

A few things that stand out:

- **Midtown Manhattan** blocks routinely hit $1–5B in total assessed value — a single city block can be assessed at more than the entire property tax base of a small city.
- **The waterfront premium** is clearly visible in both Brooklyn and Queens, where blocks adjacent to the water are noticeably warmer than those a few blocks inland.
- **The Bronx / Staten Island contrast** with Manhattan is stark. The color scale is logarithmic, so even visually similar blocks can differ by an order of magnitude.

### How it works

The map uses [Leaflet.js](https://leafletjs.com/) with CartoDB dark tiles (which are built on OpenStreetMap data). On each pan or zoom, it queries the Socrata API with a spatial `WHERE latitude between ... AND longitude between ...` filter, groups by borough+block server-side, and renders a colored circle at each block centroid. Zoom in past level 15 and it switches to individual tax lots.

Color is mapped logarithmically because assessed values span roughly six orders of magnitude ($1K to $5B+). The RdYlBu diverging colormap keeps mid-range values visible rather than everything collapsing to the extremes.

### Running the data fetcher locally

If you want to download the full dataset and process it offline:

```bash
python scripts/nyc_heatmap_data.py                # all five boroughs
python scripts/nyc_heatmap_data.py --boro 1       # Manhattan only
python scripts/nyc_heatmap_data.py --boro 3 --output /tmp/brooklyn.json
```

This writes a block-aggregated JSON to `static/nyc-heatmap/data/blocks.json` (~8 MB for all boroughs). The interactive map doesn't require this file — it fetches on demand — but it's useful for offline analysis or building a static snapshot.
