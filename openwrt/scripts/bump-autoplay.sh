#!/bin/sh
# Move the autoplay package to an AutoPlay release: its version, the release's program bundle hash, and
# release 1 of the package.
#   sh scripts/bump-autoplay.sh VERSION autoplay-bundle-VERSION.tar
# The bundle is the one attached to the AutoPlay release vVERSION (download it first).
set -eu
version=${1:?Usage: bump-autoplay.sh VERSION autoplay-bundle-VERSION.tar}
bundle=${2:?Usage: bump-autoplay.sh VERSION autoplay-bundle-VERSION.tar}
echo "$version" | grep -Eq '^[0-9]{4}\.[0-9]{1,2}\.[0-9]{1,2}(\.[0-9]+)?$' || { echo "version like 2026.10.12" >&2; exit 1; }
here=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
if [ -f "$here/../autoplay/Makefile" ]; then makefile="$here/../autoplay/Makefile"; else makefile="$here/../../openwrt/autoplay/Makefile"; fi
tar -tf "$bundle" ./supervisor_openwrt.py >/dev/null 2>&1 || { echo "$bundle is not an AutoPlay program bundle" >&2; exit 1; }
hash=$(sha256sum "$bundle" | cut -d" " -f1)
sed -i -e "s/^PKG_VERSION:=.*/PKG_VERSION:=$version/" -e "s/^PKG_RELEASE:=.*/PKG_RELEASE:=1/" \
    -e "s/^PKG_HASH:=.*/PKG_HASH:=$hash/" "$makefile"
grep -E '^PKG_(VERSION|RELEASE|HASH):=' "$makefile"
