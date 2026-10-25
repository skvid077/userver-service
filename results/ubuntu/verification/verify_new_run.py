"""Verify fresh Linux results using the published checker's data checks.

Only the input-path selection and host metadata reader are adapted.
The original verifier remains unchanged in the Git clone.
"""
import argparse
import json
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument('repository', type=Path)
parser.add_argument('results', type=Path)
parser.add_argument('docker_inspect', type=Path)
args = parser.parse_args()
project = args.repository.resolve()
root = args.results.resolve()
inspect = json.loads(args.docker_inspect.read_text())
assert len(inspect) == 1
assert inspect[0]['HostConfig']['NanoCpus'] == 4_000_000_000
assert inspect[0]['HostConfig']['CpusetCpus'] == '0-3'
assert inspect[0]['HostConfig']['Memory'] == inspect[0]['HostConfig']['MemorySwap'] == 8*1024**3
source = (project/'scripts/verify_results.py').read_text()
replacements = {
    "project = Path(__file__).resolve().parents[1]": "project = Path(REPOSITORY)",
    "root = project/'results/run'": "root = Path(RESULTS)",
    "host = load(root/'host.json')": "host = {'image': CONTAINER_IMAGE}",
    "(project/'all-results.csv')": "(root/'all-results.csv')",
}
for before, after in replacements.items():
    assert source.count(before) == 1, before
    source = source.replace(before, after, 1)
namespace = {'__name__':'__main__', '__file__':str(project/'scripts/verify_results.py'),
             'REPOSITORY':str(project), 'RESULTS':str(root),
             'CONTAINER_IMAGE':inspect[0]['Config']['Image']}
print('Fresh-run check: published verifier; paths and Linux Docker host metadata adapted.')
exec(compile(source, str(project/'scripts/verify_results.py'), 'exec'), namespace)
