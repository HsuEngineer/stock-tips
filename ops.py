from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
SERVICE_NAME = "stocktips"


def _run(cmd: list[str], *, timeout: int = 120) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd,
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def under_systemd() -> bool:
    """True when this process is managed by our stocktips.service unit."""
    if os.environ.get("INVOCATION_ID"):
        # Set by systemd for all services; confirm unit name when possible.
        try:
            proc = _run(
                ["systemctl", "show", "-p", "Id", "--value", f"{SERVICE_NAME}.service"],
                timeout=5,
            )
            if proc.returncode == 0 and proc.stdout.strip() == f"{SERVICE_NAME}.service":
                # Also check we are that service's MainPID (best-effort).
                pid_proc = _run(
                    [
                        "systemctl",
                        "show",
                        "-p",
                        "MainPID",
                        "--value",
                        f"{SERVICE_NAME}.service",
                    ],
                    timeout=5,
                )
                if pid_proc.returncode == 0:
                    main_pid = (pid_proc.stdout or "").strip()
                    if main_pid and main_pid != "0" and main_pid == str(os.getpid()):
                        return True
        except Exception:
            pass
        # INVOCATION_ID alone is a strong signal we are under systemd.
        return True
    return False


def git_update(remote: str = "origin", branch: str | None = None) -> str:
    """Fetch and hard-reset to remote branch. config.ini is gitignored so it stays."""
    if branch is None:
        proc = _run(["git", "rev-parse", "--abbrev-ref", "HEAD"], timeout=30)
        branch = (proc.stdout or "").strip() if proc.returncode == 0 else "master"
        if not branch or branch == "HEAD":
            branch = "master"

    steps = [
        ["git", "fetch", remote],
        ["git", "reset", "--hard", f"{remote}/{branch}"],
        ["git", "log", "-1", "--oneline"],
        ["git", "status", "-sb"],
    ]
    lines = []
    for cmd in steps:
        proc = _run(cmd)
        out = (proc.stdout or "").strip()
        err = (proc.stderr or "").strip()
        lines.append(f"$ {' '.join(cmd)}")
        if out:
            lines.append(out)
        if err:
            lines.append(err)
        if proc.returncode != 0:
            raise RuntimeError("\n".join(lines))
    return "\n".join(lines)


def restart_process() -> None:
    """
    Restart the bot.

    Prefer `systemctl restart stocktips` when running as the systemd unit
    (passwordless sudo is installed by deploy/install.sh). Fall back to
    replacing the current process with a fresh interpreter (tmux / manual).
    """
    if under_systemd():
        last_err = ""
        for systemctl in ("/bin/systemctl", "/usr/bin/systemctl", "systemctl"):
            proc = _run(["sudo", "-n", systemctl, "restart", SERVICE_NAME], timeout=60)
            if proc.returncode == 0:
                return
            last_err = (proc.stderr or proc.stdout or "").strip()
        raise RuntimeError(
            last_err
            or "systemctl restart failed. Is sudoers installed? See deploy/sudoers-stocktips.example"
        )

    main_py = PROJECT_ROOT / "main.py"
    os.chdir(PROJECT_ROOT)
    os.execv(sys.executable, [sys.executable, str(main_py)])


def reboot_vm() -> None:
    """Reboot the host. Requires passwordless sudo reboot on the VM."""
    proc = _run(["sudo", "-n", "reboot"], timeout=30)
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip()
        raise RuntimeError(
            detail
            or "sudo reboot failed. Allow passwordless reboot via deploy/install.sh "
            "or deploy/sudoers-stocktips.example"
        )
