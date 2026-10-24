#!/usr/bin/env python3
"""Export every scheduled build, including explicitly marked warmups, to CSV."""
import argparse
import csv
import json
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('results', type=Path)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    output = args.output or args.results/'all-results.csv'
    schedule = json.loads((args.results/'schedule.json').read_text())['runs']
    rows = []
    for sequence, item in enumerate(schedule, 1):
        metrics = json.loads((args.results/item['label']/'metrics.json').read_text())
        if metrics['build_exit_code'] != 0:
            raise SystemExit('Unsuccessful build: '+item['label'])
        row = dict(sequence=sequence, mode=item['mode'], variant=item['variant'],
                   pair=item.get('pair', ''), warmup=int(item['warmup']), label=item['label'])
        for key in ['started_unix', 'wall_seconds', 'compilation_wall_seconds', 'link_seconds',
                    'cpu_user_seconds', 'cpu_system_seconds', 'compiler_tasks', 'trace_count',
                    'build_exit_code', 'analysis_exit_code']:
            row[key] = metrics[key]
        row['cpu_total_seconds'] = metrics['cpu_user_seconds']+metrics['cpu_system_seconds']
        for key, event in [('frontend_seconds', 'Total Frontend'), ('backend_seconds', 'Total Backend'),
                           ('execute_compiler_seconds', 'Total ExecuteCompiler')]:
            row[key] = sum(t['totals_seconds'].get(event, 0) for t in metrics['traces']) if item['mode'] == 'profile' else ''
        rows.append(row)
    with output.open('w', encoding='utf-8', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    print(f'Exported {len(rows)} builds to {output}; warmup=1 marks warmup runs.')


if __name__ == '__main__':
    main()
