#!/usr/bin/env python3
"""Throughput and time-saved record for a batch of jobs spread over one or more machines.

  python run_record.py --base HOST --slots 8 [--speed laptop=1.7] [--speed local=1] \
                       [--hosts local laptop] [--extra-log-glob "C:/work/*.log"@local] [--out RUN-RECORD.md]

  --hosts   machines whose jobs (started with remote.py) to include; each is read with `remote.py HOST jobs`.
  --extra-log-glob PATTERN@HOST  also count jobs that each wrote one log file (start = file creation, end = last write).
  --base    the machine you would have used alone (the comparison baseline).
  --slots   how many jobs the base machine alone could run at once (its real core count, or less if RAM is the limit).
  --speed   HOST=FACTOR: how much work one minute of a job on HOST does, in base-machine minutes. Measure it: run the
            same job on both and divide the base time by the other's time. Unlisted hosts count as 1.0.
  --before  RUNS: how many jobs at a time the old way ran (adds a "compared with the old way" line), e.g. --before 2.

Writes a Markdown record (totals, time saved, 10-minute throughput slices, every job) and prints it.
It is an estimate, not a stopwatch test: it says so in the output, with the speed factors it used.
"""
import argparse, datetime as dt, glob, os, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__))


def jobs_from_host(host):
    out = subprocess.run([sys.executable, os.path.join(HERE, "remote.py"), host, "jobs"], capture_output=True, text=True).stdout
    rows = []
    for line in out.splitlines():
        p = line.strip().split("|")
        if len(p) == 4:
            try:
                rows.append((host, p[0], dt.datetime.fromisoformat(p[1]), dt.datetime.fromisoformat(p[2]), p[3]))
            except ValueError:
                pass
    return rows


def jobs_from_glob(spec, now):
    pattern, host = spec.rsplit("@", 1)
    rows = []
    for f in glob.glob(pattern):
        st = os.stat(f)
        s = dt.datetime.fromtimestamp(getattr(st, "st_birthtime", st.st_ctime)).astimezone()
        e = dt.datetime.fromtimestamp(st.st_mtime).astimezone()
        rows.append((host, os.path.basename(f), s, e, "running" if (now - e).total_seconds() < 120 else "done"))
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--hosts", nargs="*", default=[])
    ap.add_argument("--extra-log-glob", action="append", default=[])
    ap.add_argument("--base", required=True)
    ap.add_argument("--slots", type=int, required=True)
    ap.add_argument("--speed", action="append", default=[])
    ap.add_argument("--before", type=float)
    ap.add_argument("--out", default="RUN-RECORD.md")
    a = ap.parse_args()

    speed = {k: float(v) for k, v in (s.split("=") for s in a.speed)}
    now = dt.datetime.now().astimezone()
    runs = []
    for h in a.hosts:
        runs += jobs_from_host(h)
    for g in a.extra_log_glob:
        runs += jobs_from_glob(g, now)
    if not runs:
        sys.exit("no jobs found")
    runs = [(h, n, s, now if st == "running" else e, st) for h, n, s, e, st in runs]
    runs.sort(key=lambda r: r[2])
    t0 = runs[0][2]
    elapsed = (now - t0).total_seconds() / 60

    work = {}
    for h, n, s, e, st in runs:
        work[h] = work.get(h, 0) + max((e - s).total_seconds(), 0) / 60 * speed.get(h, 1.0)
    total = sum(work.values())
    base_alone = max(elapsed, total / a.slots)  # the base machine alone, full, doing all of it
    others = total - work.get(a.base, 0)

    L = ["# Run record (updated %s)\n" % now.strftime("%Y-%m-%d %H:%M"),
         "Started %s, %.0f min ago; %d jobs (%s).\n" % (t0.strftime("%H:%M"), elapsed, len(runs),
                                                     ", ".join("%s %d" % (h, sum(r[0] == h for r in runs)) for h in work)),
         "**Work done, in %s-minutes:** %s; total %.0f.\n" % (a.base, ", ".join("%s %.0f" % kv for kv in work.items()), total),
         "## Estimated time saved\n",
         "| Compared with | Same work would take | This took | Saved |", "|---|---|---|---|",
         "| %s alone, run full (%d at once) | %.0f min | %.0f min | **%.0f min** |" % (
             a.base, a.slots, elapsed + others / a.slots, elapsed, others / a.slots)]
    if a.before:
        L.append("| The old way (%s, %.0f at once) | %.0f min | %.0f min | **%.0f min** |" % (
            a.base, a.before, total / a.before, elapsed, max(total / a.before - elapsed, 0)))
    L += ["", "Estimate, not a stopwatch test. Speed factors used: %s; %s alone runs %d jobs at once." % (
        ", ".join("%s=%.2f" % (h, speed.get(h, 1.0)) for h in work), a.base, a.slots), "",
          "## Throughput over time (10-minute slices)\n",
          "| Slice | " + " | ".join("Avg jobs, %s" % h for h in work) + " | Work per minute (%s-minutes) |" % a.base,
          "|---|" + "---|" * len(work) + "---|"]
    t = t0
    while t < now:
        t1 = min(t + dt.timedelta(minutes=10), now)
        counts = {h: 0.0 for h in work}
        u, n = t, 0
        while u < t1:
            n += 1
            for h, _, s, e, _st in runs:
                if s <= u < e:
                    counts[h] += 1
            u += dt.timedelta(minutes=1)
        rate = sum(counts[h] / max(n, 1) * speed.get(h, 1.0) for h in work)
        L.append("| %s-%s | %s | %.1f |" % (t.strftime("%H:%M"), t1.strftime("%H:%M"),
                                            " | ".join("%.1f" % (counts[h] / max(n, 1)) for h in work), rate))
        t = t1
    L += ["", "## Every job\n", "| Start | Host | Job | Minutes | %s-minutes | State |" % a.base, "|---|---|---|---|---|---|"]
    for h, n, s, e, st in runs:
        m = max((e - s).total_seconds(), 0) / 60
        L.append("| %s | %s | %s | %.1f | %.1f | %s |" % (s.strftime("%H:%M"), h, n, m, m * speed.get(h, 1.0), st))
    text = "\n".join(L) + "\n"
    open(a.out, "w", encoding="utf-8").write(text)
    print(text)


if __name__ == "__main__":
    main()
