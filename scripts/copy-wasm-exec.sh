#!/usr/bin/env bash
# Copies TinyGo's wasm_exec.js glue (which must match the TinyGo version that
# built myco.wasm) into the site.
set -euo pipefail
root="$(bash scripts/tinygo.sh env TINYGOROOT)"
cp "$root/targets/wasm_exec.js" static/terrarium/wasm_exec.js
