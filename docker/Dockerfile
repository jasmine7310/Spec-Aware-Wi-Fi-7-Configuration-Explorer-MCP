# Simulation environment: hostap + a UML (User-Mode Linux) kernel with mac80211_hwsim.
#
# hostap's tests/hwsim/vm/vm-run.sh boots the UML kernel with the container's own
# filesystem as its root (hostfs), so every tool the tests need is installed here.
# Versions are pinned in baseline/README.md; keep the ARGs below in sync with it.

ARG UBUNTU_VERSION=24.04

# ---------------------------------------------------------------------------
# Base: build tools + everything the hwsim tests use at runtime
# (package list follows hostap's tests/hwsim/vm/example-vm-setup.txt)
# ---------------------------------------------------------------------------
FROM ubuntu:${UBUNTU_VERSION} AS base

ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential git curl ca-certificates bc flex bison python3 \
        libpcap-dev libssl-dev libxml2-dev libcurl4-openssl-dev \
        libnl-3-dev libnl-genl-3-dev libnl-route-3-dev libsqlite3-dev \
        binutils-dev libiberty-dev zlib1g-dev libpcsclite-dev libconfig-dev \
        libdbus-1-dev \
        net-tools bridge-utils ebtables iw iproute2 procps psmisc kmod \
        tshark dbus systemd-sysv \
        python3-openssl python3-pyrad python3-cryptography python3-pycryptodome \
    && rm -rf /var/lib/apt/lists/*

# ---------------------------------------------------------------------------
# Kernel: build the UML kernel once; only the resulting binary is kept.
# This is the slow step (tens of minutes on a laptop) and is cached by Docker.
# ---------------------------------------------------------------------------
FROM base AS kernel

ARG HOSTAP_COMMIT=43ee60e13c257d33d25bfb6892b9ee38fb6e88a4
ARG KERNEL_COMMIT=21b4248bfa0f410fa22202fc2c82f4808d672cda

WORKDIR /build
RUN curl -fsSL -o linux.tar.gz \
        "https://git.kernel.org/pub/scm/linux/kernel/git/wireless/wireless-next.git/snapshot/wireless-next-${KERNEL_COMMIT}.tar.gz" \
    && tar -xzf linux.tar.gz && rm linux.tar.gz \
    && mv wireless-next-${KERNEL_COMMIT} linux

WORKDIR /build/linux
# Use hostap's UML kernel config from the same pinned hostap commit.
RUN curl -fsSL -o .config \
        "https://w1.fi/cgit/hostap/plain/tests/hwsim/vm/kernel-config.uml?id=${HOSTAP_COMMIT}" \
    && make ARCH=um olddefconfig \
    && make ARCH=um -j"$(nproc)" \
    && mkdir -p /opt/uml && cp linux /opt/uml/linux

# ---------------------------------------------------------------------------
# Final image: hostap built with its test tools, plus the UML kernel binary
# ---------------------------------------------------------------------------
FROM base

ARG HOSTAP_COMMIT=43ee60e13c257d33d25bfb6892b9ee38fb6e88a4
ARG KERNEL_COMMIT=21b4248bfa0f410fa22202fc2c82f4808d672cda

# Shallow clone at the pinned commit; vm-run.sh records `git rev-parse HEAD`.
WORKDIR /opt/hostap
RUN git init -q \
    && git remote add origin https://w1.fi/hostap.git \
    && git fetch -q --depth 1 origin "${HOSTAP_COMMIT}" \
    && git checkout -q FETCH_HEAD \
    && tests/hwsim/build.sh

COPY --from=kernel /opt/uml/linux /opt/uml/linux

WORKDIR /opt/hostap/tests/hwsim/vm
RUN printf 'KERNEL=/opt/uml/linux\nMEMORY=512\n' > vm-config

LABEL org.opencontainers.image.title="wifi7-config-explorer simulation environment" \
      hostap.commit="${HOSTAP_COMMIT}" \
      kernel.commit="${KERNEL_COMMIT}"

# Logs are written inside the container and copied out by docker/run-test.sh;
# don't point this at a host bind mount (the tests' SQLite database hangs there).
ENV HWSIM_TEST_LOG_DIR=/tmp/hwsim-test-logs

# Arguments are hwsim test names, e.g. `eht_mld_sae_two_links`.
ENTRYPOINT ["./vm-run.sh"]
