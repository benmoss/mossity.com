#!/usr/bin/env bash
# Runs a pinned TinyGo, fetching it into .pixi/ on first use. TinyGo isn't on
# conda-forge; pixi provides the Go toolchain and wasm-opt (binaryen) it needs.
set -euo pipefail
VERSION=0.44.0
case "$(uname -s)-$(uname -m)" in
  Darwin-arm64) plat=darwin-arm64 sha=696a37db149c2c37ed0da96cc1f2cca2630fca0c4dd19823a2a481c9b4a6a748 ;;
  Linux-x86_64) plat=linux-amd64 sha=ed0f45543a49ff2a99120a5a1b8814a0750e1fda1a66f8e2a0a172576134aaf9 ;;
  *) echo "no TinyGo build pinned for $(uname -sm)" >&2; exit 1 ;;
esac
dir=.pixi/tinygo-$VERSION
if [[ ! -x $dir/bin/tinygo ]]; then
  tmp=$(mktemp -d)
  trap 'rm -rf "$tmp"' EXIT
  echo "fetching TinyGo $VERSION ($plat)" >&2
  curl -fsSL "https://github.com/tinygo-org/tinygo/releases/download/v$VERSION/tinygo$VERSION.$plat.tar.gz" -o "$tmp/tinygo.tgz"
  if command -v sha256sum >/dev/null; then
    echo "$sha  $tmp/tinygo.tgz" | sha256sum -c - >/dev/null
  else
    echo "$sha  $tmp/tinygo.tgz" | shasum -a 256 -c - >/dev/null
  fi
  mkdir "$tmp/x"
  tar xzf "$tmp/tinygo.tgz" -C "$tmp/x"
  rm -rf "$dir"
  mv "$tmp/x/tinygo" "$dir"
fi
exec "$dir/bin/tinygo" "$@"
