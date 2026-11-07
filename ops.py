from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent


def git_update(remote: str = "origin", branch: str = "master") -> str:
    """Fetch and hard-reset to remote branch. config.ini is gitignored so it stays."""
    steps = [
        ["git", "fetch", remote],
        ["git", "reset", "--hard", f"{remote}/{branch}"],
        ["git", "log", "-1", "--oneline"],
        ["git", "status", "-sb"],
    ]
    lines = []
    for cmd in steps:
        proc = subprocess.run(
            cmd,
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            timeout=120,
        )
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
    """Replace current process with a fresh python main.py (same venv interpreter)."""
    main_py = PROJECT_ROOT / "main.py"
    os.chdir(PROJECT_ROOT)
    os.execv(sys.executable, [sys.executable, str(main_py)])


def reboot_vm() -> None:
    """Reboot the host. Requires passwordless sudo reboot on the VM."""
    proc = subprocess.run(
        ["sudo", "-n", "reboot"],
        capture_output=True,
        text=True,
        timeout=30,
    )
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip()
        raise RuntimeError(
            detail
            or "sudo reboot failed. Allow passwordless reboot, e.g. "
            "`echo 'ubuntu ALL=NOPASSWD: /sbin/reboot' | sudo tee /etc/sudoers.d/stocktips-reboot`"
        )
