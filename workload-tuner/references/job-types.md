# Starting shapes by job type

These are starting points. Always measure one run's peak memory and adjust. "Cores" means real cores, not logical threads.

| Job type | Threads per job | Typical RAM per job | Runs on | How many at once (start) | Scales past real cores? |
|---|---|---|---|---|---|
| Optimisation solvers (scipy/HiGHS MILP and LP, OR-Tools, CBC), most single-threaded Python/R/MATLAB scripts | 1 | 0.2-2.5 GB; grows with problem size | CPU | 1 per core, RAM-gated | Barely; stop at real cores |
| Parameter sweeps / seed sweeps / Monte Carlo (independent runs) | 1 | small to medium | CPU | 1 per core | A little (5-20%) if runs wait on disk |
| Compiling (C/C++/Rust/.NET/Unity script builds) | build tool's own `-j` | 1-4 GB per build | CPU + disk | 1 build with `-j <cores>`; 2 builds with `-j <cores/2>` | Yes, modestly; disk often binds first |
| Test suites | runner workers (pytest -n, dotnet test, Unity test runner) | 0.5-3 GB per worker | CPU | split the suite across machines; workers about real cores per machine | Rarely |
| Game-engine batch jobs (Unity -batchmode, Unreal commandlets) | multi | 2-6 GB each | CPU (GPU if rendering) | 1-2 per machine | No |
| Blender CPU (Cycles CPU, geometry scripts, exports) | all cores | 1-8 GB | CPU | 1 job using all cores, or several with `-t N` adding up to the cores | No |
| Blender / Cycles GPU renders, Unity/Unreal render captures | few CPU threads | scene size in VRAM | GPU | 1 per GPU; a 2nd if VRAM has room and GPU < 70% busy | n/a: one per GPU, split frames across GPUs and machines |
| AI image generation (FLUX, SD, ComfyUI) and 3D-from-image models | 1-2 CPU threads | 6-24 GB VRAM + 8-16 GB RAM | GPU | 1 per GPU; send batches, not parallel copies | No: one model per GPU |
| Local LLM inference | many | the model's size in VRAM/RAM | GPU | 1 server per GPU; parallel requests inside the server | No |
| Video encoding (ffmpeg) | ffmpeg threads | 0.5-2 GB | CPU or GPU encoder (NVENC) | CPU: 2-3 encodes with `-threads` adding up to the cores; NVENC: 2-3 per GPU | A little |
| Downloads, uploads, API calls, scraping | I/O bound | small | network | many (10-50), limited by the far end's rate rules | Yes: CPU is not the limit |

## Signs you've gone too far

- RAM free under the reserve, or the disk busy at 100% with "paging" or "swap" growing: stop adding, and let some jobs
  finish.
- GPU "out of memory" errors, or renders falling back to the CPU: back off to one job per GPU.
- Work per minute (from `run_record.py`) flat or falling after a raise: undo the raise.
- The machine's fans at full and clocks dropping (laptops especially): one fewer job can be faster overall.
  Leave the laptop maker's power and fan tool running, and plug the laptop in.

## Measuring a machine's speed factor

Run the same job (same inputs, nothing else heavy running) on each machine and time it. Factor = base machine time ÷
other machine time. Real example: a solver setup took 36 s on a desktop (Ryzen 2700X) and 21 s on a laptop (Ryzen AI 7
350), a factor of about 1.7. GPU factors differ per job: a laptop RTX 5060 kept pace with a desktop RTX 5070 Ti on
light scenes but was up to 1.9x slower on heavy ones.
