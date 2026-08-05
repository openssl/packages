# openssl-packages — task runner over the container build scripts.
# The real build logic lives in build/*.sh and packaging/*/build-in-container.sh;
# this Makefile just adds discoverable targets, incremental (stamp-guarded)
# rebuilds, and `-j` parallelism.
#
#   make deb-bookworm            build one deb release
#   make rpm-el10                build one rpm release
#   make deb / make rpm          a whole family
#   make -j4 all                 the whole matrix, in parallel
#   make test                    install + check in clean containers
#   make lint ; make clean ; make help

STREAM  := $(or $(STREAM),4.0)
VERSION := $(or $(VERSION),4.0.1)

ARCH ?= amd64
export ARCH

# The '-N' after the upstream version; bumped to republish the same upstream
# version with different packaging.
REVISION := $(or $(REVISION),1)
export REVISION

# Timestamp for the changelogs, from the source rather than the clock: dpkg and
# rpm both derive SOURCE_DATE_EPOCH from the changelog date.
SOURCE_DATE_EPOCH ?= $(shell git log -1 --format=%ct 2>/dev/null || date +%s)
export SOURCE_DATE_EPOCH

# OpenSSL's build parallelism inside each container. Pin it where memory per
# core is tight: LTO link jobs multiply against it.
JOBS ?= $(shell nproc)
export JOBS

# RUN_TESTS=1 runs OpenSSL's own suite at build time (slow; per-toolchain gate).
# Exported so `make RUN_TESTS=1 deb-bookworm` reaches the build scripts.
RUN_TESTS ?= 0
export RUN_TESTS

# Tests run via uv (pytest + env from pyproject.toml).
PYTEST      ?= uv run pytest
PYTEST_ARGS ?= -v

# Validated modules are pinned per source version; CERT_<version> names its
# CMVP certificate. The stream's companion module is built from $(VERSION).
FIPS_VALIDATED ?= 3.1.2
CERT_3.1.2      = 4985

# The version the test-suite exercises by default.
FIPS_VERSION ?= 3.1.2
export FIPS_VERSION

# One module build serves a whole family, so build it on the OLDEST glibc in
# that family: the module inherits a symbol-version floor from its builder.
FIPS_DEB_SUITE ?= bullseye
FIPS_EL_VER    ?= 9

DEB_SUITES = bullseye bookworm trixie focal jammy noble resolute
EL_VERS    = 9 10

IMAGE_bullseye = debian:11
IMAGE_bookworm = debian:12
IMAGE_trixie   = debian:13
IMAGE_focal    = ubuntu:20.04
IMAGE_jammy    = ubuntu:22.04
IMAGE_noble    = ubuntu:24.04
IMAGE_resolute = ubuntu:26.04

STAMPDIR = .stamps
COMMON_SRCS = packaging/common/fips-enable.in packaging/common/setup-shlib-variant.sh \
              packaging/common/variant-target.conf.in packaging/common/enable.in \
              packaging/common/trust-anchors.in packaging/common/openssl-fips.cnf.in
DEB_SRCS = $(shell find packaging/deb/debian -type f) packaging/deb/build-in-container.sh build/build-deb.sh $(COMMON_SRCS)
RPM_SRCS = packaging/rpm/openssl-upstream.spec packaging/rpm/build-in-container.sh build/build-rpm.sh $(COMMON_SRCS)

DEB_TARGETS = $(addprefix deb-,$(DEB_SUITES))
RPM_TARGETS = $(addprefix rpm-el,$(EL_VERS))

.DEFAULT_GOAL := help
.PHONY: all deb rpm fips fips-deb fips-rpm test lint clean help ci-targets ci-config $(DEB_TARGETS) $(RPM_TARGETS)

all: deb rpm
deb: $(DEB_TARGETS)
rpm: $(RPM_TARGETS)

fips: fips-deb fips-rpm

fips-deb:
	$(foreach v,$(FIPS_VALIDATED),FIPS_CERT="$(CERT_$(v))" build/build-fips-deb.sh $(v) \
	    $(FIPS_DEB_SUITE) $(IMAGE_$(FIPS_DEB_SUITE)) &&) true
	FIPS_STREAM=$(STREAM) build/build-fips-deb.sh $(VERSION) \
	    $(FIPS_DEB_SUITE) $(IMAGE_$(FIPS_DEB_SUITE))
fips-rpm:
	$(foreach v,$(FIPS_VALIDATED),FIPS_CERT="$(CERT_$(v))" build/build-fips-rpm.sh $(v) \
	    $(FIPS_EL_VER) &&) true
	FIPS_STREAM=$(STREAM) build/build-fips-rpm.sh $(VERSION) $(FIPS_EL_VER)

test:
	@mkdir -p output
	STREAM=$(STREAM) FIPS_VERSION=$(FIPS_VERSION) REVISION=$(REVISION) \
	    $(PYTEST) --junitxml=output/tests.xml $(PYTEST_ARGS)

# Short names depend on their (arch-specific) stamp; the stamp rule does the work.
$(DEB_TARGETS): deb-%: $(STAMPDIR)/deb-%-$(ARCH)
$(RPM_TARGETS): rpm-el%: $(STAMPDIR)/rpm-el%-$(ARCH)

$(STAMPDIR)/deb-%-$(ARCH): $(DEB_SRCS) | $(STAMPDIR)
	build/build-deb.sh $(STREAM) $(VERSION) $* $(IMAGE_$*)
	@touch $@

$(STAMPDIR)/rpm-el%-$(ARCH): $(RPM_SRCS) | $(STAMPDIR)
	build/build-rpm.sh $(STREAM) $(VERSION) $* almalinux:$*
	@touch $@

$(STAMPDIR):
	@mkdir -p $@

# Shell templates (*.in) are scripts too; @PLACEHOLDER@ tokens are inert to
# shellcheck. Run containerized so no host install is needed.
SHELL_SRCS = $(shell git ls-files '*.sh' 2>/dev/null || find build packaging -name '*.sh') \
             packaging/common/enable.in packaging/common/trust-anchors.in \
             packaging/common/fips-enable.in

lint:
	podman run --rm -v "$(CURDIR)":/mnt:ro -w /mnt docker.io/koalaman/shellcheck:stable \
	    --shell=bash --external-sources $(SHELL_SRCS)

# One target name per line, for CI to build its job matrix from.
ci-targets:
	@printf '%s\n' $(DEB_TARGETS) $(RPM_TARGETS)

ci-config:
	@printf '%s\n' \
	    'STREAM=$(STREAM)' \
	    'VERSION=$(VERSION)' \
	    'REVISION=$(REVISION)' \
	    'FIPS_VALIDATED=$(FIPS_VALIDATED)' \
	    'FIPS_DEB_SUITE=$(FIPS_DEB_SUITE)' \
	    'FIPS_EL_VER=$(FIPS_EL_VER)' \
	    'CI_TARGETS=$(DEB_TARGETS) $(RPM_TARGETS)'

clean:
	rm -rf output $(STAMPDIR)

help:
	@echo "openssl-packages  (STREAM=$(STREAM) VERSION=$(VERSION) ARCH=$(ARCH))"
	@echo
	@echo "Targets:"
	@echo "  all                 build every stream package (deb + rpm; use -jN)"
	@echo "  deb / rpm           build one family"
	@echo "  deb-<suite>         one deb release, e.g. deb-bookworm"
	@echo "  rpm-el<n>           one rpm release, e.g. rpm-el9"
	@echo "  fips                build every FIPS module package (deb + rpm)"
	@echo "  fips-deb fips-rpm   one family of FIPS module packages"
	@echo "  test                run the package test suite (pytest, in containers)"
	@echo "  lint                shellcheck the shell scripts and templates"
	@echo "  clean               remove built packages and stamps"
	@echo
	@echo "Releases:     $(DEB_TARGETS) $(RPM_TARGETS)"
	@echo "FIPS modules: validated $(FIPS_VALIDATED); companion $(STREAM) ($(VERSION))"
	@echo "Override:     make VERSION=4.0.2 deb-bookworm"
	@echo "Subset test:  make test PYTEST_ARGS='-k \"bookworm or rpm-9\"'"
	@echo "Build tests:  make RUN_TESTS=1 deb-bookworm   (runs OpenSSL's own suite)"
	@echo "arm64:        make ARCH=arm64 deb-bookworm    (needs qemu binfmt; see README)"
