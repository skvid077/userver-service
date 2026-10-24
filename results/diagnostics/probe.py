from pathlib import Path
import json
import subprocess

output = Path('/probe')
workspace = Path('/workspace')
source = workspace/'build_study'
build = workspace/'default-compression'
commands = []

def run(command, filename):
    commands.append([str(x) for x in command])
    with (output/filename).open('w') as stream:
        return subprocess.run([str(x) for x in command], stdout=stream, stderr=subprocess.STDOUT).returncode

assert run(['userver-create-service', '--grpc', '--mongo', '--postgresql', source], 'generation.log') == 0
assert run(['cmake', '-S', source, '-B', build, '-G', 'Ninja', '-DCMAKE_BUILD_TYPE=Release',
            '-DCMAKE_C_COMPILER=clang-18', '-DCMAKE_CXX_COMPILER=clang++-18',
            '-DCMAKE_EXPORT_COMPILE_COMMANDS=ON', '-DUSERVER_USE_LD=',
            '-DUSERVER_USE_CCACHE=OFF', '-DUSERVER_FEATURE_TESTSUITE=OFF'], 'configure.log') == 0
code = run(['cmake', '--build', build, '--target', 'build_study', '--parallel', '4'], 'build.log')
log = (output/'build.log').read_text()
compile_commands = json.loads((build/'compile_commands.json').read_text())
assert all('-gz=zstd' in c['command'] for c in compile_commands)
assert code != 0 and 'Linking CXX executable build_study' in log and any(
    text in log.lower() for text in ['unsupported', 'file format not recognized', 'file not recognized', 'compression']), log[-4000:]
(output/'compile_commands.json').write_text(json.dumps(compile_commands, indent=2)+'\n')
(output/'commands.json').write_text(json.dumps(commands, indent=2)+'\n')
(output/'result.json').write_text(json.dumps({'build_exit_code': code,
    'all_compile_commands_use_gz_zstd': True, 'expected_failure': True,
    'resolution_in_measured_builds': 'USERVER_DEBUG_INFO_COMPRESSION=z for both linkers'}, indent=2)+'\n')
print('Confirmed: default Zstandard debug sections are rejected by GNU ld; common zlib setting is required.')
print(log[-1600:])

analyzer_source = workspace/'analyzer-src'
analyzer_source.mkdir()
assert run(['tar', '-xzf', '/study/vendor/ClangBuildAnalyzer-55447756.tar.gz', '--strip-components=1',
            '-C', analyzer_source], 'analyzer-extract.log') == 0
assert run(['cmake', '-S', analyzer_source, '-B', workspace/'analyzer-build', '-G', 'Ninja',
            '-DCMAKE_BUILD_TYPE=Release', '-DCMAKE_C_COMPILER=clang-18', '-DCMAKE_CXX_COMPILER=clang++-18',
            '-DCMAKE_POLICY_VERSION_MINIMUM=3.10'], 'analyzer-configure.log') == 0
assert run(['cmake', '--build', workspace/'analyzer-build', '--parallel', '4'], 'analyzer-build.log') == 0
import re
def normalize(text):
    return [line.rstrip() for line in text.splitlines() if not line.startswith('Analyzing build trace from ')
            and not re.match(r'^\s*done in [\d.]+s\.$', line)]
captures = list(Path('/study/evidence/fresh-run').glob('profile-*/capture.bin'))
assert len(captures) == 24
for capture in captures:
    actual = subprocess.check_output([workspace/'analyzer-build/ClangBuildAnalyzer', '--analyze', capture], text=True)
    assert normalize(actual) == normalize((capture.parent/'analyzer.txt').read_text()), capture
(output/'capture-verification.txt').write_text('PASS: all 24 raw captures reproduce the saved analyzer text.\n')
print('PASS: all 24 raw captures reproduce the saved analyzer text.')
