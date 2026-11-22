#!/usr/bin/env python3
"""Snapshot of one machine's capacity and load: cores, CPU %, RAM, GPUs (NVIDIA), and the biggest memory users.

Standard library only (uses psutil if it happens to be installed). Works on Windows, Linux and macOS.

  python machine_stats.py            human-readable summary
  python machine_stats.py --json     one JSON object (what plan_slots.py and remote.py read)
  python machine_stats.py --top 10   also list the 10 programs using the most memory
  python machine_stats.py --match lp  count running jobs whose command line contains "lp" (Windows/Linux)
"""
import json, os, platform, re, shutil, subprocess, sys, time

SYSTEM = platform.system()


def run(args, timeout=30):
    try:
        r = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
        return r.stdout if r.returncode == 0 else ""
    except Exception:
        return ""


def ps(script):
    return run(["powershell", "-NoProfile", "-Command", script], timeout=60)


def cores():
    logical = os.cpu_count() or 1
    physical = None
    if SYSTEM == "Windows":
        out = ps("(Get-CimInstance Win32_Processor | Measure-Object NumberOfCores -Sum).Sum")
        physical = int(out.strip()) if out.strip().isdigit() else None
    elif SYSTEM == "Linux":
        out = run(["lscpu", "-p=Core,Socket"])
        pairs = {l for l in out.splitlines() if l and not l.startswith("#")}
        physical = len(pairs) or None
    elif SYSTEM == "Darwin":
        out = run(["sysctl", "-n", "hw.physicalcpu"]).strip()
        physical = int(out) if out.isdigit() else None
    return logical, physical or logical


def cpu_percent():
    try:
        import psutil  # optional
        return psutil.cpu_percent(interval=2)
    except ImportError:
        pass
    if SYSTEM == "Windows":
        out = ps("(Get-Counter '\\Processor(_Total)\\% Processor Time' -SampleInterval 2 -MaxSamples 2).CounterSamples.CookedValue")
        vals = [float(v) for v in out.split() if re.match(r"^[\d.]+$", v)]
        return round(sum(vals) / len(vals), 1) if vals else None
    if SYSTEM == "Linux":
        def snap():
            f = open("/proc/stat").readline().split()[1:]
            n = [int(x) for x in f]
            return n[3] + n[4], sum(n)
        i0, t0 = snap(); time.sleep(2); i1, t1 = snap()
        return round(100.0 * (1 - (i1 - i0) / max(t1 - t0, 1)), 1)
    if SYSTEM == "Darwin":
        out = run(["top", "-l", "2", "-n", "0"])
        m = re.findall(r"([\d.]+)% idle", out)
        return round(100 - float(m[-1]), 1) if m else None
    return None


def memory_gb():
    try:
        import psutil
        v = psutil.virtual_memory()
        return round(v.available / 2**30, 1), round(v.total / 2**30, 1)
    except ImportError:
        pass
    if SYSTEM == "Windows":
        out = ps("$o=Get-CimInstance Win32_OperatingSystem; \"$($o.FreePhysicalMemory) $($o.TotalVisibleMemorySize)\"").split()
        if len(out) == 2:
            return round(int(out[0]) / 2**20, 1), round(int(out[1]) / 2**20, 1)
    if SYSTEM == "Linux":
        info = {l.split(":")[0]: int(l.split()[1]) for l in open("/proc/meminfo") if len(l.split()) >= 2}
        return round(info.get("MemAvailable", info.get("MemFree", 0)) / 2**20, 1), round(info["MemTotal"] / 2**20, 1)
    if SYSTEM == "Darwin":
        total = int(run(["sysctl", "-n", "hw.memsize"]).strip() or 0)
        vm = run(["vm_stat"])
        page = int(re.search(r"page size of (\d+)", vm).group(1)) if "page size" in vm else 4096
        free = sum(int(re.search(r"%s:\s+(\d+)" % k, vm).group(1)) for k in ("Pages free", "Pages inactive") if re.search(k, vm))
        return round(free * page / 2**30, 1), round(total / 2**30, 1)
    return None, None


def gpus():
    if not shutil.which("nvidia-smi"):
        return []
    out = run(["nvidia-smi", "--query-gpu=name,memory.total,memory.used,utilization.gpu", "--format=csv,noheader,nounits"])
    res = []
    for line in out.strip().splitlines():
        p = [x.strip() for x in line.split(",")]
        if len(p) == 4:
            tot, used = float(p[1]) / 1024, float(p[2]) / 1024
            res.append({"name": p[0], "vram_total_gb": round(tot, 1), "vram_free_gb": round(tot - used, 1), "util_percent": float(p[3])})
    return res


def top_memory(n):
    if SYSTEM == "Windows":
        out = ps("Get-Process | Group-Object Name | ForEach-Object { '{0}|{1}|{2}' -f $_.Name, $_.Count, [int](($_.Group | Measure-Object WS -Sum).Sum/1MB) }")
        rows = [l.split("|") for l in out.splitlines() if l.count("|") == 2]
        rows = [(r[0], int(r[1]), int(r[2])) for r in rows]
    else:
        out = run(["ps", "-eo", "comm=,rss="])
        agg = {}
        for l in out.splitlines():
            p = l.rsplit(None, 1)
            if len(p) == 2 and p[1].isdigit():
                name = os.path.basename(p[0])
                c, m = agg.get(name, (0, 0))
                agg[name] = (c + 1, m + int(p[1]) // 1024)
        rows = [(k, v[0], v[1]) for k, v in agg.items()]
    rows.sort(key=lambda r: -r[2])
    return [{"name": r[0], "count": r[1], "mb": r[2]} for r in rows[:n]]


def matching_jobs(pattern):
    if SYSTEM == "Windows":
        pat = pattern.replace("'", "''")
        out = ps("Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -match '" + pat + "' -and $_.CommandLine -notmatch 'machine_stats' } | "
                 "ForEach-Object { '{0}|{1}' -f $_.ProcessId, $_.CommandLine }")
    else:
        out = "\n".join("%s|%s" % tuple(l.strip().split(None, 1)) for l in run(["ps", "-eo", "pid=,args="]).splitlines()
                        if pattern in l and "machine_stats" not in l and len(l.strip().split(None, 1)) == 2)
    return [l for l in out.splitlines() if "|" in l]


def collect(top=0, match=None):
    logical, physical = cores()
    free, total = memory_gb()
    d = {"host": platform.node(), "os": SYSTEM, "logical_cores": logical, "physical_cores": physical,
         "cpu_percent": cpu_percent(), "ram_free_gb": free, "ram_total_gb": total, "gpus": gpus()}
    if top:
        d["top_memory"] = top_memory(top)
    if match:
        jobs = matching_jobs(match)
        d["matching_jobs"] = len(jobs)
        d["matching_job_lines"] = [j[:200] for j in jobs]
    return d


def main():
    a = sys.argv[1:]
    top = int(a[a.index("--top") + 1]) if "--top" in a else 0
    match = a[a.index("--match") + 1] if "--match" in a else None
    d = collect(top, match)
    if "--json" in a:
        print(json.dumps(d))
        return
    print("%s (%s): %d cores / %d threads, CPU %s%%, RAM free %s of %s GB" % (
        d["host"], d["os"], d["physical_cores"], d["logical_cores"], d["cpu_percent"], d["ram_free_gb"], d["ram_total_gb"]))
    busy_cores = (d["cpu_percent"] or 0) / 100 * d["logical_cores"]
    print("  about %.1f threads busy; %d single-thread jobs fill the real cores (the CPU meter then reads about %d%%)" % (
        busy_cores, d["physical_cores"], round(100 * d["physical_cores"] / d["logical_cores"])))
    for g in d["gpus"]:
        print("  GPU %s: %s of %s GB VRAM free, %s%% busy" % (g["name"], g["vram_free_gb"], g["vram_total_gb"], g["util_percent"]))
    if not d["gpus"]:
        print("  no NVIDIA GPU found (nvidia-smi missing)")
    for r in d.get("top_memory", []):
        print("  %6d MB  %s (x%d)" % (r["mb"], r["name"], r["count"]))
    if match:
        print("  %d running jobs match '%s'" % (d["matching_jobs"], match))


if __name__ == "__main__":
    main()
