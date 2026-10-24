#!/usr/bin/env python3
"""Summarize scheduled paired runs; warmups never enter measurements."""
import csv
import json
import random
import statistics as st
import sys
from pathlib import Path

root = Path(sys.argv[1])
schedule = json.loads((root/'schedule.json').read_text())['runs']
rows = []
for item in schedule:
    data = json.loads((root/item['label']/'metrics.json').read_text())
    if data['build_exit_code'] != 0 or data['link_seconds'] is None:
        raise SystemExit('Unsuccessful full build: '+item['label'])
    if item['warmup']:
        continue
    row = {k: item[k] for k in ['mode', 'variant', 'pair', 'label']}
    for key in ['wall_seconds', 'compilation_wall_seconds', 'link_seconds',
                'cpu_user_seconds', 'cpu_system_seconds', 'compiler_tasks', 'trace_count']:
        row[key] = data[key]
    row['cpu_total_seconds'] = row['cpu_user_seconds']+row['cpu_system_seconds']
    for key, event in [('frontend_seconds', 'Total Frontend'), ('backend_seconds', 'Total Backend'),
                       ('execute_compiler_seconds', 'Total ExecuteCompiler')]:
        row[key] = sum(t['totals_seconds'].get(event, 0) for t in data['traces']) if item['mode'] == 'profile' else None
    rows.append(row)
with (root/'runs.csv').open('w', newline='') as out:
    writer = csv.DictWriter(out, fieldnames=list(rows[0]))
    writer.writeheader()
    writer.writerows(rows)

summary = {'method': 'balanced paired runs; warmups excluded; positive delta = optimized slower',
           'bootstrap': 'paired percentile bootstrap of median ratio, 20000 resamples, seed 20261023; exploratory, no host drift/systematic error coverage',
           'runs': rows, 'modes': {}}
for mode in dict.fromkeys(r['mode'] for r in rows):
    subset = [r for r in rows if r['mode'] == mode]
    group = {'variants': {}}
    keys = [k for k in rows[0] if k.endswith('_seconds') and subset[0][k] is not None]
    for variant in dict.fromkeys(r['variant'] for r in subset):
        values = [r for r in subset if r['variant'] == variant]
        group['variants'][variant] = {'runs': len(values),
            'median': {k: st.median(r[k] for r in values) for k in keys},
            'min': {k: min(r[k] for r in values) for k in keys},
            'max': {k: max(r[k] for r in values) for k in keys},
            'stdev': {k: st.stdev(r[k] for r in values) if len(values)>1 else 0 for k in keys}}
    if 'optimized' in group['variants']:
        b = {r['pair']: r for r in subset if r['variant'] == 'baseline'}
        o = {r['pair']: r for r in subset if r['variant'] == 'optimized'}
        assert b.keys() == o.keys()
        pairs = list(b)
        comparison = {}
        for key in keys:
            rng = random.Random(20261023)
            ratios = []
            for _ in range(20000):
                sample = rng.choices(pairs, k=len(pairs))
                ratios.append(100*(st.median(o[i][key] for i in sample)/st.median(b[i][key] for i in sample)-1))
            ratios.sort()
            comparison[key] = {
                'median_ratio_delta_percent': 100*(group['variants']['optimized']['median'][key]/group['variants']['baseline']['median'][key]-1),
                'paired_median_delta_seconds': st.median(o[i][key]-b[i][key] for i in pairs),
                'optimized_faster_pairs': sum(o[i][key] < b[i][key] for i in pairs),
                'pairs': len(pairs), 'bootstrap_95_percent_interval': [ratios[499], ratios[19499]]}
        group['comparison'] = comparison
    summary['modes'][mode] = group
(root/'summary.json').write_text(json.dumps(summary, indent=2)+'\n')
for mode, group in summary['modes'].items():
    print(mode, json.dumps(group, indent=2), flush=True)
