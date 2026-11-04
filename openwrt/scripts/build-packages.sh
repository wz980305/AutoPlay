#!/bin/sh
# Build the AutoPlay packages for OpenWrt 25.12 (.apk) in the official SDK container:
#   autoplay and luci-app-autoplay (+ luci-i18n-autoplay-zh-cn): all architectures;
#   autoplay-jre: aarch64 (one package per OpenWrt aarch64 package architecture) and x86_64.
#   sh scripts/build-packages.sh OUT_DIR [autoplay-bundle.tar]
# Without a bundle the SDK downloads the AutoPlay release named in autoplay/Makefile and checks its
# hash; with one (an AutoPlay build not released yet) that file is used instead.
# Needs Docker; the container gets no privileges, host network or devices.
set -eu
out=$(realpath -m "${1:?Usage: build-packages.sh OUT_DIR [autoplay-bundle.tar]}")
bundle=${2:+$(realpath "$2")}
here=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
# The packages sit at the top of openwrt-autoplay, or under openwrt/ in the AutoPlay repository.
if [ -f "$here/../autoplay/Makefile" ]; then feed=$(CDPATH= cd -- "$here/.." && pwd); else feed=$(CDPATH= cd -- "$here/../../openwrt" && pwd); fi
image=${OPENWRT_SDK:-openwrt/sdk:x86-64-25.12.5}
# OpenWrt names aarch64 package architectures per CPU family; the JRE is the same for all of them.
jre_arches=${JRE_ARCHES:-"aarch64_generic aarch64_cortex-a53 aarch64_cortex-a72 aarch64_cortex-a76"}
version=$(sed -n 's/^PKG_VERSION:=//p' "$feed/autoplay/Makefile")
mkdir -p "$out"
# The Docker daemon may not see this checkout (a network mount): hand it local copies.
stage=$(mktemp -d "${TMPDIR:-/tmp}/autoplay-openwrt.XXXXXX")
trap 'rm -rf "$stage"' EXIT
mkdir "$stage/feed" "$stage/dl"
for package in autoplay autoplay-jre luci-app-autoplay; do cp -R "$feed/$package" "$stage/feed/"; done
local_hash=""
if [ -n "$bundle" ]; then
    cp "$bundle" "$stage/dl/autoplay-bundle-$version.tar"
    local_hash=$(sha256sum "$bundle" | cut -d" " -f1)
fi
mkdir -m 777 "$stage/out"
docker run --rm --cap-drop ALL --security-opt no-new-privileges \
    -v "$stage/feed:/feed:ro" -v "$stage/dl:/dl-local:ro" -v "$stage/out:/out" \
    -e JRE_ARCHES="$jre_arches" -e LOCAL_HASH="$local_hash" --entrypoint sh "$image" -c '
set -eu
cd /builder
# Only our feed and luci (for luci.mk and its host tools): dependencies are runtime-only (EXTRA_DEPENDS),
# so nothing from the package feeds is compiled.
echo "src-link autoplay /feed" >> feeds.conf.default
# Quiet when it works, the reason when it does not (a release run once failed here with no word, 2026-11-05).
# Network steps (the luci feed from git.openwrt.org, the Temurin download from GitHub) are tried three times.
quiet() { "$@" >/tmp/step.log 2>&1 || { echo "FAILED: $*" >&2; tail -60 /tmp/step.log >&2; return 1; }; }
retry() { for try in 1 2 3; do quiet "$@" && return 0; echo "retrying in $((try * 20)) s ($try/3): $*" >&2; sleep $((try * 20)); done; return 1; }
retry ./scripts/feeds update luci autoplay
quiet ./scripts/feeds install -p autoplay -a
quiet make defconfig
cp /dl-local/* dl/ 2>/dev/null || true
build() {
    for try in 1 2 3; do
        make "$@" V=s >/tmp/build.log 2>&1 && return 0
        echo "FAILED ($try/3): make $*" >&2
        grep -B5 -A5 "ERROR:\|Hash mismatch\|hash\|Download failed\|curl:\|wget:" /tmp/build.log | tail -40 >&2 || tail -60 /tmp/build.log >&2
        # Only a failed download is worth another try; anything else fails now.
        grep -q "Download failed\|curl:\|wget:\|Could not resolve\|Connection reset\|timed out" /tmp/build.log || exit 1
        sleep $((try * 20))
    done
    exit 1
}
# A local bundle has its own hash; set it for this package only (the JRE keeps the one in its Makefile).
build package/autoplay/compile ${LOCAL_HASH:+PKG_HASH=$LOCAL_HASH}
build package/luci-app-autoplay/compile package/autoplay-jre/compile
cp bin/packages/*/autoplay/autoplay-[0-9]*.apk bin/packages/*/autoplay/luci-*.apk /out/
# The JRE package names no architecture in its file name: give each copy its own.
for jre in bin/packages/*/autoplay/autoplay-jre-*.apk; do cp "$jre" "/out/$(basename "$jre" .apk)_x86_64.apk"; done
for arch in $JRE_ARCHES; do
    rm -f bin/packages/*/autoplay/autoplay-jre-*.apk
    make package/autoplay-jre/clean >/dev/null 2>&1
    build package/autoplay-jre/compile JRE_CPU=aarch64 PKGARCH=$arch
    for jre in bin/packages/*/autoplay/autoplay-jre-*.apk; do cp "$jre" "/out/$(basename "$jre" .apk)_$arch.apk"; done
done
for apk in /out/*.apk; do
    echo "$(basename "$apk"): $(staging_dir/host/bin/apk adbdump "$apk" | sed -n "s/^  arch: //p")"
done
'
cp "$stage"/out/*.apk "$out"/
(cd "$out" && sha256sum *.apk > SHA256SUMS)
