---
name: workload-tuner
description: Get the most out of every CPU core, GPU and gigabyte of RAM/VRAM on one or more computers when running many jobs - solver runs, simulations, test suites, builds, renders, batch scripts, AI image or model jobs. Picks how many jobs to run at once for each machine from the job type and live memory, spreads them over a second PC via SSH, keeps checking the load every 10-15 minutes and refills idle slots, and keeps a record of throughput and time saved. Use this whenever the user wants to speed up a batch of work, asks to "use more CPU/GPU", "max out", "run more workers", "use my other PC/laptop too", asks why the CPU meter is low, or starts a long multi-run job - even if they don't mention tuning.
---

# Workload tuner

Run a batch of jobs as fast as the hardware allows without tipping a machine into swapping or out-of-memory
crashes. On a real project this took a batch from 1-3 solver runs at a time on one PC (1-3 "PC-minutes" of work per
minute) to 17 runs over a desktop and a laptop (about 12 PC-minutes per minute): roughly 4x the work rate, and an
estimated 3-5 hours saved on a 50-minute round.

The gains came from five habits. The scripts make each one quick.

1. **Know the job's shape before choosing a number.** How many threads one job keeps busy, its peak RAM and VRAM.
2. **Memory is usually the real limit, not CPU.** Gate every new job on free RAM/VRAM, not on the CPU meter.
3. **Read the CPU meter correctly.** On an 8-core/16-thread PC, 8 single-thread jobs fill every real core while the
   meter shows only about 50%. Jobs past the real core count share cores and each one slows down.
4. **Use every machine you have.** A second PC (often faster per core than the main one) roughly doubles throughput.
5. **Check often and refill.** Long jobs finish in bunches; if nobody refills the slots, throughput dips sharply.

## Scripts (in `scripts/`, standard-library Python 3; no installs needed)

| Script | What it does |
|---|---|
| `machine_stats.py [--json] [--top N] [--match TEXT]` | Cores (real and logical), CPU %, free/total RAM, NVIDIA GPUs (free VRAM, busy %), biggest memory users, count of running jobs matching TEXT |
| `plan_slots.py --threads T --ram GB [--vram GB] [--stats FILE]` | How many more jobs of this shape to start now on a machine, and which resource limits it |
| `remote.py HOST info / stats / push / start / log / wait / get / jobs / windows` | Run jobs on a second PC over SSH, hidden, each with a log; `HOST` can be `local` too |
| `run_record.py --base HOST --slots N --hosts ... --speed HOST=F` | Writes RUN-RECORD.md: work done, estimated time saved, throughput per 10-minute slice, every job |

Run them with the user's Python (`py -3` on Windows, `python3` elsewhere). Paths below are relative to this skill's
folder.

## The workflow

### 1. Size up the machines (2 minutes)

```
python scripts/machine_stats.py --top 10
python scripts/remote.py <host> info          # for each extra PC the user has set up for SSH
```

Note real cores, free RAM, GPUs and their free VRAM, and anything big that the batch doesn't need (game launchers,
chat apps, overlays, an idle game engine hub). If memory is tight, **ask the user** before closing programs; list each
one with its memory use. Never close security software, system services, or the PC maker's fan/power tool.

If there is no second PC set up, say in one line what it would add (about 1.5-2.5x for CPU batches) and point to
`references/second-pc-setup.md`. Carry on with one machine; it's optional.

### 2. Classify the job and measure one run

Use `references/job-types.md` to choose the starting shape (threads per job, typical RAM, CPU or GPU, how far past real
cores it scales). Then run **one** job and watch its peak memory (`machine_stats.py --match <script name>` while it
runs, or the job's own log). Use the biggest number you see; jobs of the same kind can vary 5-10x in memory
(0.2-2.4 GB was seen across variants of one solver).

If the user has more than one machine, time the same job on each once. The ratio is that machine's speed factor for
`run_record.py`. Real example: the laptop did a solver setup in 21 s against the desktop's 36 s, a factor of 1.7.

### 3. Fill the machines, conservatively first

```
python scripts/plan_slots.py --threads 1 --ram 1.5            # this PC, measured now
python scripts/remote.py <host> stats > s.json
python scripts/plan_slots.py --stats s.json --threads 1 --ram 1.5   # the other PC
```

- Start about half of what `plan_slots` says, then step up after the first check. Memory use often climbs partway
  through a run.
- Keep a **2 GB free-RAM reserve** per machine, and about **1.5-2 GB free VRAM** per GPU. The OS and the user's other
  programs need it, and running out costs far more than one fewer job.
- Single-thread jobs: aim for one job per **real** core. Go past that only for jobs that wait on disk or network, or
  when a test shows throughput still rising.
- Multi-thread jobs (builds, Blender, test runners with their own workers): fewer jobs, each with a fixed thread count,
  so the jobs' threads add up to about the real cores. Don't let three jobs each grab all cores.
- GPU jobs: one job per GPU is the safe start. Add a second only if VRAM has room and the GPU sits under about 70% busy.
- Put the biggest-memory jobs on the machine with the most free RAM, and the long ones on the fastest machine.
- On a second PC use `remote.py <host> start JOB --dir NAME -- <command>`. It starts the job hidden, so no window pops
  up on the other person's screen, and the job survives the SSH connection dropping. Copy non-git inputs with `push`.
- If parallel agents or helpers run the jobs, give each a per-machine limit (for example "at most 3 runs on each PC")
  **plus** the rule "start a run only if that PC still has at least 2 GB of RAM free". The limit alone isn't enough,
  because job sizes vary.

### 4. Check every 10-15 minutes, and refill

At each check, run `machine_stats.py` here and `remote.py <host> stats` for each other PC, then act straight away:

| What you see | Do this |
|---|---|
| RAM free well above the reserve, real cores idle | raise the per-machine limit by 1-2 and start more jobs |
| RAM free near or below the reserve | stop adding; let the running jobs finish |
| CPU meter about real cores / logical threads (about 50% on SMT chips) and RAM still free | the cores are full: extra jobs only share cores; add more only if throughput keeps rising |
| Throughput dipped (long jobs finished together) | refill the empty slots now |
| A job's memory grows without stopping | stop new starts on that machine; warn the user |

Give the user one line per check, for example: "Desktop 9 jobs, 83% CPU, 2.6 GB free (full); laptop 8 jobs, 54%,
5.5 GB free (room for 2)". Stop raising limits when (a) both machines are at the RAM reserve or the real core count,
or (b) the last raise didn't increase work per minute. Say so when you stop.

### 5. Keep the record, and report time saved

```
python scripts/run_record.py --hosts local laptop --base local --slots 8 --speed laptop=1.7 --before 2
```

Use `--extra-log-glob "PATTERN@HOST"` for jobs started some other way that each write one log file. Show the user:
- work per minute before and after each change;
- time saved compared with the base machine alone, and with the old way (`--before`);
- the caveats: speed factors are measured on a sample job, and jobs without logs are not counted.

Call it an estimate. Never present it as a stopwatch result.

## Rules that keep it safe

- Never open windows or start interactive programs on another person's PC. Use `remote.py start`, which runs hidden.
  Check with `remote.py <host> windows`.
- Ask before installing anything on either machine, closing the user's programs, or changing startup programs.
  Show what each one is and how much memory it uses.
- Don't move GPU work to the CPU just to dodge a full card. Wait for VRAM instead; the CPU version is usually far slower.
- Don't run a big local AI model, or anything else that needs a lot of memory, while the batch is filling the machine.
- Leave a restart suggestion for long-running machines (days of uptime) once the batch is done. Not during it.

## References

- `references/job-types.md`: starting shapes for common job types (solvers, simulations, builds, tests, Blender,
  Unity, AI image and 3D models, video encoding).
- `references/second-pc-setup.md`: setting up a second Windows/Linux/macOS PC for SSH jobs (one-time, about 15 min).
