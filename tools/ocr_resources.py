"""Linux process-specific CPU accounting and sampled process-tree resident sets.

RSS is summed within each scan, then its observed maximum is retained. It is
never a sum of independent per-process maxima. CPU from wait4 belongs to the
selected PID and descendants it waited for, not a process-global child delta.
"""
import os
from pathlib import Path
import subprocess
import threading
import time

INTERVAL = .05
TICKS = os.sysconf('SC_CLK_TCK')
PAGE_SIZE = os.sysconf('SC_PAGE_SIZE')


def process(pid):
    try:
        fields = Path(f'/proc/{pid}/stat').read_text().rsplit(')', 1)[1].split()
        return {'pid': pid, 'identity': fields[19], 'state': fields[0],
                'own_cpu': (int(fields[11]) + int(fields[12])) / TICKS,
                'waited_cpu': (int(fields[13]) + int(fields[14])) / TICKS,
                'rss': max(0, int(fields[21])) * PAGE_SIZE}
    except (OSError, IndexError, ValueError):
        return None


def children(pid):
    values = set()
    try:
        for task in Path(f'/proc/{pid}/task').iterdir():
            try:
                values.update(int(value) for value in (task / 'children').read_text().split())
            except (OSError, ValueError):
                pass
    except OSError:
        pass
    return values


class ProcessResources:
    def __init__(self, pid, *, baseline=False, publish=None):
        self.pid, self.publish = pid, publish
        self.started = time.monotonic()
        self.initial = process(pid)
        self.baseline_available = not baseline or self.initial is not None
        self.baseline_own = self.initial['own_cpu'] if baseline and self.initial else 0
        self.baseline_inclusive = (self.initial['own_cpu'] + self.initial['waited_cpu']) if baseline and self.initial else 0
        self.known, self.cpu_observed = {}, {}
        self.inclusive_cpu = 0
        self.peak_rss = None
        self.samples = self.max_processes = 0
        self.live = set()
        self.last_publish = 0
        self.errors = []
        self.stopped = threading.Event()
        self.thread = threading.Thread(target=self._observe, name=f'OCR-resources-{pid}', daemon=True)

    def start(self):
        self.sample()
        self._publish()
        self.thread.start()
        return self

    def sample(self):
        queue, observed = [self.pid, *self.known], {}
        while queue:
            pid = queue.pop()
            if pid in observed:
                continue
            value = process(pid)
            if value is None or pid in self.known and self.known[pid] != value['identity']:
                continue
            if pid == self.pid and self.initial and value['identity'] != self.initial['identity']:
                continue
            self.known[pid] = value['identity']
            observed[pid] = value
            queue.extend(children(pid) - observed.keys())
        self.samples += 1
        self.live = {pid for pid, value in observed.items() if value['state'] not in ('Z', 'X')}
        self.max_processes = max(self.max_processes, len(self.live))
        rss = sum(observed[pid]['rss'] for pid in self.live)
        if rss > 0:
            self.peak_rss = max(self.peak_rss or 0, rss)
        for pid, value in observed.items():
            own = max(0, value['own_cpu'] - (self.baseline_own if pid == self.pid else 0))
            self.cpu_observed[pid] = max(self.cpu_observed.get(pid, 0), own)
        if self.pid in observed:
            value = observed[self.pid]
            self.inclusive_cpu = max(self.inclusive_cpu,
                value['own_cpu'] + value['waited_cpu'] - self.baseline_inclusive)

    def snapshot(self, *, final=False, wait_usage=None, returncode=None):
        sampled_cpu = max(self.inclusive_cpu, sum(self.cpu_observed.values())) if self.known and self.baseline_available else None
        cpu = sampled_cpu
        cpu_status = 'sampled_lower_bound' if cpu is not None else 'unavailable'
        basis = 'Per-PID /proc counters; max of inclusive root and individually observed own CPU, never added together.'
        if wait_usage is not None:
            waited = wait_usage.ru_utime + wait_usage.ru_stime
            complete = not (self.live - {self.pid}) and (sampled_cpu or 0) <= waited + 2 / TICKS
            cpu = waited if complete else max(waited, sampled_cpu or 0)
            cpu_status = 'observed_wait4' if complete else 'partial_wait4_and_observed_tree'
            basis = 'wait4 for the exact child PID, including descendants waited for through the chain; observed unjoined descendants make coverage partial.'
        elif final and self.pid == os.getpid() and self.initial and not (self.live - {self.pid}):
            cpu = self.inclusive_cpu
            cpu_status = 'observed_process_counter'
            basis = 'Root process CPU and waited-descendant CPU during this native admission; one inclusive scope for all its threads.'
        coverage = 'sampled' if final and cpu_status.startswith('observed_') and not self.errors else 'partial'
        return {'schema_version': 1, 'status': coverage,
            'scope': {'kind': 'process_tree', 'root_pid': self.pid,
                      'root_start_ticks': self.initial['identity'] if self.initial else None,
                      'includes_descendants': True, 'cpu': 'process_and_waited_descendants',
                      'memory': 'sum_of_resident_sets_within_one_scan', 'shared_pages': 'counted_per_process',
                      'measurement_overhead_included': True, 'provider_compute': False},
            'cpu_seconds': cpu, 'cpu_unit': 's', 'cpu_status': cpu_status, 'cpu_basis': basis,
            'peak_rss_bytes': self.peak_rss, 'ram_unit': 'bytes',
            'ram_status': 'sampled_lower_bound' if self.peak_rss is not None else 'unavailable',
            'ram_basis': 'Maximum of scan-local sums of RSS for the root and observed descendants. Shared pages may appear in multiple processes; peaks between scans can be missed.',
            'sampling_interval_seconds': INTERVAL, 'sample_count': self.samples,
            'max_observed_processes': self.max_processes, 'processes_observed': len(self.known),
            'observed_runtime_seconds': max(0, time.monotonic() - self.started),
            'termination': 'running' if not final else 'completed' if returncode in (None, 0) else 'signal' if returncode < 0 else 'failed',
            'errors': self.errors}

    def _publish(self):
        if self.publish is None:
            return
        try:
            self.publish(self.snapshot())
        except (OSError, ValueError) as error:
            if not self.errors:
                self.errors.append(str(error))
        self.last_publish = time.monotonic()

    def _observe(self):
        while not self.stopped.wait(INTERVAL):
            self.sample()
            if time.monotonic() - self.last_publish >= 1.:
                self._publish()

    def finish(self, *, wait_usage=None, returncode=None):
        self.stopped.set()
        self.thread.join()
        self.sample()
        return self.snapshot(final=True, wait_usage=wait_usage, returncode=returncode)


def run_measured(command, *, env, publish):
    """Drain both pipes while this caller alone reaps this exact child PID."""
    child = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env, text=True)
    resources = ProcessResources(child.pid, publish=publish).start()
    output = {}

    def drain(name, stream):
        try:
            output[name] = stream.read()
        finally:
            stream.close()

    readers = [threading.Thread(target=drain, args=(name, stream), daemon=True)
               for name, stream in [('stdout', child.stdout), ('stderr', child.stderr)]]
    for reader in readers:
        reader.start()
    try:
        while True:
            try:
                _, status, usage = os.wait4(child.pid, 0)
                break
            except InterruptedError:
                continue
        child.returncode = os.waitstatus_to_exitcode(status)
        for reader in readers:
            reader.join()
        measured = resources.finish(wait_usage=usage, returncode=child.returncode)
    except BaseException:
        if child.returncode is None:
            child.kill()
            child.wait()
        resources.finish(returncode=child.returncode)
        raise
    return subprocess.CompletedProcess(command, child.returncode, output.get('stdout', ''), output.get('stderr', '')), measured


def thread_resources(start, *, termination='completed'):
    interrupted = termination == 'interrupted'
    return {'schema_version': 1, 'status': 'partial' if interrupted else 'observed',
        'scope': {'kind': 'thread', 'root_pid': os.getpid(), 'thread_id': threading.get_native_id(),
                  'includes_descendants': False, 'provider_compute': False},
        'cpu_seconds': max(0, time.thread_time() - start), 'cpu_unit': 's', 'cpu_status': 'observed_thread_counter',
        'cpu_basis': 'Calling thread CPU only. External tools and other native threads have separate or parent scopes.',
        'peak_rss_bytes': None, 'ram_unit': 'bytes', 'ram_status': 'unavailable',
        'ram_basis': 'Shared process memory cannot be attributed to one in-process unit, particularly during concurrent work.',
        'sample_count': 0, 'max_observed_processes': 0,
        'termination': termination}
