#!/usr/bin/env bash
set -euo pipefail
clang_version='1:18.1.8~++20240731024944+3b5b5c1ec4a3-1~exp1~20240731145000.144'
if ! command -v clang++-18 >/dev/null; then
    export DEBIAN_FRONTEND=noninteractive
    # Refresh only the repositories needed by Clang and its Ubuntu dependencies.
    # List-Cleanup=0 preserves indexes belonging to other installed software.
    {
        echo 'deb https://archive.ubuntu.com/ubuntu jammy main universe'
        echo 'deb https://archive.ubuntu.com/ubuntu jammy-updates main universe'
        grep -hE '^deb .*llvm-toolchain-jammy-18' /etc/apt/sources.list /etc/apt/sources.list.d/*.list
    } > /tmp/clang18-study.list
    test -s /tmp/clang18-study.list
    apt-get update -o Acquire::Retries=3 -o Acquire::https::Timeout=30 \
        -o Dir::Etc::sourcelist=/tmp/clang18-study.list -o Dir::Etc::sourceparts=- \
        -o APT::Get::List-Cleanup=0
    apt-get install -y --no-install-recommends -o Acquire::Retries=3 \
        -o Acquire::http::Timeout=30 -o Acquire::https::Timeout=30 \
        -o Dir::Etc::sourcelist=/tmp/clang18-study.list -o Dir::Etc::sourceparts=- \
        "clang-18=$clang_version"
fi
[[ "$(dpkg-query -W -f='${Version}' clang-18)" == "$clang_version" ]] || {
    echo 'Unexpected clang-18 package version' >&2; exit 2;
}
export CC=clang-18
export CXX=clang++-18
clang++-18 --version
if ! command -v ld.lld-18 >/dev/null; then
    export DEBIAN_FRONTEND=noninteractive
    apt-get install -y --no-install-recommends --no-upgrade -o Acquire::Retries=3 \
        -o Acquire::http::Timeout=30 -o Acquire::https::Timeout=30 "lld-18=$clang_version"
fi
[[ "$(dpkg-query -W -f='${Version}' lld-18)" == "$clang_version" ]] || {
    echo 'Unexpected lld-18 package version' >&2; exit 2;
}
ld.lld-18 --version
