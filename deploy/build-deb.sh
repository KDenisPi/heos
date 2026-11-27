#!/bin/bash
# Build build/heos-home_<version>_all.deb: our code, the built web app, the
# systemd unit and the install scripts. No Python environment inside; on the
# Pi run /opt/heos-home/setup-env.sh once after the first install.
#
#     deploy/build-deb.sh              # builds the web app first (needs Node)
#     deploy/build-deb.sh --skip-web   # use the existing web/dist
#
# The version comes from pyproject.toml; VERSION=0.1.0-2 overrides it.
set -euo pipefail

ROOT=$(cd "$(dirname "$0")/.." && pwd)
cd "$ROOT"
VERSION=${VERSION:-$(sed -n 's/^version = "\(.*\)"/\1/p' pyproject.toml | head -1)}
OUT=${OUT_DIR:-$ROOT/build}
PKG=$OUT/heos-home_${VERSION}_all
MAINTAINER="$(git config user.name) <$(git config user.email)>"

if [ "${1:-}" != "--skip-web" ]; then
    # Node is often unpacked under ~/.local/node instead of being on PATH.
    if ! command -v npm >/dev/null && [ -x "$HOME/.local/node/bin/npm" ]; then
        export PATH="$HOME/.local/node/bin:$PATH"
    fi
    if ! command -v npm >/dev/null; then
        echo "npm not found: put Node on PATH, or run with --skip-web to use the existing web/dist" >&2
        exit 1
    fi
    (cd web && npm ci --no-audit --no-fund && npm run build)
fi
[ -f web/dist/index.html ] || { echo "web/dist is missing; build the web app first" >&2; exit 1; }

rm -rf "$PKG"
install -d "$PKG/DEBIAN" "$PKG/opt/heos-home/src" "$PKG/opt/heos-home/web" \
    "$PKG/lib/systemd/system" "$PKG/etc/heos-home" "$PKG/usr/share/doc/heos-home"

rsync -a --exclude __pycache__ --exclude '*.pyc' src/heos_home "$PKG/opt/heos-home/src/"
rsync -a web/dist "$PKG/opt/heos-home/web/"
install -m 0644 deploy/requirements.txt "$PKG/opt/heos-home/"
install -m 0755 deploy/setup-env.sh "$PKG/opt/heos-home/"
install -m 0644 deploy/heos-home.service "$PKG/lib/systemd/system/"
install -m 0640 deploy/env.example "$PKG/etc/heos-home/env"
install -m 0644 README.md "$PKG/usr/share/doc/heos-home/"

# Plain permissions whatever the local umask was.
find "$PKG" -type d -exec chmod 0755 {} +
find "$PKG/opt" "$PKG/lib" "$PKG/usr" -type f ! -name setup-env.sh -exec chmod 0644 {} +

SIZE=$(du -sk --exclude=DEBIAN "$PKG" | cut -f1)
sed -e "s|@VERSION@|$VERSION|" -e "s|@MAINTAINER@|$MAINTAINER|" -e "s|@SIZE@|$SIZE|" \
    deploy/debian/control.in > "$PKG/DEBIAN/control"
install -m 0644 deploy/debian/conffiles "$PKG/DEBIAN/"
install -m 0755 deploy/debian/postinst deploy/debian/prerm deploy/debian/postrm "$PKG/DEBIAN/"

dpkg-deb --build --root-owner-group -Zxz "$PKG" "$OUT/heos-home_${VERSION}_all.deb" >/dev/null
rm -rf "$PKG"
echo "Built $OUT/heos-home_${VERSION}_all.deb"
