import json
import os
import resource
import sys
import time
from pathlib import Path

records = []
for cpu in sorted(os.sched_getaffinity(0)):
    os.sched_setaffinity(0, {cpu})
    start = time.perf_counter()
    wall = time.time()
    process = time.process_time()
    time.sleep(1)
    records.append({'cpu': cpu, 'sleep_monotonic': time.perf_counter()-start,
                    'sleep_wall': time.time()-wall, 'sleep_cpu': time.process_time()-process})
    start = time.perf_counter()
    process = time.process_time()
    value = 1
    while time.perf_counter()-start < 1:
        for _ in range(10000):
            value = (value*3+1) % 1000000007
    records[-1].update(busy_monotonic=time.perf_counter()-start, busy_cpu=time.process_time()-process)
os.sched_setaffinity(0, set(range(4)))
start = time.perf_counter()
wall = time.time()
time.sleep(10)
result = {'clocksource': Path('/sys/devices/system/clocksource/clocksource0/current_clocksource').read_text().strip(),
          'kernel_command_line': Path('/proc/cmdline').read_text().strip(),
          'sleep10_monotonic': time.perf_counter()-start, 'sleep10_wall': time.time()-wall,
          'per_cpu': records}
print(json.dumps(result,indent=2),flush=True)
assert result['clocksource'] == (sys.argv[1] if len(sys.argv)>1 else 'hpet')
assert 9.9 < result['sleep10_monotonic'] < 10.5
assert 9.9 < result['sleep10_wall'] < 10.5
for record in records:
    assert 0.95 < record['sleep_monotonic'] < 1.5
    assert 0.8 < record['busy_cpu']/record['busy_monotonic'] < 1.1
