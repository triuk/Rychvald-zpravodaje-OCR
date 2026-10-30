"""Explicit native-tool fixture with independent child/grandchild workloads."""
import subprocess
import sys
import time
import mmap
from pathlib import Path

role, mode, gate = sys.argv[1:]
gate = Path(gate)
if role == 'grandchild' and mode == 'staggered':
    while not gate.exists():
        time.sleep(.01)
    time.sleep(.2)  # Separate the two peaks by several sampling intervals.
size = (128 if mode == 'staggered' else 8 if role == 'child' else 12) * 1024 * 1024
memory = mmap.mmap(-1, size)
for position in range(0, size, 4096):
    memory[position] = 1
if role == 'child':
    child = subprocess.Popen([sys.executable, __file__, 'grandchild', mode, str(gate)])
deadline = time.process_time() + .04
while time.process_time() < deadline:
    sum(range(500))
time.sleep(3 if mode == 'hold' else .3)
memory.close()
if role == 'child':
    if mode == 'staggered':
        gate.write_text('First resident set was released before the second allocation.')
    raise SystemExit(child.wait())
