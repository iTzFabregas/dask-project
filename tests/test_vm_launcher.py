"""Exercise VM entry points with simulated Docker, without running measurements."""
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
        shutil.copytree('scripts', self.root / 'scripts')
        shutil.copy2('.env.vm.example', self.root / '.env.vm.example')
        self.harness = self.root / 'harness.sh'
        self.harness.write_text(r'''set -Eeuo pipefail
docker() {
    printf '%s\n' "$*" >> "$CALL_LOG"
    case "$*" in
        'info --format {{.OSType}}') printf 'linux\n' ;;
        'compose version') printf 'SIMULATED Compose for unit tests\n' ;;
        'compose port results 8080') printf '0.0.0.0:5285\n' ;;
        'compose port dashboard 8787') printf '0.0.0.0:5185\n' ;;
        *'compose run '*)
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

    def run_script(self, script, *args, fail=False):
        env = {**os.environ, 'CALL_LOG': (self.root / 'calls.log').as_posix(),
               'SIMULATE_FAILURE': '1' if fail else '0',
               'EXPORTS_HOST_DIR': (self.root / 'exports').as_posix()}
        process = subprocess.run([bash_executable(), self.harness.as_posix(),
            (self.root / 'scripts' / script).as_posix(), *args], env=env,
            text=True, capture_output=True, timeout=30)
        calls_file = self.root / 'calls.log'
        calls = calls_file.read_text().splitlines() if calls_file.exists() else []
        calls_file.unlink(missing_ok=True)
        return process, calls

    def test_shell_syntax(self):
        for script in ('vm.sh', 'vm-common.sh', 'vm-prepare.sh', 'vm-run.sh', 'vm-stop.sh'):
            result = subprocess.run([bash_executable(), '-n', f'scripts/{script}'],
                                    capture_output=True, text=True, timeout=15)
            self.assertEqual(result.returncode, 0, f'{script}: {result.stderr}')

    def test_prepare_builds_and_tests_without_running_measurement(self):
        result, calls = self.run_script('vm-prepare.sh')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        stop = calls.index('compose --profile demo stop results dashboard')
        build = calls.index('compose build experiment')
        units = next(i for i, call in enumerate(calls) if 'unittest discover' in call)
        environment = next(i for i, call in enumerate(calls) if 'environment --output' in call)
        self.assertTrue(stop < build < units < environment)
        self.assertFalse(any(' compose run ' in call and 'smoke' in call for call in calls))
        self.assertFalse(any(' compose --profile demo up ' in call for call in calls))
        self.assertEqual((self.root / '.env').read_bytes(), (self.root / '.env.vm.example').read_bytes())

    def test_run_applies_parameters_then_publishes_interfaces(self):
        result, calls = self.run_script(
            'vm-run.sh', 'smoke', '--workers', '4', '--partitions', '8', '--memory', '1g')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        run = next(i for i, call in enumerate(calls) if 'compose run ' in call and 'smoke' in call)
        web = calls.index('compose --profile demo up -d results dashboard')
        self.assertIn('--workers 4 --partitions 8', calls[run])
        self.assertLess(run, web)
        self.assertTrue(any('compose exec -T results' in call for call in calls))
        self.assertTrue(any('compose exec -T dashboard' in call for call in calls))
        self.assertIn('Memoria total: 1g; limite por worker Dask: 204 MiB.', result.stdout)

    def test_failed_run_does_not_start_interfaces(self):
        result, calls = self.run_script('vm-run.sh', 'pilot', fail=True)
        self.assertEqual(result.returncode, 7, result.stdout + result.stderr)
        self.assertNotIn('compose --profile demo up -d results dashboard', calls)

    def test_stop_only_stops_project_interfaces_and_preserves_volumes(self):
        result, calls = self.run_script('vm-stop.sh')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(calls.count('compose --profile demo stop results dashboard'), 1)
        self.assertFalse(any(' down' in call or '--volumes' in call or 'prune' in call for call in calls))

    def test_invalid_parameters_do_not_touch_docker(self):
        result, calls = self.run_script('vm-run.sh', 'smoke', '--workers', '3')
        self.assertEqual(result.returncode, 2)
        self.assertEqual(calls, [])
