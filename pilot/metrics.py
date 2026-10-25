import os
import threading
import time
from pathlib import Path

import psutil


def container_counters():
    result = {}
    for name in ("cpu.stat", "memory.current", "memory.peak", "memory.events", "memory.swap.current"):
        try:
            raw = (Path('/sys/fs/cgroup') / name).read_text().strip()
            result[name] = int(raw) if ' ' not in raw and '\n' not in raw else {
                k: int(v) for k, v in (line.split() for line in raw.splitlines())}
        except (OSError, ValueError):
            result[name] = None
    return result


class Sampler:
    def __init__(self, interval, cpu_budget, root_pid=None):
        self.interval, self.cpu_budget = interval, cpu_budget
        self.root_pid = root_pid or os.getppid()
        self.samples = []
        self.stop_event = threading.Event()
        self.thread = threading.Thread(target=self._loop, daemon=True)

    def snapshot(self):
        root = psutil.Process(self.root_pid)
        records = []
        for p in [root] + root.children(recursive=True):
            try:
                cpu = p.cpu_times()
                records.append({'pid': p.pid, 'created': p.create_time(),
                                'cpu_s': cpu.user + cpu.system, 'rss': p.memory_info().rss})
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
        return {'time': time.perf_counter(), 'rss_sum_bytes': sum(p['rss'] for p in records),
                'processes': records, 'cgroup': container_counters()}

    def _loop(self):
        while not self.stop_event.wait(self.interval):
            self.samples.append(self.snapshot())

    def start(self):
        self.samples.append(self.snapshot())
        self.thread.start()

    def stop(self, runtime):
        self.stop_event.set()
        self.thread.join()
        self.samples.append(self.snapshot())
        initial = {(p['pid'], p['created']): p['cpu_s'] for p in self.samples[0]['processes']}
        latest = {}
        for s in self.samples:
            for p in s['processes']:
                latest[p['pid'], p['created']] = p['cpu_s']
        cpu_s = sum(max(0, v - initial.get(k, 0)) for k, v in latest.items())
        first, last = self.samples[0]['cgroup'], self.samples[-1]['cgroup']
        a, b = first.get('cpu.stat'), last.get('cpu.stat')
        cg_cpu = (b['usage_usec'] - a['usage_usec']) / 1e6 if a and b else None
        return {'sample_interval_s': self.interval, 'samples': len(self.samples),
                'process_cpu_seconds': cpu_s,
                'cpu_budget_percent': 100 * cpu_s / runtime / self.cpu_budget,
                'cgroup_cpu_seconds': cg_cpu,
                'cgroup_cpu_budget_percent': 100 * cg_cpu / runtime / self.cpu_budget if cg_cpu is not None else None,
                'rss_sum_peak_bytes': max(s['rss_sum_bytes'] for s in self.samples),
                'container_memory_sampled_peak_bytes': max(
                    (s['cgroup']['memory.current'] for s in self.samples
                     if s['cgroup']['memory.current'] is not None), default=None),
                'cgroup_before': first, 'cgroup_after': last,
                'caveat': 'RSS sum double-counts shared pages; sampled peaks; process CPU may miss short-lived processes; cgroup includes entire container'}
