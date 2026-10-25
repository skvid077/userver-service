#!/usr/bin/env bash
set -euo pipefail
study_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
phase="${1:-all}"
repeats="${2:-10}"
plain_repeats="${3:-6}"
image='ghcr.io/userver-framework/ubuntu-22.04-userver@sha256:fca9c8ac7e97b4e2b042d822facbb152aec10a9d4e09c0862e44c50640f3f303'
case "$(docker info --format '{{.Architecture}}')" in
    amd64|x86_64) ;;
    *) echo 'Use an x86-64 Docker host. ARM emulation distorts timing.' >&2; exit 2 ;;
esac
study_run_key="$(date +%Y%m%d-%H%M%S)-$$"
study_container="userver-study-$study_run_key"
results="$study_dir/results/$study_run_key"
mkdir -p "$results"
{
    date --iso-8601=seconds
    uname -a
    lscpu
    free -b
    docker info --format 'Engine={{.ServerVersion}} OS={{.OperatingSystem}} Kernel={{.KernelVersion}} Arch={{.Architecture}} CPUs={{.NCPU}} Memory={{.MemTotal}}'
} > "$results/host.txt"
docker run --detach --name "$study_container" --cpus=4 --cpuset-cpus=0-3 --memory=8g --memory-swap=8g \
    --mount "type=bind,source=$study_dir,target=/study,readonly" \
    --mount "type=bind,source=$results,target=/results" \
    --mount 'type=volume,target=/workspace' \
    --workdir /workspace "$image" bash /study/scripts/experiment.sh "$phase" "$repeats" "$plain_repeats"
printf '%s\n' "$study_container" > "$results/container.txt"
docker logs --follow "$study_container"
study_exit_code="$(docker wait "$study_container")"
printf '%s\n' "$study_exit_code" > "$results/exit-code.txt"
[[ "$study_exit_code" == 0 ]] || { printf 'Experiment failed; logs: %s\n' "$results" >&2; exit 1; }
printf 'Results: %s\n' "$results"
printf 'Container and Linux volume retained: %s\n' "$study_container"
