# Setting up a second PC for jobs (one time, about 15 minutes)

You need: both PCs on the same network, an account on the second PC, and Python 3 on both. The user does the
installs and settings on the second PC themselves, or approves each step. Never type passwords for them.

## 1. Turn on the SSH server on the second PC

- **Windows 10/11:** open Settings, then System, then Optional features, then Add a feature, and pick **OpenSSH Server**. Then, in
  PowerShell as administrator: `Start-Service sshd; Set-Service sshd -StartupType Automatic`.
- **Linux:** `sudo apt install openssh-server` (or the distro's equivalent); it starts by itself.
- **macOS:** System Settings, then General, then Sharing, then turn on **Remote Login**.

## 2. Key login from the main PC (no password prompts)

On the main PC:

```
ssh-keygen -t ed25519            # press Enter for the defaults (skip if ~/.ssh/id_ed25519 already exists)
```

Copy the contents of `~/.ssh/id_ed25519.pub` into the second PC's authorized keys:

- **Windows second PC, normal user:** `C:\Users\<name>\.ssh\authorized_keys`.
- **Windows second PC, administrator account:** `C:\ProgramData\ssh\administrators_authorized_keys`. That file must
  be readable only by Administrators and SYSTEM:
  `icacls C:\ProgramData\ssh\administrators_authorized_keys /inheritance:r /grant "Administrators:F" /grant "SYSTEM:F"`
- **Linux/macOS second PC:** `ssh-copy-id <user>@<second-pc>` does it.

## 3. Give it a short name

Add this to `~/.ssh/config` on the main PC:

```
Host laptop
    HostName 192.168.1.50      # the second PC's address, or its network name
    User <name>
```

Then `ssh laptop echo ok` should print `ok` without asking for a password.

## 4. Check it from the skill

```
python scripts/remote.py laptop info
```

It should print the OS, the Python command, cores, RAM and GPUs. If Python is missing there, install Python 3 on the
second PC (Windows: from python.org, with "Add to PATH" ticked).

## 5. Make room on the second PC

- Plug it in, and set the power mode to "Best performance" (the user's own setting).
- Close the chat apps, game launchers and overlays the batch doesn't need. Ask first. On Windows, stop the ones that
  don't need to start at login in Task Manager, then Startup apps.
- Libraries the jobs need (numpy, scipy and so on) must be installed on the second PC too. Ask first, and match the
  versions on the main PC.
- A restart after several days of uptime often frees a few GB of RAM. Do it between batches.
