# Workload-Tuner

A Claude skill that spreads local AI work across more than one PC and keeps tuning how many jobs each machine runs, so no machine sits idle or runs out of memory.

## Results

Measured in 10-minute slices as work per minute, in desktop-minutes. One laptop run counts as about 1.7 desktop-minutes.

| Setup | Desktop runs | Laptop runs | Work per minute |
|---|---|---|---|
| Without Workload-Tuner (desktop only) | 1–3 | none | 1–3 |
| Start: 1 desktop + 2 laptop runs per critic | 0.7 | 2.3 | 4.6 |
| Critics warmed up | 3.0 | 3.4 | 8.8 |
| Desktop limit raised to 2, laptop memory freed | 3.2 | 4.8 | 11.4 |
| Dip: long laptop runs finished | 3.4 | 2.4 | 7.5 |
| Limits raised to 3 per PC, laptop to 4 | 3.0 | 5.4 | **12.2** |

**12.2 vs 3: 4.1× the best result without the skill.** The laptop now does about 75% of the work.

Note: the baseline ran on the desktop alone, so the gain comes from the skill and the second machine together.

## Hardware tested

| Machine | CPU | GPU |
|---|---|---|
| Desktop | AMD Ryzen 7 2700X | NVIDIA RTX 5070 Ti 16GB |
| Laptop | AMD Ryzen AI 7 350 | NVIDIA RTX 5060 Laptop |

## What it does

- Uses every connected machine as a worker, not just the main PC
- Sets a limit on parallel runs per machine and raises it while there's headroom
- Frees memory on machines that are running short before adding more work
- Watches throughput in 10-minute slices, so a drop shows up quickly and the cause can be checked

## Install

### Claude Code

Clone this repository or download the source, then copy the `workload-tuner` folder (the one that contains `SKILL.md`) into a skills directory:

- All your projects: `~/.claude/skills/workload-tuner/`
- One project: `.claude/skills/workload-tuner/` inside that project

Claude Code picks the skill up when a task matches the description in `SKILL.md`.

That layout is the one in Claude Code's docs: a personal skill is `~/.claude/skills/<name>/SKILL.md`, and a project skill is `.claude/skills/<name>/SKILL.md` ([Extend Claude with skills](https://code.claude.com/docs/en/skills)).

### Claude apps (claude.ai and the desktop app)

1. Download [workload-tuner.skill](../releases/workload-tuner.skill), or zip the `workload-tuner` folder so the zip contains `SKILL.md`.
2. Open **Customize > Skills** and upload the file. Enable the skill there.

**Customize > Skills** is the upload location in Anthropic's help center for Free, Pro, Max, Ultra, and Team plans, and for personal skills on Enterprise ([Use skills in Claude](https://support.claude.com/en/articles/12512180-use-skills-in-claude), [How to create custom skills](https://support.claude.com/en/articles/12512198-how-to-create-custom-skills)). On Team and Enterprise plans, an owner also turns on **Cloud code execution and file creation** and **Skills** under **Organization settings > Plugins & skills**, on the Policy tab. An organization-wide upload uses that same settings page: Add, then Upload a skill, and the file is a `.zip` that contains `SKILL.md` ([Provision and manage skills for your organization](https://support.claude.com/en/articles/13119606-provision-and-manage-skills-for-your-organization)). `workload-tuner.skill` is that zip. If the file picker only lists `.zip` names, rename the download to `workload-tuner.zip`.

The scripts and the SSH steps need an agent that can run commands on your own PCs, so Claude Code is the main fit.

## Requirements

- Python 3 on each machine. The scripts use the Python 3 standard library only, so there is nothing else to install for the skill itself. On Windows, run them with `py -3`. Elsewhere, use `python3`.
- Two or more PCs when you want the work spread out. One machine still runs: the skill sizes jobs and refills slots on the PC you are on, and a second PC is optional. To use another PC, put both machines on the same network, have an account on the second PC, and set up SSH key login with no password prompt, once, as in [references/second-pc-setup.md](references/second-pc-setup.md). That guide covers the OpenSSH Server on Windows, OpenSSH on Linux, and Remote Login on macOS.
- NVIDIA GPU stats are optional. They are read with `nvidia-smi` when that command is installed. Cores, CPU use, and RAM are reported either way.

## Configuration

There is no settings file. Each batch uses the live numbers from the machines and the choices below.

| Setting | What it controls | Example |
|---|---|---|
| Machines | Which PCs take work. This PC is `local`. Any other name is an SSH host from the setup guide. | `local`, `laptop` |
| Max runs per machine | Upper limit on parallel jobs. Start near half of what `plan_slots.py` prints, then raise it while there is headroom. Start another job on a PC only when that PC still has at least 2 GB of RAM free. | 3 (desktop), 4 (laptop) |
| Job shape | Threads one job keeps busy, and its peak RAM. For a GPU job, include peak VRAM. Measure one run first and use the biggest number you see. | `--threads 1 --ram 1.5` |
| Free memory reserve | RAM left unused on each machine, and VRAM left unused on each GPU | 2 GB RAM, about 1.5–2 GB VRAM |
| Speed factor | How many minutes on the base machine one minute on another PC is worth. Time the same job on each machine and divide. | `laptop=1.7` |
| Check interval | How often the load is read again and empty slots are refilled | every 10–15 minutes |

## License

MIT. Copyright (c) 2026 Unc Interactive.

The full text is [LICENSE](../LICENSE) at the root of this repository.
