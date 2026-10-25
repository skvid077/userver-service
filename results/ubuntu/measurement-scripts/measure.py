#!/usr/bin/env python3
"""Time a real build, preserve traces, and reject incomplete captures."""
import argparse
import json
import re
import resource
import shutil
import subprocess
import time
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument('--build', type=Path, required=True)
parser.add_argument('--output', type=Path, required=True)
parser.add_argument('--analyzer', required=True)
parser.add_argument('--target', default='build_study')
parser.add_argument('--mode', choices=['profile', 'plain'], default='profile')
parser.add_argument('--expected-compiler-tasks', type=int, default=10)
args = parser.parse_args()
args.output.mkdir(parents=True, exist_ok=False)

def run(command, log):
    with log.open('w') as out:
        return subprocess.run(command, stdout=out, stderr=subprocess.STDOUT).returncode

subprocess.run(['cmake', '--build', str(args.build), '--target', 'clean'], check=True,
               stdout=subprocess.DEVNULL)
# Restrict removal to compiler output directories in this experiment's build tree.
for trace in args.build.rglob('*.json'):
    if 'CMakeFiles' in trace.parts and any(p.endswith('.dir') for p in trace.parts):
        trace.unlink()

if args.mode == 'profile':
    subprocess.run([args.analyzer, '--start', str(args.build)], check=True,
                   stdout=subprocess.DEVNULL)
command = ['cmake', '--build', str(args.build), '--target', args.target, '--parallel', '4']
ninja_path = args.build / '.ninja_log'
ninja_before = ninja_path.read_text().splitlines() if ninja_path.exists() else []
started = time.time()
usage_before = resource.getrusage(resource.RUSAGE_CHILDREN)
t0 = time.perf_counter()
returncode = run(command, args.output / 'build.log')
elapsed = time.perf_counter()-t0
usage_after = resource.getrusage(resource.RUSAGE_CHILDREN)
ninja_after = ninja_path.read_text().splitlines()
if ninja_after[:len(ninja_before)] != ninja_before:
    raise SystemExit('Ninja log was rewritten; cannot isolate current run reliably')
ninja_current = ninja_after[len(ninja_before):]
(args.output / 'ninja.log').write_text('\n'.join(ninja_current)+'\n')
ninja_records = []
for line in ninja_current:
    fields = line.split('\t')
    if len(fields) == 5 and not line.startswith('#'):
        ninja_records.append((int(fields[0]), int(fields[1]), fields[3]))
compiled = [r for r in ninja_records if r[2].endswith(('.o', '.pch'))]
if not compiled:
    raise SystemExit('No compiler tasks in the current Ninja log')
if len(compiled) != args.expected_compiler_tasks:
    raise SystemExit(f'Expected {args.expected_compiler_tasks} compiler tasks, observed {len(compiled)}')
compile_wall = (max(r[1] for r in compiled)-min(r[0] for r in compiled))/1000
linked = [r for r in ninja_records if r[2] == args.target]
link_seconds = (linked[-1][1]-linked[-1][0])/1000 if linked else None
analysis_code = None
if args.mode == 'profile':
    capture_code = run([args.analyzer, '--stop', str(args.build), str(args.output / 'capture.bin')],
                       args.output / 'capture.log')
    if capture_code:
        raise SystemExit('Analyzer capture failed')
    analysis_code = run([args.analyzer, '--analyze', str(args.output / 'capture.bin')],
                        args.output / 'analyzer.txt')

traces = []
for path in args.build.rglob('*.json'):
    if 'CMakeFiles' not in path.parts or not any(p.endswith('.dir') for p in path.parts):
        continue
    try:
        data = json.loads(path.read_text())
    except (ValueError, UnicodeDecodeError):
        continue
    if 'traceEvents' not in data:
        continue
    destination = args.output / 'traces' / path.relative_to(args.build)
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(path, destination)
    totals = {e['name']: e['dur']/1e6 for e in data['traceEvents']
              if e.get('name', '').startswith('Total ') and 'dur' in e}
    traces.append({'file': str(path.relative_to(args.build)), 'totals_seconds': totals})

result = {'started_unix': started, 'command': command, 'wall_seconds': elapsed,
          'mode': args.mode, 'compiler_tasks': len(compiled),
          'cpu_user_seconds': usage_after.ru_utime-usage_before.ru_utime,
          'cpu_system_seconds': usage_after.ru_stime-usage_before.ru_stime,
          'compilation_wall_seconds': compile_wall, 'link_seconds': link_seconds,
          'build_exit_code': returncode, 'analysis_exit_code': analysis_code,
          'trace_count': len(traces), 'traces': traces}
(args.output / 'metrics.json').write_text(json.dumps(result, indent=2)+'\n')
print(f'{args.output.name}: wall={elapsed:.3f}s compile={compile_wall:.3f}s link={link_seconds} exit={returncode} tasks={len(compiled)} traces={len(traces)}', flush=True)
if args.mode == 'profile' and (len(traces) != args.expected_compiler_tasks or analysis_code != 0):
    raise SystemExit('Missing or invalid compiler traces: see logs')
if args.mode == 'plain' and traces:
    raise SystemExit('Unexpected traces in uninstrumented control')
log_text = (args.output / 'build.log').read_text()
if 'Re-running CMake' in log_text:
    raise SystemExit('Unexpected CMake reconfiguration inside timed build')
if re.search(r'precompiled header.*(?:ignored|invalid)|invalid precompiled', log_text, re.IGNORECASE):
    raise SystemExit('PCH was rejected by compiler')
if returncode:
    print('Build failed; preserving compiler metrics and full diagnostic log.', flush=True)
    raise SystemExit('Full build failed; refusing an incomplete experiment')
