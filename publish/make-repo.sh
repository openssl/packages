#!/usr/bin/env bash
# Regenerate the apt and dnf indexes for the slice of the published repository
# that a publish invalidates.
#
#   publish/make-repo.sh --packages "<name>..." \
#       <bucket-url> <repo-dir> <package-dir> <target>...
#
#   publish/make-repo.sh --packages "$(make -s plan-packages GOALS=stream)" \
#       gs://some-bucket repo output deb-bookworm rpm-el9
set -euo pipefail

USAGE='usage: make-repo.sh --packages "<name>..." <bucket-url> <repo-dir> <package-dir> <target>...'

# Which source packages to index. Required, and an argument rather than one of
# the REPO_* overrides below: those are deployment settings with sane defaults,
# while this decides what reaches the repository and differs every run. A run
# can build more than it publishes — a validated-module publish builds the
# streams its modules are tested against — so a forgotten value must be an error
# and not "index whatever the build left behind".
PACKAGES=
while [ $# -gt 0 ]; do
    case "$1" in
        --packages) PACKAGES=${2:?$USAGE}; shift 2 ;;
        --) shift; break ;;
        -*) echo "unknown option $1" >&2; echo "$USAGE" >&2; exit 1 ;;
        *) break ;;
    esac
done
[ -n "$PACKAGES" ] || { echo "--packages is required" >&2; echo "$USAGE" >&2; exit 1; }

BUCKET=${1:?$USAGE}
REPO=${2:?$USAGE}
PKGDIR=${3:?$USAGE}
shift 3
[ $# -gt 0 ] || { echo "no targets given" >&2; echo "$USAGE" >&2; exit 1; }

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
    local family=$1 release=$2 pkgdir name
    while IFS= read -r pkgdir; do
        name=$(basename "$pkgdir")
        if [ -n "$PACKAGES" ]; then
            case " $PACKAGES " in *" $name "*) ;; *) continue ;; esac
        fi
        if [ -d "$pkgdir/$family/$release" ]; then
            printf '%s\t%s\n' "$name" "$pkgdir/$family/$release"
        fi
    done < <(find "$PKGDIR" -mindepth 1 -maxdepth 1 -type d | sort)
}

# A published filename keeps its bytes forever. Builds are not reproducible, so
# a rebuild at an already-published version-revision produces different bytes:
# the upload would skip the object while the indexes hash the local copy, and
# every client would fail the checksum. Refuse instead.
place() {
    local src=$1 dst=$2 name
    for name in "$src"/*; do
        [ -e "$name" ] || continue
        if [ -e "$dst/$(basename "$name")" ] \
           && ! cmp -s "$name" "$dst/$(basename "$name")"; then
            echo "$(basename "$name") is published already with different bytes." >&2
            echo "A published version-revision cannot be rebuilt. Bump REVISION." >&2
            exit 1
        fi
        cp -f "$name" "$dst/"
    done
}

# The pool is per suite
make_deb_suite() {
    local suite=$1 pool="$REPO/deb/pool/$1" dists="$REPO/deb/dists/$1" pkg dir arch d f added

    sync_down "$BUCKET/deb/pool/$suite" "$pool"
    sync_down "$BUCKET/deb/dists/$suite" "$dists"

    # The pool holds both architectures; apt-ftparchive --arch splits them at
    # index time (and includes Architecture: all in each).
    added=""
    while IFS=$'\t' read -r pkg dir; do
        mkdir -p "$pool/$COMPONENT/o/$pkg"
        place "$dir" "$pool/$COMPONENT/o/$pkg"
        added="$added $pkg"
        FOUND=1
    done < <(sources deb "$suite")
    # What this run contributes, as opposed to what the pool already held: an
    # empty list, or a package nobody meant to publish, is only visible here.
    echo "== $suite: adding${added:- nothing}"

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
    local el=$1 basearch pkg dir r added n rpm

    for basearch in $RPM_ARCHES; do
        r="$REPO/rpm/$el/$basearch"
        sync_down "$BUCKET/rpm/$el/$basearch" "$r"
        mkdir -p "$r"

        # createrepo_c indexes the whole directory, so unlike the deb pool this
        # one has to hold a single architecture.
        added=""
        while IFS=$'\t' read -r pkg dir; do
            n=0
            while IFS= read -r rpm; do
                if [ -e "$r/$(basename "$rpm")" ] && ! cmp -s "$rpm" "$r/$(basename "$rpm")"; then
                    echo "$(basename "$rpm") is published already with different bytes." >&2
                    echo "A published version-revision cannot be rebuilt. Bump REVISION." >&2
                    exit 1
                fi
                cp -f "$rpm" "$r/"
                n=$((n + 1))
                FOUND=1
            done < <(find "$dir" -maxdepth 1 -type f \
                \( -name "*.$basearch.rpm" -o -name '*.noarch.rpm' \))
            if [ "$n" -gt 0 ]; then added="$added $pkg"; fi
        done < <(sources rpm "$el")
        # Nothing for this arch is normal on a single-arch publish; a package
        # nobody meant to publish is not, and this is where it shows.
        echo "== $el/$basearch: adding${added:- nothing}"

        createrepo_c --quiet --update --general-compress-type=gz "$r"
        echo "== $el/$basearch: $(find "$r" -maxdepth 1 -name '*.rpm' | wc -l) packages"
    done
}

FOUND=0
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

# Indexing nothing at all means the packages never reached this stage; going on
# would sign and tag a publish that contains nothing.
if [ "$FOUND" -eq 0 ]; then
    echo "No packages found in $PKGDIR for: $*${PACKAGES:+ (limited to $PACKAGES)}." >&2
    echo "Nothing would be published; refusing." >&2
    exit 1
fi
