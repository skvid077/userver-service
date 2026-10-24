#!/usr/bin/env python3
"""Balanced paired experiment, with an independent uninstrumented control."""
import argparse
import hashlib
import json
import os
import random
import shlex
import shutil
import subprocess
from pathlib import Path

p = argparse.ArgumentParser()
p.add_argument('--workspace', type=Path, required=True)
p.add_argument('--results', type=Path, required=True)
p.add_argument('--study', type=Path, default=Path('/study'))
p.add_argument('--phase', choices=['baseline', 'all'], default='all')
p.add_argument('--repeats', type=int, default=10)
p.add_argument('--plain-repeats', type=int, default=6)
p.add_argument('--warmups', type=int, default=2)
a = p.parse_args()
if not 1 <= a.repeats <= 20 or not 0 <= a.plain_repeats <= 20 or not 1 <= a.warmups <= 3:
    p.error('Invalid repetition count')
a.workspace.mkdir(parents=True, exist_ok=True)
a.results.mkdir(parents=True, exist_ok=True)
sources = {'baseline': a.workspace/'build_study', 'optimized': a.workspace/'build_study-optimized'}
if sources['baseline'].exists():
    raise SystemExit('A fresh source workspace is required')

def call(command, log=None, cwd=None):
    if log:
        with log.open('w') as out:
            subprocess.run([str(x) for x in command], check=True, cwd=cwd,
                           stdout=out, stderr=subprocess.STDOUT)
    else:
        subprocess.run([str(x) for x in command], check=True, cwd=cwd)

call(['userver-create-service', '--grpc', '--mongo', '--postgresql', sources['baseline']])
manifest = json.loads((a.study/'scripts/template-sha256.json').read_text())
generated_hashes = {p.relative_to(sources['baseline']).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                    for p in sources['baseline'].rglob('*') if p.is_file()}
if generated_hashes != manifest:
    raise SystemExit('Fresh generator output differs from the recorded untouched service')
for directory in ['src', 'proto']:
    call(['diff', '-ru', a.study/'service'/directory, sources['baseline']/directory])
flag_line = b'target_link_options(${PROJECT_NAME}_objs INTERFACE -fuse-ld=lld-18)\n'
published_cmake = (a.study/'service/CMakeLists.txt').read_bytes()
if published_cmake.count(flag_line) != 1 or published_cmake.replace(flag_line, b'', 1) != (sources['baseline']/'CMakeLists.txt').read_bytes():
    raise SystemExit('Published service must differ from the generator by exactly one linker line')
call(['tar', '-czf', a.results/'service-original.tar.gz', '-C', sources['baseline'], '.'])
if a.phase == 'all':
    shutil.copytree(sources['baseline'], sources['optimized'])
    with (a.study/'optimization.patch').open('rb') as patch:
        subprocess.run(['patch', '-p1'], cwd=sources['optimized'], stdin=patch, check=True)
    call(['cmp', a.study/'service/CMakeLists.txt', sources['optimized']/'CMakeLists.txt'])
    call(['tar', '-czf', a.results/'service-optimized.tar.gz', '-C', sources['optimized'], '.'])

variants = ['baseline', 'optimized'] if a.phase == 'all' else ['baseline']
modes = ['profile'] + (['plain'] if a.phase == 'all' and a.plain_repeats else [])
builds = {}
for mode in modes:
    for variant in variants:
        build = a.workspace/f'{mode}-{variant}'
        builds[mode, variant] = build
        call(['cmake', '-S', sources[variant], '-B', build, '-G', 'Ninja',
              '-DCMAKE_BUILD_TYPE=Release', '-DCMAKE_C_COMPILER=clang-18',
              '-DCMAKE_CXX_COMPILER=clang++-18',
              '-DCMAKE_CXX_FLAGS='+('-ftime-trace' if mode == 'profile' else ''),
              '-DCMAKE_EXPORT_COMPILE_COMMANDS=ON', '-DCMAKE_CXX_COMPILER_LAUNCHER=',
              '-DCMAKE_C_COMPILER_LAUNCHER=', '-DUSERVER_USE_CCACHE=OFF',
              '-DUSERVER_USE_LD=',
              '-DUSERVER_FEATURE_TESTSUITE=OFF', '-DUSERVER_DEBUG_INFO_COMPRESSION=z'],
             a.results/f'configure-{mode}-{variant}.log')
        for filename in ['compile_commands.json', 'CMakeCache.txt', 'build.ninja']:
            shutil.copy2(build/filename, a.results/f'{mode}-{variant}-{filename}')
        call(['ninja', '-t', 'commands', 'build_study'], a.results/f'{mode}-{variant}-target-commands.txt', cwd=build)
        for kind in ['grpc', 'sql']:
            call(['uv', 'pip', 'freeze', '--python', build/f'venv-userver-{kind}/bin/python'],
                 a.results/f'python-{kind}-{mode}-{variant}.txt')

def normalized_command(entry, mode, variant):
    return [token.replace(str(sources[variant]), '<SOURCE>').replace(str(builds[mode, variant]), '<BUILD>')
            for token in shlex.split(entry['command'])]

audit = {'optimization': 'LLVM LLD 18 instead of GNU ld; no PCH',
         'same_sources': True, 'ccache_disabled_by_cmake_and_environment': os.environ.get('CCACHE_DISABLE') == '1',
         'modes': {}, 'source_sha256': {}}
for path in sorted((sources['baseline']/'src').glob('*')):
    if path.is_file():
        original = path.read_bytes()
        if a.phase == 'all' and original != (sources['optimized']/'src'/path.name).read_bytes():
            raise SystemExit('Unexpected C++ source modification')
        audit['source_sha256'][path.name] = hashlib.sha256(original).hexdigest()
for mode in modes:
    commands = {}
    for variant in variants:
        entries = json.loads((builds[mode, variant]/'compile_commands.json').read_text())
        commands[variant] = {Path(e['file']).name: normalized_command(e, mode, variant)
                             for e in entries if not Path(e['file']).name.startswith('cmake_pch.')}
        for tokens in commands[variant].values():
            if ('-ftime-trace' in tokens) != (mode == 'profile') or any('ccache' in t for t in tokens):
                raise SystemExit('Unexpected trace/cache flags')
    if a.phase == 'all' and commands['baseline'] != commands['optimized']:
        (a.results/f'commands-difference-{mode}.json').write_text(json.dumps(commands, indent=2))
        raise SystemExit('Compiler commands differ beyond build/source paths')
    link_commands = {}
    for variant in variants:
        raw = (a.results/f'{mode}-{variant}-target-commands.txt').read_text().splitlines()[-1]
        tokens = shlex.split(raw)
        linker_flags = [t for t in tokens if t.startswith('-fuse-ld=')]
        expected = ['-fuse-ld=lld-18'] if variant == 'optimized' else []
        if linker_flags != expected:
            raise SystemExit('Unexpected linker selection: '+str(linker_flags))
        link_commands[variant] = [t.replace(str(sources[variant]), '<SOURCE>').replace(str(builds[mode, variant]), '<BUILD>')
                                  for t in tokens if not t.startswith('-fuse-ld=')]
    if a.phase == 'all' and link_commands['baseline'] != link_commands['optimized']:
        (a.results/f'link-commands-difference-{mode}.json').write_text(json.dumps(link_commands, indent=2))
        raise SystemExit('Link commands differ beyond linker selection and build/source paths')
    audit['modes'][mode] = {'matching_compiler_flags': True, 'link_commands_differ_only_in_linker': True,
                           'source_command_count': len(commands['baseline'])}
(a.results/'audit.json').write_text(json.dumps(audit, indent=2)+'\n')
print('Audit passed: identical sources and compiler flags; only linker selection differs; ccache off.', flush=True)

seed = 20261023
schedule = []
for mode in modes:
    for warm in range(a.warmups):
        order = variants if warm % 2 == 0 else list(reversed(variants))
        for variant in order:
            schedule.append({'mode': mode, 'variant': variant, 'label': f'{mode}-{variant}-warmup-{warm+1}', 'warmup': True})
    repeats = a.repeats if mode == 'profile' else a.plain_repeats
    orders = [variants[:] for _ in range((repeats+1)//2)] + [list(reversed(variants)) for _ in range(repeats//2)]
    random.Random(seed+(mode == 'plain')).shuffle(orders)
    for pair, order in enumerate(orders, 1):
        for variant in order:
            schedule.append({'mode': mode, 'variant': variant, 'pair': pair,
                             'label': f'{mode}-{variant}-{pair:02d}', 'warmup': False})
(a.results/'schedule.json').write_text(json.dumps({'seed': seed, 'runs': schedule}, indent=2)+'\n')
for index, run in enumerate(schedule, 1):
    print(f'[{index}/{len(schedule)}] {run["label"]}', flush=True)
    call(['python3', a.study/'scripts/measure.py', '--build', builds[run['mode'], run['variant']],
          '--output', a.results/run['label'], '--analyzer', a.workspace/'analyzer-build/ClangBuildAnalyzer',
          '--mode', run['mode'], '--expected-compiler-tasks', 10])
call(['python3', a.study/'scripts/summarize_recheck.py', a.results])
call(['python3', a.study/'scripts/export_all_results.py', a.results])
if a.phase == 'all':
    call(['python3', a.study/'scripts/validate.py', '--workspace', a.workspace, '--results', a.results])
print('Experiment complete.', flush=True)
