#!/usr/bin/env bash
# Upload a generated repository tree to the bucket that serves it.
#
#   publish/publish-repo.sh [--dry-run] <bucket-url> <repo-dir>
#
# Two rules decide everything here.
#
# The pool is APPEND-ONLY. A published filename keeps its bytes forever, so
# packages upload with --no-clobber: an existing object is never rewritten, and
# shipping a fix means bumping the package revision instead. Nothing is ever
# deleted — old index generations stay reachable so a client holding an older
# Release can still fetch what that Release names.
#
# A publish must look ATOMIC to clients. apt and dnf fetch an entry point, then
# the indexes it hashes, then the packages those hash — so the upload runs in
# that order backwards: packages, then indexes, then the entry points last. Up
# to the final step a client sees the previous, wholly consistent repository.
#
# Cache-Control is set per object, because the CDN honours origin headers:
# immutable for anything content-addressed, no-cache for the mutable paths
# clients re-fetch.
#
# Requires: gcloud, already authenticated.
set -euo pipefail

DRY_RUN=
if [ "${1:-}" = "--dry-run" ]; then
    DRY_RUN=1
    shift
fi
BUCKET=${1:?usage: publish-repo.sh [--dry-run] <bucket-url> <repo-dir>}
REPO=${2:?usage: publish-repo.sh [--dry-run] <bucket-url> <repo-dir>}

IMMUTABLE="public, max-age=31536000, immutable"
VOLATILE="no-cache"

# upload <cache-control> <extra-flag...> -- <source...> <destination>
upload() {
    if [ -n "$DRY_RUN" ]; then
        echo "  would upload: gcloud storage cp $*"
        return 0
    fi
    gcloud storage cp "$@"
}

# A scope that touched only one family leaves the other's tree absent, so a
# glob matching nothing is normal.
present() {
    local path
    for path in "$@"; do
        [ -e "$path" ] && return 0
    done
    return 1
}

# Whereas a file that should be there and is not is a broken publish, not an
# empty one — say which, rather than letting gcloud complain about an argument.
require() {
    local path
    for path in "$@"; do
        [ -f "$path" ] || {
            echo "$path is missing; the repository is incomplete, refusing to publish." >&2
            exit 1
        }
    done
}

echo "== 1/3 packages (append-only, never overwritten)"
for pool in "$REPO"/deb/pool/*/; do
    [ -d "$pool" ] || continue
    suite=$(basename "$pool")
    upload --recursive --no-clobber --cache-control="$IMMUTABLE" \
        "$pool" "$BUCKET/deb/pool/"
    echo "   deb/pool/$suite"
done
for repodir in "$REPO"/rpm/*/*/; do
    [ -d "$repodir" ] || continue
    present "$repodir"*.rpm || continue
    rel=${repodir#"$REPO"/}
    upload --no-clobber --cache-control="$IMMUTABLE" \
        "$repodir"*.rpm "$BUCKET/${rel%/}/"
    echo "   ${rel%/}"
done

echo "== 2/3 indexes"
for byhash in "$REPO"/deb/dists/*/*/binary-*/by-hash; do
    [ -d "$byhash" ] || continue
    rel=${byhash#"$REPO"/}
    # Content-addressed, so these are immutable and must land before the
    # Release that names their hashes.
    upload --recursive --no-clobber --cache-control="$IMMUTABLE" \
        "$byhash" "$BUCKET/$(dirname "$rel")/"
done
for pkgs in "$REPO"/deb/dists/*/*/binary-*/Packages; do
    [ -f "$pkgs" ] || continue
    rel=${pkgs#"$REPO"/}
    require "$pkgs" "$pkgs.gz"
    upload --cache-control="$VOLATILE" "$pkgs" "$pkgs.gz" "$BUCKET/$(dirname "$rel")/"
done
for repodata in "$REPO"/rpm/*/*/repodata; do
    [ -d "$repodata" ] || continue
    rel=${repodata#"$REPO"/}
    # The <hash>-*.xml.gz files are content-addressed; repomd.xml is not and is
    # deliberately left for the last pass.
    present "$repodata"/*-*.xml.gz || continue
    upload --no-clobber --cache-control="$IMMUTABLE" "$repodata"/*-*.xml.gz "$BUCKET/$rel/"
done

echo "== 3/3 entry points (last: this is what makes the publish visible)"
for dists in "$REPO"/deb/dists/*/; do
    [ -d "$dists" ] || continue
    rel=${dists#"$REPO"/}
    require "$dists"Release "$dists"InRelease "$dists"Release.gpg
    upload --cache-control="$VOLATILE" \
        "$dists"Release "$dists"InRelease "$dists"Release.gpg "$BUCKET/${rel%/}/"
    echo "   ${rel%/}"
done
for repodata in "$REPO"/rpm/*/*/repodata; do
    [ -d "$repodata" ] || continue
    rel=${repodata#"$REPO"/}
    require "$repodata"/repomd.xml "$repodata"/repomd.xml.asc
    upload --cache-control="$VOLATILE" \
        "$repodata"/repomd.xml "$repodata"/repomd.xml.asc "$BUCKET/$rel/"
    echo "   $rel"
done

if [ -n "$DRY_RUN" ]; then
    echo "Dry run: nothing was uploaded."
else
    echo "Published to $BUCKET."
fi
