#!/usr/bin/env bash
# Regenerate the apt and dnf indexes for the slice of the published repository
# that a publish invalidates.
#
#   publish/make-repo.sh <bucket-url> <repo-dir> <package-dir> <target>...
#
#   publish/make-repo.sh gs://some-bucket repo output deb-bookworm rpm-el9
set -euo pipefail

BUCKET=${1:?usage: make-repo.sh <bucket-url> <repo-dir> <package-dir> <target>...}
REPO=${2:?usage: make-repo.sh <bucket-url> <repo-dir> <package-dir> <target>...}
PKGDIR=${3:?usage: make-repo.sh <bucket-url> <repo-dir> <package-dir> <target>...}
shift 3
[ $# -gt 0 ] || { echo "no targets given" >&2; exit 1; }

ORIGIN=${REPO_ORIGIN:-OpenSSL}
LABEL=${REPO_LABEL:-OpenSSL}
DESCRIPTION=${REPO_DESCRIPTION:-OpenSSL upstream packages}
COMPONENT=${REPO_COMPONENT:-main}
DEB_ARCHES=${REPO_DEB_ARCHES:-amd64 arm64}
RPM_ARCHES=${REPO_RPM_ARCHES:-x86_64 aarch64}

# An absent prefix is the first publish, not an error.
sync_down() {
    if gcloud storage ls "$1/**" >/dev/null 2>&1; then
        mkdir -p "$2" && gcloud storage rsync -r "$1" "$2"
    else
        echo "no existing $1 — first publish"
    fi
}

# Every package, FIPS modules included, is built per release and lives under
# <pkg>/<family>/<release>/. Prints "<package-name><TAB><source-directory>".
sources() {
    local family=$1 release=$2 pkgdir
    while IFS= read -r pkgdir; do
        if [ -d "$pkgdir/$family/$release" ]; then
            printf '%s\t%s\n' "$(basename "$pkgdir")" "$pkgdir/$family/$release"
        fi
    done < <(find "$PKGDIR" -mindepth 1 -maxdepth 1 -type d | sort)
}

# The pool is per suite
make_deb_suite() {
    local suite=$1 pool="$REPO/deb/pool/$1" dists="$REPO/deb/dists/$1" pkg dir arch d f

    sync_down "$BUCKET/deb/pool/$suite" "$pool"
    sync_down "$BUCKET/deb/dists/$suite" "$dists"

    # The pool holds both architectures; apt-ftparchive --arch splits them at
    # index time (and includes Architecture: all in each).
    while IFS=$'\t' read -r pkg dir; do
        mkdir -p "$pool/$COMPONENT/o/$pkg"
        cp -f "$dir"/* "$pool/$COMPONENT/o/$pkg/"
    done < <(sources deb "$suite")

    for arch in $DEB_ARCHES; do
        d="$dists/$COMPONENT/binary-$arch"
        mkdir -p "$d"
        (cd "$REPO/deb" && apt-ftparchive --arch "$arch" packages "pool/$suite") >"$d/Packages"
        gzip -9nkf "$d/Packages"
    done

    # Release last: apt-ftparchive walks the tree and checksums what it finds.
    (cd "$REPO/deb" && apt-ftparchive release "dists/$suite" \
        -o APT::FTPArchive::Release::Origin="$ORIGIN" \
        -o APT::FTPArchive::Release::Label="$LABEL" \
        -o APT::FTPArchive::Release::Suite="$suite" \
        -o APT::FTPArchive::Release::Codename="$suite" \
        -o APT::FTPArchive::Release::Components="$COMPONENT" \
        -o APT::FTPArchive::Release::Architectures="$DEB_ARCHES" \
        -o APT::FTPArchive::Release::Description="$DESCRIPTION" \
        -o APT::FTPArchive::Release::Acquire-By-Hash=yes) >"$dists/Release"

    # by-hash copies after Release, keyed on the hashes it just recorded, so an
    # index stays fetchable while a CDN still serves the previous Release.
    for arch in $DEB_ARCHES; do
        d="$dists/$COMPONENT/binary-$arch"
        mkdir -p "$d/by-hash/SHA256"
        for f in Packages Packages.gz; do
            cp -f "$d/$f" "$d/by-hash/SHA256/$(sha256sum "$d/$f" | cut -d' ' -f1)"
        done
        echo "== $suite/$arch: $(grep -c '^Package: ' "$d/Packages") packages"
    done
}

make_rpm_repo() {
    local el=$1 basearch pkg dir r

    for basearch in $RPM_ARCHES; do
        r="$REPO/rpm/$el/$basearch"
        sync_down "$BUCKET/rpm/$el/$basearch" "$r"
        mkdir -p "$r"

        # createrepo_c indexes the whole directory, so unlike the deb pool this
        # one has to hold a single architecture.
        while IFS=$'\t' read -r pkg dir; do
            find "$dir" -maxdepth 1 -type f \
                \( -name "*.$basearch.rpm" -o -name '*.noarch.rpm' \) \
                -exec cp -f {} "$r/" \;
        done < <(sources rpm "$el")

        createrepo_c --quiet --update --general-compress-type=gz "$r"
        echo "== $el/$basearch: $(find "$r" -maxdepth 1 -name '*.rpm' | wc -l) packages"
    done
}

for TARGET in "$@"; do
    case "$TARGET" in
    deb-*) make_deb_suite "${TARGET#deb-}" ;;
    rpm-*) make_rpm_repo "${TARGET#rpm-}" ;;
    *)
        echo "unrecognised target '$TARGET'; expected deb-<suite> or rpm-el<n>" >&2
        exit 1
        ;;
    esac
done
