#!/bin/sh
# Build everything one AutoPlay release consists of, check it, and (with a key) sign and publish it (docs/RELEASE.md).
#
#   sh box/scripts/release.sh VERSION [OUT_DIR]                # build + check; nothing leaves this machine
#   AUTOPLAY_RELEASE_KEY_FILE=~/autoplay-release.key \
#   sh box/scripts/release.sh VERSION [OUT_DIR] --publish      # ... then sign and `gh release create vVERSION`
#
# Steps (each also runnable by hand; the release workflow runs the same script):
#   1. the version in the tree must be VERSION everywhere (receiver, web, OpenWrt package);
#   2. receiver: ./gradlew build :server:installDist (JDK 21, Gradle network);
#   3. web: npm ci && npm run build;
#   4. bundle: box/scripts/build-bundle.sh (javac, pip, curl, unzip; two pinned downloads);
#   5. packages: openwrt/scripts/build-packages.sh in the OpenWrt SDK container (Docker);
#   6. manifest: box/scripts/make-update-manifest.py with this version's CHANGELOG section as the notes;
#   7. --publish: sign autoplay-update.json and SHA256SUMS with the Ed25519 release key, verify both against the
#      public key the box ships (box/scripts/onecloud/update-key.pem), create the GitHub Release with every file.
# OUT_DIR (default out/release-VERSION) ends up as:
#   autoplay/autoplay-bundle-VERSION.tar, autoplay/autoplay-update.json[.sig], openwrt/*.apk, openwrt/SHA256SUMS[.sig]
set -eu
version=${1:?Usage: release.sh VERSION [OUT_DIR] [--publish]}
shift
out=""
publish=no
for arg in "$@"; do
    case "$arg" in
        --publish) publish=yes ;;
        --no-publish) publish=no ;;
        *) out=$arg ;;
    esac
done
repo=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
out=$(realpath -m "${out:-$repo/out/release-$version}")
echo "$version" | grep -Eq '^[0-9]+(\.[0-9]+)+$' || { echo "release.sh: version must look like 1.3.1" >&2; exit 1; }
say() { printf '\n== %s\n' "$*"; }

say "1. the tree is version $version"
fail=0
check() { [ "$2" = "$version" ] || { echo "   $1 says '$2', not $version" >&2; fail=1; }; }
check "receiver/build.gradle.kts" "$(sed -n 's/^ *version = "\(.*\)"/\1/p' "$repo/receiver/build.gradle.kts" | head -1)"
check "receiver/server Main.kt fallback" "$(sed -n 's/.*implementationVersion ?: "\(.*\)".*/\1/p' "$repo/receiver/server/src/main/kotlin/com/playport/server/Main.kt" | head -1)"
check "receiver/web/package.json" "$(sed -n 's/^ *"version": "\(.*\)",/\1/p' "$repo/receiver/web/package.json" | head -1)"
check "openwrt/autoplay/Makefile" "$(sed -n 's/^PKG_VERSION:=//p' "$repo/openwrt/autoplay/Makefile")"
check "openwrt/luci-app-autoplay/Makefile depends" "$(sed -n 's/^LUCI_EXTRA_DEPENDS:=autoplay (>=\([0-9.]*\)).*/\1/p' "$repo/openwrt/luci-app-autoplay/Makefile")"
grep -q "^## \[$version\]" "$repo/CHANGELOG.md" || { echo "   CHANGELOG.md has no '## [$version]' section" >&2; fail=1; }
[ "$fail" = 0 ] || exit 1

say "2. receiver (Gradle)"
(cd "$repo/receiver" && sh ./gradlew --no-daemon --console=plain -q build :server:installDist)
set -- "$repo"/receiver/server/build/install/server/lib/server-*.jar
[ "$#" = 1 ] && [ -s "$1" ] || { echo "   expected one server jar, found: $*" >&2; exit 1; }

say "3. web viewer (npm)"
(cd "$repo/receiver/web" && npm ci --no-audit --no-fund --silent && npm run -s build)

say "4. program bundle"
rm -rf "$out"
mkdir -p "$out/autoplay" "$out/openwrt"
AUTOPLAY_VERSION=$version sh "$repo/box/scripts/build-bundle.sh" "$out/autoplay/autoplay-bundle-$version.tar"
(cd "$out/autoplay" && sha256sum "autoplay-bundle-$version.tar" > "autoplay-bundle-$version.tar.sha256")

say "5. OpenWrt packages (Docker SDK)"
sh "$repo/openwrt/scripts/build-packages.sh" "$out/openwrt" "$out/autoplay/autoplay-bundle-$version.tar"

say "6. update manifest"
# The notes are this version's CHANGELOG section (heading line excluded), the same text the box shows.
awk -v v="$version" '/^## \[/{p=($0 ~ "^## \\[" v "\\]")} p' "$repo/CHANGELOG.md" | sed '1d' > "$out/notes.md"
python3 "$repo/box/scripts/make-update-manifest.py" "$version" "$out/notes.md" "$out"
python3 "$repo/box/scripts/make-update-manifest.py" --check "$out/autoplay/autoplay-update.json" "$out/openwrt/SHA256SUMS" \
    "$out/autoplay/autoplay-bundle-$version.tar.sha256" "$version"

if [ "$publish" != yes ]; then
    say "built, not published: $out"
    exit 0
fi

say "7. sign and publish"
key=${AUTOPLAY_RELEASE_KEY_FILE:?AUTOPLAY_RELEASE_KEY_FILE=<the Ed25519 private key> is needed to publish}
public="$repo/box/scripts/onecloud/update-key.pem"
for file in "$out/autoplay/autoplay-update.json" "$out/openwrt/SHA256SUMS"; do
    openssl pkeyutl -sign -inkey "$key" -rawin -in "$file" -out "$file.sig"
    # The box only trusts the public key it ships: a signature it cannot verify would be a release nobody can install.
    openssl pkeyutl -verify -pubin -inkey "$public" -rawin -in "$file" -sigfile "$file.sig" | grep -q "Signature Verified Successfully" \
        || { echo "   $file.sig does not verify with $public: wrong key" >&2; exit 1; }
done
gh release create "v$version" --title "AutoPlay $version" --notes-file "$out/notes.md" --verify-tag \
    "$out"/openwrt/*.apk "$out/openwrt/SHA256SUMS" "$out/openwrt/SHA256SUMS.sig" \
    "$out/autoplay/autoplay-update.json" "$out/autoplay/autoplay-update.json.sig" \
    "$out/autoplay/autoplay-bundle-$version.tar" "$out/autoplay/autoplay-bundle-$version.tar.sha256"
say "published v$version"
