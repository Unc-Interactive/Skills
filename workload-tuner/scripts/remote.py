#!/usr/bin/env python3
"""Run jobs on a second computer over SSH (or on this one with HOST "local"), hidden, each with its own log.

Needs: an SSH alias that logs in without a password prompt (key-based), e.g. `ssh laptop` works, and Python 3 on the
remote machine for `stats`. The remote can be Windows (OpenSSH server, cmd shell) or Linux/macOS.

  python remote.py HOST info                      OS, Python command, cores, RAM (checks the link works)
  python remote.py HOST stats [--top N] [--match TEXT]   machine_stats.py on that host (copied there first)
  python remote.py HOST push LOCAL_DIR NAME       copy a folder's files to ~/workload-jobs/NAME on the host (tar over SSH)
  python remote.py HOST start JOB --dir NAME -- COMMAND...   start COMMAND in ~/workload-jobs/NAME, hidden, detached
  python remote.py HOST log JOB [--tail N]         log tail + running/done (and exit code)
  python remote.py HOST wait JOB                   wait until done, print the tail, exit with the job's exit code
  python remote.py HOST get REMOTE_PATH LOCAL      copy one file back (REMOTE_PATH relative to ~/workload-jobs)
  python remote.py HOST jobs                       every job: name|start|end|done/running (for run_record.py)
  python remote.py HOST windows                    Windows hosts: console windows open on the owner's desktop (should be none)

Jobs on Windows start through WMI (Win32_Process Create), so they run in the background session: no window pops up on
the other person's desktop, and the job survives the SSH connection closing. On Linux/macOS they start with setsid nohup.
Logs live in ~/workload-jobs/logs/JOB.txt, with JOB.txt.exit written when the job ends.
"""
import base64, json, os, shlex, subprocess, sys, tarfile, tempfile, io, time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = "workload-jobs"
SSH_OPTS = ["-o", "BatchMode=yes", "-o", "LogLevel=ERROR"]
_cache = {}


def die(msg):
    sys.exit("remote.py: " + msg)


def ssh(host, cmd, inp=None, check=True):
    r = subprocess.run(["ssh"] + SSH_OPTS + [host, cmd], capture_output=True, input=inp)
    out = r.stdout.decode("utf-8", "replace").replace("\r", "")
    if check and r.returncode != 0:
        die("ssh %s failed (%d): %s\n%s" % (host, r.returncode, cmd[:200], r.stderr.decode("utf-8", "replace").strip()))
    return out


def scp(src, dst):
    r = subprocess.run(["scp", "-q"] + SSH_OPTS + [src, dst], capture_output=True)
    if r.returncode != 0:
        die("scp failed: " + r.stderr.decode("utf-8", "replace").strip())


def is_local(host):
    return host in ("local", "localhost", ".")


def remote_os(host):
    if host in _cache:
        return _cache[host]
    if is_local(host):
        _cache[host] = "windows" if os.name == "nt" else "posix"
    else:
        out = ssh(host, "echo %OS%", check=False).strip()
        _cache[host] = "windows" if out == "Windows_NT" else "posix"
    return _cache[host]


def home(host):
    if is_local(host):
        return os.path.expanduser("~")
    if remote_os(host) == "windows":
        return ssh(host, "echo %USERPROFILE%").strip()
    return ssh(host, "echo $HOME").strip()


def jpath(host, *parts):
    sep = "\\" if remote_os(host) == "windows" else "/"
    return sep.join([home(host), ROOT] + list(parts))


def rsh(host, cmd, inp=None, check=True):
    """Run a shell command on the host (cmd.exe on Windows, sh elsewhere)."""
    if is_local(host):
        r = subprocess.run(cmd, shell=True, capture_output=True, input=inp)
        if check and r.returncode != 0:
            die("local command failed: " + cmd[:200])
        return r.stdout.decode("utf-8", "replace").replace("\r", "")
    return ssh(host, cmd, inp, check)


def ps_encoded(script):
    return "powershell -NoProfile -EncodedCommand " + base64.b64encode(script.encode("utf-16-le")).decode()


def python_cmd(host):
    for c in (["py", "-3"], ["python3"], ["python"]):
        out = rsh(host, " ".join(c) + " -c \"import sys;print(sys.version_info[0])\"", check=False).strip()
        if out.endswith("3"):
            return " ".join(c)
    die("no Python 3 found on %s" % host)


def mkdirs(host, *dirs):
    if remote_os(host) == "windows":
        rsh(host, " & ".join('if not exist "%s" mkdir "%s"' % (d, d) for d in dirs), check=False)
    else:
        rsh(host, "mkdir -p " + " ".join(shlex.quote(d) for d in dirs))


def put_file(host, local, remote):
    if is_local(host):
        import shutil
        shutil.copyfile(local, remote)
    else:
        scp(local, "%s:%s" % (host, remote.replace("\\", "/")))


def cmd_info(host):
    py = python_cmd(host)
    d = json.loads(cmd_stats(host, quiet=True))
    print("%s: %s, Python '%s', %d cores / %d threads, RAM free %s of %s GB, GPUs: %s" % (
        host, d["os"], py, d["physical_cores"], d["logical_cores"], d["ram_free_gb"], d["ram_total_gb"],
        ", ".join("%s (%s GB free)" % (g["name"], g["vram_free_gb"]) for g in d["gpus"]) or "none"))


def cmd_stats(host, extra=(), quiet=False):
    if is_local(host):
        out = subprocess.run([sys.executable, os.path.join(HERE, "machine_stats.py"), "--json"] + list(extra),
                             capture_output=True, text=True).stdout
    else:
        mkdirs(host, jpath(host))
        put_file(host, os.path.join(HERE, "machine_stats.py"), jpath(host, "machine_stats.py"))
        out = rsh(host, '%s "%s" --json %s' % (python_cmd(host), jpath(host, "machine_stats.py"), " ".join(extra)))
    if not quiet:
        print(out.strip())
    return out


def cmd_push(host, local_dir, name):
    dest = jpath(host, name)
    mkdirs(host, dest)
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as tar:
        for f in sorted(os.listdir(local_dir)):
            p = os.path.join(local_dir, f)
            if os.path.isfile(p):
                tar.add(p, arcname=f)
    if is_local(host):
        buf.seek(0)
        tarfile.open(fileobj=buf).extractall(dest)
    else:
        rsh(host, 'tar -xf - -C "%s"' % dest.replace("\\", "/"), inp=buf.getvalue())
    print("pushed %s -> %s:%s" % (local_dir, host, dest))


def cmd_start(host, job, workdir, command):
    logs = jpath(host, "logs")
    wd = jpath(host, workdir) if workdir else jpath(host)
    mkdirs(host, logs, wd)
    log = (logs + ("\\" if remote_os(host) == "windows" else "/") + job + ".txt")
    tmpdir = tempfile.mkdtemp()
    if remote_os(host) == "windows":
        lines = ["@echo off", 'cd /d "%s"' % wd, "set PYTHONUTF8=1",
                 '(%s) > "%s" 2>&1' % (command, log), 'echo %%errorlevel%% > "%s.exit"' % log]
        script = os.path.join(tmpdir, job + ".cmd")
        open(script, "w", encoding="ascii", errors="replace", newline="\r\n").write("\n".join(lines) + "\n")
        rbat = logs + "\\" + job + ".cmd"
        rsh(host, 'del /q "%s" "%s.exit" 2>nul & echo.' % (log, log), check=False)
        put_file(host, script, rbat)
        ps = ("$r = Invoke-CimMethod -ClassName Win32_Process -MethodName Create "
              "-Arguments @{CommandLine='cmd /c \"%s\"'}; \"$($r.ProcessId) $($r.ReturnValue)\"" % rbat)
        out = rsh(host, ps_encoded(ps)).split()
        if len(out) < 2 or out[-1] != "0":
            die("start failed: " + " ".join(out))
        print("started %s on %s (pid %s); log %s" % (job, host, out[-2], log))
    else:
        body = "cd %s\n(%s) > %s 2>&1\necho $? > %s.exit\n" % (shlex.quote(wd), command, shlex.quote(log), shlex.quote(log))
        script = os.path.join(tmpdir, job + ".sh")
        open(script, "w", newline="\n").write(body)
        rsh(host, "rm -f %s %s.exit" % (shlex.quote(log), shlex.quote(log)), check=False)
        rsc = logs + "/" + job + ".sh"
        put_file(host, script, rsc)
        rsh(host, "setsid nohup sh %s > /dev/null 2>&1 < /dev/null &" % shlex.quote(rsc))
        print("started %s on %s; log %s" % (job, host, log))


def state(host, job):
    log = jpath(host, "logs", job + ".txt")
    if remote_os(host) == "windows":
        out = rsh(host, '(if exist "%s.exit" (type "%s.exit") else (if exist "%s" (echo running) else (echo none)))' % (log, log, log), check=False).strip()
    else:
        q = shlex.quote(log)
        out = rsh(host, "if [ -f %s.exit ]; then cat %s.exit; elif [ -f %s ]; then echo running; else echo none; fi" % (q, q, q), check=False).strip()
    return out


def tail(host, job, n):
    log = jpath(host, "logs", job + ".txt")
    if remote_os(host) == "windows":
        return rsh(host, ps_encoded("Get-Content -LiteralPath '%s' -Tail %d" % (log, n)), check=False)
    return rsh(host, "tail -n %d %s" % (n, shlex.quote(log)), check=False)


def cmd_log(host, job, n=40):
    st = state(host, job)
    print("STATE " + ("running" if st == "running" else "none" if st == "none" else "done, exit %s" % st))
    print(tail(host, job, n).rstrip())
    return st


def cmd_wait(host, job, n=40):
    while True:
        st = state(host, job)
        if st == "none":
            die("no job named %s on %s" % (job, host))
        if st != "running":
            break
        time.sleep(15)
    cmd_log(host, job, n)
    sys.exit(0 if st.strip() == "0" else 1)


def cmd_get(host, rel, local):
    src = jpath(host, *rel.replace("\\", "/").split("/"))
    if is_local(host):
        import shutil
        shutil.copyfile(src, local)
    else:
        scp("%s:%s" % (host, src.replace("\\", "/")), local)
    print("copied %s:%s -> %s" % (host, src, local))


def cmd_jobs(host):
    logs = jpath(host, "logs")
    if remote_os(host) == "windows":
        ps = ("Get-ChildItem -LiteralPath '%s' -Filter *.txt -EA SilentlyContinue | %% { $c = Get-Item ($_.FullName -replace '\\.txt$','.cmd') -EA SilentlyContinue; "
              "$s = if ($c) { $c.LastWriteTime } else { $_.CreationTime }; $d = Test-Path ($_.FullName + '.exit'); "
              "'{0}|{1:o}|{2:o}|{3}' -f $_.BaseName, $s, $_.LastWriteTime, $(if ($d) {'done'} else {'running'}) }" % logs).replace("%%", "%")
        out = rsh(host, ps_encoded(ps), check=False)
    else:
        q = shlex.quote(logs)
        out = rsh(host, "cd %s 2>/dev/null && for f in *.txt; do [ -f \"$f\" ] || continue; n=${f%%.txt}; "
                        "s=$(date -r \"$n.sh\" -Iseconds 2>/dev/null || date -r \"$f\" -Iseconds); e=$(date -r \"$f\" -Iseconds); "
                        "[ -f \"$f.exit\" ] && st=done || st=running; echo \"$n|$s|$e|$st\"; done" % q, check=False)
    print(out.strip())


def cmd_windows(host):
    if remote_os(host) != "windows":
        print("not a Windows host")
        return
    ps = ("$c = Get-CimInstance Win32_Process | ? { $_.SessionId -gt 0 -and $_.Name -match '^(cmd|powershell|pwsh|python|py|blender|Unity)\\.exe$' }; "
          "if ($c) { $c | %% { '{0} {1} {2}' -f $_.ProcessId, $_.Name, $_.CommandLine } } else { 'no console windows open on the desktop' }").replace("%%", "%")
    print(rsh(host, ps_encoded(ps), check=False).strip())


def main():
    a = sys.argv[1:]
    if len(a) < 2:
        print(__doc__)
        sys.exit(2)
    host, verb, rest = a[0], a[1], a[2:]
    if verb == "info":
        cmd_info(host)
    elif verb == "stats":
        cmd_stats(host, rest)
    elif verb == "push":
        cmd_push(host, rest[0], rest[1])
    elif verb == "start":
        if "--" not in rest:
            die("usage: start JOB [--dir NAME] -- COMMAND")
        i = rest.index("--")
        head, command = rest[:i], " ".join(rest[i + 1:])
        job = head[0]
        workdir = head[head.index("--dir") + 1] if "--dir" in head else ""
        cmd_start(host, job, workdir, command)
    elif verb == "log":
        cmd_log(host, rest[0], int(rest[rest.index("--tail") + 1]) if "--tail" in rest else 40)
    elif verb == "wait":
        cmd_wait(host, rest[0])
    elif verb == "get":
        cmd_get(host, rest[0], rest[1])
    elif verb == "jobs":
        cmd_jobs(host)
    elif verb == "windows":
        cmd_windows(host)
    else:
        die("unknown command " + verb)


if __name__ == "__main__":
    main()
