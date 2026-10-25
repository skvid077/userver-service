import json
import queue
import subprocess
import sys
import threading
import time
from pathlib import Path
root=Path(__file__).resolve().parent
label=sys.argv[1]
duration=float(sys.argv[2]) if len(sys.argv)>2 else 90
port=sys.argv[3] if len(sys.argv)>3 else '22227'
mode=sys.argv[4] if len(sys.argv)>4 else ''
assert mode in ('','no-load')
args=[r'C:\Windows\System32\OpenSSH\ssh.exe','-F','NUL','-p',port,'-i',str(root/'vm_ed25519'),
      '-o','BatchMode=yes','-o','ConnectTimeout=10','-o','UserKnownHostsFile='+str(root/'known_hosts'),
      '-o','StrictHostKeyChecking=yes','study@127.0.0.1','python3 /home/study/clock_probe_guest.py'+(' --no-load' if mode=='no-load' else '')]
process=subprocess.Popen(args,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,bufsize=1)
lines=queue.Queue()
def reader():
    for line in process.stdout: lines.put(line)
threading.Thread(target=reader,daemon=True).start()
records=[]
start=time.perf_counter()
try:
    with (root/(label+'-clock-probe.jsonl')).open('w') as out:
        while time.perf_counter()-start < duration and not (root/(label+'.stop')).exists():
            before=time.perf_counter()
            process.stdin.write('sample\n'); process.stdin.flush()
            line=lines.get(timeout=20)
            after=time.perf_counter()
            record=json.loads(line)
            record.update(host_before=before,host_after=after,rtt=after-before)
            records.append(record)
            out.write(json.dumps(record)+'\n'); out.flush()
            time.sleep(1 if mode=='no-load' else 0.5)
finally:
    process.stdin.close()
    try: process.wait(timeout=20)
    except subprocess.TimeoutExpired: process.kill()
assert process.returncode==0,process.stderr.read()
good=[r for r in records if r['rtt']<0.1]
assert len(good)>10,'Too few low-latency samples'
first=good[0]
mid=lambda r:(r['host_before']+r['host_after'])/2
drifts=[(r['monotonic']-first['monotonic'])-(mid(r)-mid(first)) for r in good]
summary={'samples':len(records),'low_latency_samples':len(good),'host_elapsed':mid(good[-1])-mid(first),
         'guest_elapsed':good[-1]['monotonic']-first['monotonic'],
         'max_abs_clock_drift_seconds':max(map(abs,drifts)),
         'max_rtt':max(r['rtt'] for r in records),'reliable':max(map(abs,drifts))<0.1}
if 'tsc' in first:
    rate=(good[-1]['tsc']-first['tsc'])/(mid(good[-1])-mid(first))
    tsc_errors=[(r['tsc']-first['tsc'])/rate-(mid(r)-mid(first)) for r in good]
    summary.update(tsc_frequency_hz=rate,max_abs_tsc_drift_seconds=max(map(abs,tsc_errors)),
                   tested_cpus=sorted({r['cpu'] for r in good}),
                   tsc_reliable=max(map(abs,tsc_errors))<0.1)
(root/(label+'-clock-probe-summary.json')).write_text(json.dumps(summary,indent=2))
print(json.dumps(summary,indent=2),flush=True)
