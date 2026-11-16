#!/usr/bin/env bash
# Renders the terrarium's static set and mushroom sprites with Blender into
# static/terrarium/set/. The outputs are committed: the site build doesn't
# need Blender. Takes several minutes.
set -euo pipefail
run() { blender -b -P blender/terrarium.py -- "$@" 2>&1 | grep -E "Error|Traceback|done" ; }
# back and front are what you look at, so they get 2x for high-DPI screens;
# the glass is soft and the id layer is only read at CSS-pixel resolution
run --scale 2 --only back,front,rot,collapse --out static/terrarium/set
run --scale 1 --only glass,id --out static/terrarium/set
run --portrait --scale 2 --only back,front,rot,collapse --out static/terrarium/set/portrait
run --portrait --scale 1 --only glass,id --out static/terrarium/set/portrait
# the windowsill and room behind the jar, day and night, shared by both layouts
run --only room --out static/terrarium/set
# mushroom and bracket growth strips; clears the set to render quickly, so on its own
run --only grow --samples 48 --out static/terrarium/set
