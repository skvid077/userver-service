#!/usr/bin/env bash
set -euo pipefail
phase="${1:-all}"
repeats="${2:-10}"
plain_repeats="${3:-6}"
workspace="${STUDY_WORKSPACE:-/workspace}"
results="${STUDY_RESULTS:-/results}"
export CCACHE_DISABLE=1 CMAKE_BUILD_PARALLEL_LEVEL=4
mkdir -p "$workspace" "$results"
cd "$workspace"
[[ ! -e build_study && ! -e analyzer-src ]] || { echo 'Use a fresh workspace' >&2; exit 2; }
exec > >(tee "$results/experiment.log") 2>&1
python3 - "$results" <<'PY'
import hashlib, json, shutil, sys
from pathlib import Path
study, output = Path('/study'), Path(sys.argv[1])
snapshot = output/'measurement-scripts'
snapshot.mkdir()
files = [*sorted((study/'scripts').glob('*.py')), *sorted((study/'scripts').glob('*.sh')),
         study/'run.ps1', study/'run.sh', study/'optimization.patch']
for path in files:
    shutil.copyfile(path, snapshot/path.name)
hashes = {p.relative_to(study).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in files}
(output/'measurement-scripts-sha256.json').write_text(json.dumps(hashes, indent=2)+'\n')
PY
bash /study/scripts/prepare.sh > "$results/prepare.log" 2>&1 || { cat "$results/prepare.log"; exit 1; }
{
    date --iso-8601=seconds
    uname -a
    cat /etc/os-release
    clang++-18 --version
    cmake --version
    ninja --version
    python3 --version
    ld --version
    ld.lld-18 --version
    dpkg-query -W clang-18 lld-18
    dpkg-query -W '*userver*' || true
    printf '\nCgroup limits: cpu.max cpuset memory.max memory.swap.max\n'
    cat /sys/fs/cgroup/cpu.max /sys/fs/cgroup/cpuset.cpus.effective /sys/fs/cgroup/memory.max /sys/fs/cgroup/memory.swap.max
} > "$results/environment.txt"
[[ "$(cat /sys/fs/cgroup/cpu.max)" == '400000 100000' ]]
[[ "$(cat /sys/fs/cgroup/cpuset.cpus.effective)" == '0-3' ]]
[[ "$(cat /sys/fs/cgroup/memory.max)" == '8589934592' ]]
[[ "$(cat /sys/fs/cgroup/memory.swap.max)" == '0' ]]
printf '%s  %s\n' '6571520c81f1dbb42a42d15e85c7069e54d1b7d43a42fffc794d39f7c0a70f4a' \
    /study/scripts/ClangBuildAnalyzer-55447756.tar.gz | sha256sum --check
mkdir analyzer-src
tar -xzf /study/scripts/ClangBuildAnalyzer-55447756.tar.gz --strip-components=1 -C analyzer-src
cmake -S analyzer-src -B analyzer-build -G Ninja -DCMAKE_BUILD_TYPE=Release \
    -DCMAKE_C_COMPILER=clang-18 -DCMAKE_CXX_COMPILER=clang++-18 \
    -DCMAKE_POLICY_VERSION_MINIMUM=3.10 > "$results/analyzer-configure.log"
cmake --build analyzer-build --parallel 4 > "$results/analyzer-build.log"
analyzer-build/ClangBuildAnalyzer --version >> "$results/environment.txt"
python3 /study/scripts/run_experiment.py --workspace "$workspace" --results "$results" \
    --phase "$phase" --repeats "$repeats" --plain-repeats "$plain_repeats"
