#!/usr/bin/env python3
"""drive-check: will this drive and this computer run a local AI model well?

Point it at a folder on a drive (and, best, at a model file on that drive).
It measures the drive's real read speed, guesses how long the model takes to
load from it, checks the model against this computer's RAM, and prints one
verdict line. No installs: Python 3.8+ only. macOS, Windows and Linux.

    python3 drive_check.py /Volumes/MyDrive
    python3 drive_check.py /Volumes/MyDrive --model /Volumes/MyDrive/models/gemma-4-E4B-it-Q4_K_M.gguf
    python3 drive_check.py D:\\ --model D:\\models\\model.gguf --llama-bench D:\\app\\llama-bench.exe

MIT licence. From The Coderlog's "$10 AI USB drive" video.
"""
import argparse
import ctypes
import json
import os
import platform
import shutil
import subprocess
import sys
import time

GB = 1e9
MB = 1e6

# The ladder from the video (Gemma 4, Q4_K_M, file sizes in bytes).
LADDER = [
    ('Gemma 4 E2B Q4_K_M', 3106738272),
    ('Gemma 4 E4B Q4_K_M', 4977171584),
    ('Gemma 4 12B Q4_K_M', 7121861440),
    ('Gemma 4 31B Q4_K_M', 18323733440),
]

# Memory the model needs on top of its file: context, KV cache and the runtime.
# Measured in the video with a 4k context; a bigger context needs more.
OVERHEAD = 1.5 * GB
# Fixed start-up cost of a load (engine start, warm-up), measured on an M4.
LOAD_FIXED_S = 3.0


# ------------------------------------------------------------------ memory
def ram_total_and_free():
    """Total and currently available RAM in bytes (free may be None)."""
    system = platform.system()
    try:
        if system == 'Darwin':
            total = int(subprocess.check_output(['sysctl', '-n', 'hw.memsize']).strip())
            free = None
            try:
                out = subprocess.check_output(['memory_pressure', '-Q'], text=True)
                for line in out.splitlines():
                    if 'free percentage' in line:
                        free = total * int(line.rsplit(':', 1)[1].strip().rstrip('%')) / 100
            except Exception:  # noqa: BLE001
                pass
            return total, free
        if system == 'Linux':
            info = {}
            with open('/proc/meminfo') as f:
                for line in f:
                    k, v = line.split(':', 1)
                    info[k] = int(v.split()[0]) * 1024
            return info.get('MemTotal'), info.get('MemAvailable')
        if system == 'Windows':
            class MEMORYSTATUSEX(ctypes.Structure):
                _fields_ = [('dwLength', ctypes.c_ulong), ('dwMemoryLoad', ctypes.c_ulong),
                            ('ullTotalPhys', ctypes.c_ulonglong), ('ullAvailPhys', ctypes.c_ulonglong),
                            ('ullTotalPageFile', ctypes.c_ulonglong), ('ullAvailPageFile', ctypes.c_ulonglong),
                            ('ullTotalVirtual', ctypes.c_ulonglong), ('ullAvailVirtual', ctypes.c_ulonglong),
                            ('ullAvailExtendedVirtual', ctypes.c_ulonglong)]
            m = MEMORYSTATUSEX()
            m.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
            ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m))
            return m.ullTotalPhys, m.ullAvailPhys
    except Exception:  # noqa: BLE001
        pass
    return None, None


def model_budget(total):
    """Bytes a model (plus overhead) can use and still run fast.

    On Apple Silicon the GPU may use about 75% of RAM (12.7 GB on a 16 GB M4, from
    Metal's recommendedMaxWorkingSetSize; a bigger share on 64 GB+ Macs).
    Elsewhere we keep the same 75% so the system and your apps still fit.
    """
    if not total:
        return None
    share = 0.75 if total < 48 * GB else 0.8
    return total * share


def fit(size, total):
    """'fits', 'tight' (loads but swaps, very slow) or 'no'."""
    need = size + OVERHEAD
    budget = model_budget(total)
    if budget is None:
        return 'unknown'
    if need <= budget:
        return 'fits'
    if need <= total:
        return 'tight'
    return 'no'


# ------------------------------------------------------------------ drive speed
def _nocache(fd):
    """Ask the OS not to serve this file from its cache (macOS, Linux)."""
    try:
        if platform.system() == 'Darwin':
            import fcntl
            fcntl.fcntl(fd, 48, 1)  # F_NOCACHE
        elif hasattr(os, 'posix_fadvise'):
            os.posix_fadvise(fd, 0, 0, os.POSIX_FADV_DONTNEED)
    except Exception:  # noqa: BLE001
        pass


def read_speed(path, limit=None, block=8 * 1024 * 1024):
    """Sequential read speed of a file, in bytes/s. Reads up to `limit` bytes."""
    size = os.path.getsize(path)
    limit = int(min(size, limit or size))
    flags = os.O_RDONLY | getattr(os, 'O_BINARY', 0)
    fd = os.open(path, flags)
    try:
        _nocache(fd)
        done, t0 = 0, time.perf_counter()
        while done < limit:
            chunk = os.read(fd, min(block, limit - done))
            if not chunk:
                break
            done += len(chunk)
        took = time.perf_counter() - t0
    finally:
        os.close(fd)
    return done / took if took > 0 else 0, done, took


def write_then_read(folder, size):
    """Write a test file (with fsync), then read it back. Returns (write B/s, read B/s, read_cached?)."""
    path = os.path.join(folder, '.drive-check.tmp')
    block = os.urandom(8 * 1024 * 1024)
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, 'O_BINARY', 0)
    try:
        fd = os.open(path, flags)
        try:
            _nocache(fd)
            done, t0 = 0, time.perf_counter()
            while done < size:
                done += os.write(fd, block[: min(len(block), size - done)])
            os.fsync(fd)
            wtook = time.perf_counter() - t0
        finally:
            os.close(fd)
        if platform.system() == 'Linux':
            fd = os.open(path, os.O_RDONLY)
            _nocache(fd)
            os.close(fd)
        rs, _, _ = read_speed(path)
        # Windows has no simple cache bypass from Python: a just-written file reads from RAM.
        cached = platform.system() == 'Windows'
        return done / wtook, rs, cached
    finally:
        try:
            os.remove(path)
        except OSError:
            pass


# ------------------------------------------------------------------ llama-bench
def llama_bench(exe, model):
    try:
        out = subprocess.run([exe, '-m', model, '-p', '512', '-n', '128', '-r', '3', '-o', 'json'],
                             capture_output=True, text=True, timeout=1800)
        rows = json.loads(out.stdout)
    except Exception as e:  # noqa: BLE001
        return {'error': str(e)[:200]}
    res = {}
    for r in rows:
        if r.get('n_prompt'):
            res['prompt_tps'] = r.get('avg_ts')
        elif r.get('n_gen'):
            res['gen_tps'] = r.get('avg_ts')
    return res


# ------------------------------------------------------------------ output
def gb(x):
    return f'{x / GB:.1f} GB' if x is not None else '?'


def gib(x):
    return f'{x / 1024 ** 3:.1f} GB' if x is not None else '?'


def secs(s):
    if s < 90:
        return f'about {s:.0f} s'
    return f'about {s / 60:.0f} min'


def verdict(size, total, rspeed):
    f = fit(size, total)
    load = size / rspeed + LOAD_FIXED_S if rspeed else None
    if f == 'no':
        return f, load, 'too big for your RAM: pick the next size down'
    if f == 'tight':
        return f, load, 'it may load, but it will swap and crawl: pick the next size down'
    if load is None:
        return f, load, 'fits your RAM'
    if load > 60:
        return f, load, f'fits your RAM, but each load will take {secs(load)}: a faster drive helps'
    return f, load, f'fine for this model (load {secs(load)})'


def main(argv=None):
    ap = argparse.ArgumentParser(description='Will this drive and this computer run a local AI model well?')
    ap.add_argument('folder', help='a folder on the drive to test (needs ~1 GB free for the write test)')
    ap.add_argument('--model', help='a model file (.gguf) on that drive: read it to get the real read speed')
    ap.add_argument('--size-mb', type=int, default=1024, help='write-test size in MB (default 1024)')
    ap.add_argument('--no-write', action='store_true', help='skip the write test (read-only drives)')
    ap.add_argument('--llama-bench', metavar='EXE', help='path to llama-bench, to add tokens/s for --model')
    ap.add_argument('--json', action='store_true', help='print the results as JSON')
    a = ap.parse_args(argv)

    if not os.path.isdir(a.folder):
        ap.error(f'not a folder: {a.folder}')
    total, free = ram_total_and_free()
    out = {'computer': {'os': platform.system(), 'machine': platform.machine(), 'ram_total': total,
                        'ram_free_now': free, 'model_budget': model_budget(total)}}

    wspeed = rspeed = None
    cached = False
    if not a.no_write:
        need = a.size_mb * 1024 * 1024
        if shutil.disk_usage(a.folder).free < need * 1.2:
            print('Not enough free space for the write test: skipping it (use --size-mb to make it smaller).')
        else:
            wspeed, rspeed, cached = write_then_read(a.folder, need)
            out['drive'] = {'write_MBps': round(wspeed / MB), 'read_MBps_testfile': round(rspeed / MB),
                            'read_maybe_cached': cached}

    model = None
    if a.model:
        if not os.path.isfile(a.model):
            ap.error(f'not a file: {a.model}')
        msize = os.path.getsize(a.model)
        ms, nread, took = read_speed(a.model, limit=4 * GB)
        rspeed, cached = ms, False
        out.setdefault('drive', {})['read_MBps_model'] = round(ms / MB)
        f, load, line = verdict(msize, total, rspeed)
        model = {'file': os.path.basename(a.model), 'size': msize, 'fit': f,
                 'load_s_estimate': round(load, 1) if load else None, 'verdict': line}
        if a.llama_bench and f != 'no':
            model['llama_bench'] = llama_bench(a.llama_bench, a.model)
        out['model'] = model

    out['ladder'] = [{'name': n, 'size': s, 'fit': fit(s, total),
                      'load_s_estimate': round(s / rspeed + LOAD_FIXED_S, 1) if rspeed else None}
                     for n, s in LADDER]

    if a.json:
        print(json.dumps(out, indent=2))
        return 0

    print('drive-check')
    print(f'  computer : {platform.system()} {platform.machine()}, RAM {gib(total)}'
          + (f' ({gib(free)} free now)' if free else '')
          + f', room for a model: about {gb(model_budget(total))}')
    d = out.get('drive', {})
    if 'write_MBps' in d:
        print(f"  drive    : write {d['write_MBps']} MB/s, read {d['read_MBps_testfile']} MB/s"
              + (' (Windows may read the test file from RAM: use --model for a true read speed)' if cached else ''))
    if 'read_MBps_model' in d:
        print(f"  drive    : read {d['read_MBps_model']} MB/s from the model file")
    if model:
        print(f"  model    : {model['file']} ({gb(model['size'])})")
        lb = model.get('llama_bench') or {}
        if lb.get('gen_tps'):
            print(f"  speed    : {lb['gen_tps']:.1f} tokens/s writing, {lb.get('prompt_tps', 0):.0f} tokens/s reading")
        print(f"  verdict  : {model['verdict']}")
    print('  ladder   : what fits this computer'
          + (' (load times from this drive)' if rspeed and not cached else ''))
    mark = {'fits': 'yes  ', 'tight': 'tight', 'no': 'no   ', 'unknown': '?    '}
    for r in out['ladder']:
        lt = f", load {secs(r['load_s_estimate'])}" if r['load_s_estimate'] and r['fit'] != 'no' and not cached else ''
        print(f"    {mark[r['fit']]}  {r['name']} ({gb(r['size'])}){lt}")
    print('  RAM decides which model you can run. The drive decides how long you wait for it to load.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
