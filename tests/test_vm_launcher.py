"""Exercise the launcher with simulated Docker, never generating benchmark results."""
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


def bash_executable():
    if os.name == 'nt':
        candidate = Path('C:/Program Files/Git/bin/bash.exe')
        return str(candidate) if candidate.exists() else None
    return shutil.which('bash')


@unittest.skipUnless(bash_executable(), 'Bash required for VM launcher checks')
class LauncherTests(unittest.TestCase):
    def setUp(self):
        parent = Path('tmp/launcher-tests')
        parent.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=parent)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        (self.root / 'scripts').mkdir()
        shutil.copy2('scripts/vm.sh', self.root / 'scripts/vm.sh')
        shutil.copy2('.env.vm.example', self.root / '.env.vm.example')
        self.harness = self.root / 'harness.sh'
        self.harness.write_text(r'''set -Eeuo pipefail
docker() {
    printf '%s\n' "$*" >> "$CALL_LOG"
    case "$*" in
        'info --format '{{.OSType}}) printf 'linux\n' ;;
        'compose version') printf 'SIMULATED Compose for unit tests\n' ;;
        'compose port results 8080') printf '0.0.0.0:5285\n' ;;
        'compose port dashboard 8787') printf '0.0.0.0:5185\n' ;;
        'compose config') printf 'services: {}\n' ;;
        *'--service-ports experiment '* )
            if [[ "${SIMULATE_FAILURE:-0}" == 1 ]]; then return 7; fi ;;
    esac
    return 0
}
git() {
    if [[ "$*" == 'rev-parse HEAD' ]]; then printf '0123456789abcdef0123456789abcdef01234567\n'; fi
    return 0
}
curl() { return 0; }
export -f docker git curl
bash "$@"
''', encoding='utf-8', newline='\n')

    def run_launcher(self, mode='smoke', fail=False):
        env = {**os.environ, 'CALL_LOG': (self.root / 'calls.log').as_posix(),
               'SIMULATE_FAILURE': '1' if fail else '0'}
        process = subprocess.run([bash_executable(), self.harness.as_posix(),
            (self.root / 'scripts/vm.sh').as_posix(), mode], env=env,
            text=True, capture_output=True, timeout=30)
        calls_file = self.root / 'calls.log'
        calls = calls_file.read_text().splitlines() if calls_file.exists() else []
        return process, calls

    def test_shell_syntax(self):
        result = subprocess.run([bash_executable(), '-n', 'scripts/vm.sh'],
                                capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_smoke_before_web_and_own_services_only(self):
        result, calls = self.run_launcher()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        stop = calls.index('compose --profile demo stop results dashboard')
        build = calls.index('compose build experiment')
        units = next(i for i, c in enumerate(calls) if 'unittest discover' in c)
        smoke = next(i for i, c in enumerate(calls) if '--service-ports experiment smoke ' in c)
        web = calls.index('compose --profile demo up -d results dashboard')
        self.assertTrue(stop < build < units < smoke < web)
        self.assertIn('vm-smoke-0123456789', calls[smoke])
        self.assertEqual((self.root / '.env').read_bytes(), (self.root / '.env.vm.example').read_bytes())
        self.assertFalse(any('prune' in c or '--volumes' in c for c in calls))

    def test_failure_stops_before_publishing(self):
        result, calls = self.run_launcher(fail=True)
        self.assertEqual(result.returncode, 7, result.stdout + result.stderr)
        self.assertNotIn('compose --profile demo up -d results dashboard', calls)

    def test_pilot_and_existing_configuration_preserved(self):
        (self.root / '.env').write_text('RESULTS_PORT=9999\n', encoding='utf-8')
        result, calls = self.run_launcher(mode='pilot')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue(any('--service-ports experiment pilot ' in c for c in calls))
        self.assertEqual((self.root / '.env').read_text(), 'RESULTS_PORT=9999\n')

    def test_invalid_mode_does_not_touch_docker(self):
        result, calls = self.run_launcher(mode='invalid')
        self.assertEqual(result.returncode, 2)
        self.assertEqual(calls, [])
