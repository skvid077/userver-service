#!/usr/bin/env python3
"""Check saved measurements without importing the measurement/export scripts."""
import csv
import hashlib
import json
import math
import re
import shlex
import tarfile
from pathlib import Path


def load(path):
    return json.loads(path.read_text(encoding='utf-8-sig'))


def require(condition, message):
    if not condition:
        raise ValueError(message)


def equal(actual, expected, label, tolerance=1e-9):
    require(math.isclose(actual, expected, rel_tol=0, abs_tol=tolerance),
            f'{label}: calculated {actual}, recorded {expected}')


def archive(path):
    with tarfile.open(path) as stream:
        return {Path(item.name).as_posix(): stream.extractfile(item).read()
                for item in stream if item.isfile()}


def main():
    project = Path(__file__).resolve().parents[1]
    root = project/'results/run'
    host = load(root/'host.json')
    image = 'ghcr.io/userver-framework/ubuntu-22.04-userver@sha256:fca9c8ac7e97b4e2b042d822facbb152aec10a9d4e09c0862e44c50640f3f303'
    require(host['image'] == image, 'Wrong Docker image')
    environment = (root/'environment.txt').read_text()
    require('400000 100000\n0-3\n8589934592\n0\n' in environment, 'Wrong cgroup resource limits')
    original = archive(root/'service-original.tar.gz')
    optimized = archive(root/'service-optimized.tar.gz')
    manifest = load(project/'scripts/template-sha256.json')
    require({p: hashlib.sha256(data).hexdigest() for p, data in original.items()} == manifest,
            'Original sources differ from freshly generated template')
    require(original.keys() == optimized.keys(), 'Source file lists differ')
    changed = [p for p in original if original[p] != optimized[p]]
    require(changed == ['CMakeLists.txt'], f'Unexpected changed files: {changed}')
    flag = b'target_link_options(${PROJECT_NAME}_objs INTERFACE -fuse-ld=lld-18)\n'
    require(optimized['CMakeLists.txt'].count(flag) == 1 and
            optimized['CMakeLists.txt'].replace(flag, b'', 1) == original['CMakeLists.txt'],
            'Service change is not exactly one linker line')
    for name, data in optimized.items():
        require((project/'service'/name).read_bytes() == data, f'Published service differs: {name}')
    print('PASS: all template files match; exactly one CMake line added, no C++ changes.')

    schedule = load(root/'schedule.json')['runs']
    with (project/'all-results.csv').open(encoding='utf-8', newline='') as stream:
        exported = list(csv.DictReader(stream))
    require(len(schedule) == len(exported) == 40, 'Expected all 40 runs including warmups')
    require([r['label'] for r in exported] == [r['label'] for r in schedule], 'CSV run order differs')
    rows, traces_count = [], 0
    for index, (item, csv_row) in enumerate(zip(schedule, exported), 1):
        folder = root/item['label']
        metrics = load(folder/'metrics.json')
        require(metrics['build_exit_code'] == 0, f'{folder}: build failed')
        require(csv_row['sequence'] == str(index) and csv_row['warmup'] == str(int(item['warmup'])),
                f'{folder}: incorrect CSV warmup/order')
        require(csv_row['pair'] == str(item.get('pair', '')) and
                csv_row['mode'] == item['mode'] and csv_row['variant'] == item['variant'],
                f'{folder}: incorrect CSV labels')
        for key in ['started_unix', 'wall_seconds', 'compilation_wall_seconds', 'link_seconds',
                    'cpu_user_seconds', 'cpu_system_seconds', 'compiler_tasks', 'trace_count', 'build_exit_code']:
            equal(float(csv_row[key]), metrics[key], f'{folder} CSV {key}')
        equal(float(csv_row['cpu_total_seconds']), metrics['cpu_user_seconds']+metrics['cpu_system_seconds'],
              f'{folder}: total CPU')
        records = [line.split('\t') for line in (folder/'ninja.log').read_text().splitlines()]
        records = [r for r in records if len(r) == 5 and not r[0].startswith('#')]
        objects = [r for r in records if r[3].endswith('.o')]
        links = [r for r in records if r[3] == 'build_study']
        require(len(objects) == metrics['compiler_tasks'] == 10 and len(links) == 1, f'{folder}: Ninja tasks')
        equal((max(int(r[1]) for r in objects)-min(int(r[0]) for r in objects))/1000,
              metrics['compilation_wall_seconds'], f'{folder}: compile interval')
        equal((int(links[0][1])-int(links[0][0]))/1000, metrics['link_seconds'], f'{folder}: link interval')
        require(metrics['wall_seconds'] >= metrics['link_seconds'], f'{folder}: impossible wall time')
        traces = list((folder/'traces').rglob('*.json'))
        require(len(traces) == metrics['trace_count'] == (10 if item['mode'] == 'profile' else 0),
                f'{folder}: trace count')
        traces_count += len(traces)
        totals = {p.relative_to(folder/'traces').as_posix():
                  {e['name']: e['dur']/1e6 for e in load(p)['traceEvents']
                   if e.get('name', '').startswith('Total ') and 'dur' in e} for p in traces}
        require(totals == {t['file']: t['totals_seconds'] for t in metrics['traces']}, f'{folder}: raw totals')
        row = dict(item, **{k: metrics[k] for k in ['wall_seconds', 'link_seconds', 'compilation_wall_seconds']})
        if item['mode'] == 'profile':
            require(metrics['analysis_exit_code'] == 0 and (folder/'analyzer.txt').stat().st_size > 0
                    and (folder/'capture.bin').stat().st_size > 0, f'{folder}: analyzer output')
            for key, event in [('frontend_seconds', 'Total Frontend'), ('backend_seconds', 'Total Backend'),
                               ('execute_compiler_seconds', 'Total ExecuteCompiler')]:
                row[key] = sum(t.get(event, 0) for t in totals.values())
                equal(row[key], float(csv_row[key]), f'{folder}: CSV {key}')
            generated = [t for p, t in totals.items() if 'build_study_proto.dir/' in p]
            row['generated_frontend_seconds'] = sum(t['Total Frontend'] for t in generated)
            row['generated_backend_seconds'] = sum(t['Total Backend'] for t in generated)
            text = (folder/'analyzer.txt').read_text()
            for key, pattern in {
                'service_header': r'^\s*(\d+) ms: .*?/hello_service\.usrv\.pb\.hpp \(included (\d+) times',
                'component_header': r'^\s*(\d+) ms: /usr/include/userver/components/component\.hpp \(included (\d+) times',
            }.items():
                match = re.search(pattern, text, re.MULTILINE)
                require(match is not None, f'{folder}: missing {key}')
                row[key], row[key+'_count'] = int(match[1])/1000, int(match[2])
        else:
            require(all(csv_row[k] == '' for k in ['frontend_seconds', 'backend_seconds', 'execute_compiler_seconds']),
                    f'{folder}: unexpected profiling values')
        rows.append(row)
    require(traces_count == 240, 'Expected 240 raw traces')
    measured = [r for r in rows if not r['warmup']]
    print('PASS: 40 CSV rows, 32 measured builds, 8 warmups, 240 raw traces and Ninja intervals.')

    for mode, count in [('profile', 10), ('plain', 6)]:
        selected = [r for r in measured if r['mode'] == mode]
        pairs = {r['pair'] for r in selected}
        require(pairs == set(range(1, count+1)), 'Missing measured pair')
        for pair in sorted(pairs):
            variants = {r['variant']: r for r in selected if r['pair'] == pair}
            require(set(variants) == {'baseline', 'optimized'}, 'Incomplete measured pair')
            b, o = variants['baseline'], variants['optimized']
            print(f"{mode} pair {pair}: GNU ld={b['wall_seconds']:.6f}s, LLD={o['wall_seconds']:.6f}s")
    baseline_rows = [r for r in measured if r['mode'] == 'profile' and r['variant'] == 'baseline']
    require(all(r['service_header_count'] == 3 and r['component_header_count'] == 4 for r in baseline_rows),
            'Header inclusion counts differ')
    for key in ['frontend_seconds', 'backend_seconds', 'generated_frontend_seconds',
                'generated_backend_seconds', 'service_header', 'component_header', 'link_seconds', 'wall_seconds']:
        values = [r[key] for r in baseline_rows]
        print(f'{key}: min={min(values):.6f}s, max={max(values):.6f}s')
    print('PASS: all 16 measured pairs and profiling ranges recalculated from raw data.')

    for mode in ['profile', 'plain']:
        compiles, links = [], []
        for variant in ['baseline', 'optimized']:
            prefix = root/f'{mode}-{variant}'
            cache = Path(str(prefix)+'-CMakeCache.txt').read_text()
            source = re.search(r'^CMAKE_HOME_DIRECTORY:INTERNAL=(.*)$', cache, re.MULTILINE)[1]
            commands = load(Path(str(prefix)+'-compile_commands.json'))
            build = commands[0]['directory']
            def normalize(token):
                return token.replace(source, '<SOURCE>').replace(build, '<BUILD>')
            compiles.append({Path(c['file']).name: [normalize(t) for t in shlex.split(c['command'])] for c in commands})
            link = shlex.split(Path(str(prefix)+'-target-commands.txt').read_text().splitlines()[-1])
            require([t for t in link if t.startswith('-fuse-ld=')] ==
                    (['-fuse-ld=lld-18'] if variant == 'optimized' else []), 'Unexpected linker selection')
            links.append([normalize(t) for t in link if not t.startswith('-fuse-ld=')])
        require(compiles[0] == compiles[1] and links[0] == links[1], 'Commands differ beyond linker selection')
    print('PASS: matching compiler commands; link commands differ only in linker selection.')

    details = load(root/'binary-details.json')
    schemas = [p.read_bytes() for p in root.glob('schema-*.yaml')]
    require(len(schemas) == 4 and all(s == schemas[0] for s in schemas), 'Configuration schemas differ')
    libraries = [item['needed_libraries'] for item in details.values()]
    require(len(libraries) == 4 and all(s == libraries[0] for s in libraries), 'Dynamic dependencies differ')
    sizes = [details['profile-'+v]['size_bytes'] for v in ['baseline', 'optimized']]
    print(f'ELF bytes: GNU ld={sizes[0]}, LLD={sizes[1]}; change={100*(sizes[1]/sizes[0]-1):.3f}%')
    for variant in ['baseline', 'optimized']:
        log = (root/f'unit-tests-{variant}.log').read_text()
        require('[  PASSED  ] 1 test.' in log, f'{variant}: missing passed unit test')
    print('PASS: both unit tests, identical schemas and dynamic dependencies.')
    print('LIMIT: stored logs and timer/stat readings do not authenticate themselves; rerun independently.')


if __name__ == '__main__':
    main()
