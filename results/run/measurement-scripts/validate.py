#!/usr/bin/env python3
"""Validate completed builds independently of timed measurements."""
import argparse
import json
import re
import subprocess
from pathlib import Path

p = argparse.ArgumentParser()
p.add_argument('--workspace', type=Path, required=True)
p.add_argument('--results', type=Path, required=True)
a = p.parse_args()
modes = list(dict.fromkeys(r['mode'] for r in json.loads((a.results/'schedule.json').read_text())['runs']))

def call(command, filename):
    with (a.results/filename).open('w') as out:
        subprocess.run([str(x) for x in command], stdout=out, stderr=subprocess.STDOUT, check=True)
    return (a.results/filename).read_text()

def comment(binary, filename):
    # GNU readelf 2.38 cannot decode all Clang 18 DWARF forms. Do not follow
    # debug links when inspecting unrelated ELF sections.
    return call(['readelf', '--debug-dump=no-follow-links', '--string-dump=.comment', binary], filename)

def is_lld(text):
    return bool(re.search(r'Linker: (?:Ubuntu )?LLD 18\.1\.8(?:\s|$)', text))

for variant in ['baseline', 'optimized']:
    build = a.workspace/f'profile-{variant}'
    call(['cmake', '--build', build, '--target', 'build_study_unittest', '--parallel', '4'], f'unit-build-{variant}.log')
    call([build/'build_study_unittest', '--gtest_color=no'], f'unit-tests-{variant}.log')
    if is_lld(comment(build/'build_study_unittest', f'unit-linker-{variant}.txt')) != (variant == 'optimized'):
        raise SystemExit('Unexpected unit test linker')
details = {}
for mode in modes:
    for variant in ['baseline', 'optimized']:
        binary = a.workspace/f'{mode}-{variant}'/'build_study'
        source = a.workspace/('build_study' if variant == 'baseline' else 'build_study-optimized')
        call([binary, '--config', source/'configs/static_config.yaml',
              '--config-vars', source/'configs/config_vars.yaml', '--print-config-schema'], f'schema-{mode}-{variant}.yaml')
        if is_lld(comment(binary, f'linker-{mode}-{variant}.txt')) != (variant == 'optimized'):
            raise SystemExit('Unexpected service linker in ELF')
        sections = call(['readelf', '--debug-dump=no-follow-links', '--wide', '--sections', binary], f'sections-{mode}-{variant}.txt')
        if not all(name in sections for name in ['.debug_info', '.debug_line', '.symtab']):
            raise SystemExit('Missing debug information or symbol table')
        dynamic = call(['readelf', '--debug-dump=no-follow-links', '--dynamic', binary], f'dynamic-{mode}-{variant}.txt')
        details[f'{mode}-{variant}'] = {'size_bytes': binary.stat().st_size,
            'debug_info_and_line_and_symbols_present': True,
            'needed_libraries': sorted(re.findall(r'\(NEEDED\).*?\[(.*?)\]', dynamic))}
reference = (a.results/'schema-profile-baseline.yaml').read_bytes()
if not all(path.read_bytes() == reference for path in a.results.glob('schema-*.yaml')):
    raise SystemExit('Configuration schemas differ')
libraries = [item['needed_libraries'] for item in details.values()]
if not all(item == libraries[0] for item in libraries):
    raise SystemExit('Dynamic dependencies differ')
(a.results/'binary-details.json').write_text(json.dumps(details, indent=2)+'\n')
(a.results/'validation.txt').write_text('Both GNU-ld and LLD unit tests passed; configuration schemas and dynamic dependencies of all service builds are identical. ELF .comment confirms Ubuntu LLD 18.1.8 only in optimized binaries; debug sections and symbol tables preserved.\n')
print((a.results/'validation.txt').read_text(), flush=True)
