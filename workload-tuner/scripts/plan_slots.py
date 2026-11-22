#!/usr/bin/env python3
"""How many more copies of a job fit on a machine right now, and what limits it.

  python plan_slots.py --stats stats.json --threads 1 --ram 1.0 [--vram 0] [--running 3]
                       [--reserve-ram 2] [--reserve-vram 1.5] [--hyperthreads]

  --stats      JSON from machine_stats.py --json (local file, or "-" for stdin). Omit it to measure this machine now.
  --threads    CPU threads one job keeps busy (1 for most solvers and single-threaded scripts).
  --ram/--vram peak GB one job uses (measure one run first; use the biggest you have seen).
  --running    jobs of this kind already running on the machine (they are already inside the free numbers).
  --hyperthreads  count logical threads, not real cores (worth it only for jobs that wait on disk/network).

Prints the number of NEW jobs to start and which resource is the limit.
"""
import argparse, json, os, sys, subprocess

HERE = os.path.dirname(os.path.abspath(__file__))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--stats")
    ap.add_argument("--threads", type=float, default=1)
    ap.add_argument("--ram", type=float, required=True)
    ap.add_argument("--vram", type=float, default=0)
    ap.add_argument("--running", type=int, default=0)
    ap.add_argument("--reserve-ram", type=float, default=2.0)
    ap.add_argument("--reserve-vram", type=float, default=1.5)
    ap.add_argument("--hyperthreads", action="store_true")
    a = ap.parse_args()

    if a.stats in (None, ""):
        s = json.loads(subprocess.run([sys.executable, os.path.join(HERE, "machine_stats.py"), "--json"],
                                      capture_output=True, text=True).stdout)
    else:
        s = json.load(sys.stdin if a.stats == "-" else open(a.stats, encoding="utf-8-sig"))

    cores = s["logical_cores"] if a.hyperthreads else s["physical_cores"]
    # threads already busy, from the CPU meter (covers other programs, not only our jobs)
    busy = (s.get("cpu_percent") or 0) / 100.0 * s["logical_cores"]
    cpu_room = max(0, int((cores - max(busy, a.running * a.threads)) // a.threads))
    ram_room = max(0, int((s["ram_free_gb"] - a.reserve_ram) // a.ram)) if a.ram > 0 else 999
    limits = {"cpu": cpu_room, "ram": ram_room}
    if a.vram > 0:
        free = max((g["vram_free_gb"] for g in s.get("gpus", [])), default=0)
        limits["vram"] = max(0, int((free - a.reserve_vram) // a.vram))
    n = min(limits.values())
    binding = min(limits, key=limits.get)
    print(json.dumps({"host": s.get("host"), "start_now": n, "limited_by": binding, "room": limits,
                      "cores_counted": cores, "threads_busy_now": round(busy, 1),
                      "ram_free_gb": s["ram_free_gb"], "reserve_ram_gb": a.reserve_ram}))


if __name__ == "__main__":
    main()
