#!/usr/bin/env python3
"""
Bedrock Playground launcher.

Run from the repo root:
  python start.py
  python start.py --skip-install

Automatically picks one of two modes:

  Single-server (Cloudera AI, or local machine without npm)
  ─────────────────────────────────────────────────────────
  FastAPI serves both the API and the pre-built UI (frontend/dist)
  on one port (CDSW_APP_PORT on CAI, otherwise 5173).

  Dev mode (local machine with npm)
  ─────────────────────────────────
  FastAPI on :8000  +  Vite dev server on :5173
  Vite proxies /api to the backend.
"""

from __future__ import annotations

import argparse
import os
import shutil
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

# ── Paths & ports ─────────────────────────────────────────────────────────────

ROOT = Path(__file__).resolve().parent
BACKEND_DIR = ROOT / "backend"
FRONTEND_DIR = ROOT / "frontend"
VENV_DIR = BACKEND_DIR / "venv"
FRONTEND_DIST = FRONTEND_DIR / "dist"

HOST = "127.0.0.1"
DEV_API_PORT = 8000
APP_PORT = int(os.environ.get("CDSW_APP_PORT", "5173"))
ON_CLOUDERA_AI = "CDSW_APP_PORT" in os.environ
# Cloudera workbench sessions and Applications already provide a Python environment.
_CLOUDERA_ENV_MARKERS = (
    "CDSW_APP_PORT",
    "CDSW_PROJECT",
    "CDSW_DOMAIN",
    "CDSW_PUBLIC_URL",
)


# ── Logging ───────────────────────────────────────────────────────────────────


def log(message: str) -> None:
    """Print a timestamped-style status line to stdout."""
    print(f"[start] {message}", flush=True)


# ── Environment detection ─────────────────────────────────────────────────────


def use_platform_python() -> bool:
    """
    True on Cloudera AI / CDSW: use the session's Python, not backend/venv.

    Set BEDROCK_PLAYGROUND_USE_VENV=1 to force a local-style venv (mainly for testing).
    """
    force_venv = os.environ.get("BEDROCK_PLAYGROUND_USE_VENV", "").lower()
    if force_venv in ("1", "true", "yes"):
        return False
    return any(marker in os.environ for marker in _CLOUDERA_ENV_MARKERS)


def venv_python() -> Path:
    """Return the path to the Python executable inside backend/venv."""
    name = "Scripts/python.exe" if os.name == "nt" else "bin/python"
    return VENV_DIR / name


def runtime_python() -> Path:
    """Interpreter used to run uvicorn (platform Python on CAI, else backend/venv)."""
    if use_platform_python():
        return Path(sys.executable)
    return ensure_venv()


def has_npm() -> bool:
    """True when the npm CLI is available on PATH."""
    return shutil.which("npm") is not None


def has_built_frontend() -> bool:
    """True when frontend/dist/index.html exists (committed production build)."""
    return (FRONTEND_DIST / "index.html").exists()


def use_single_server() -> bool:
    """
    True when one FastAPI process should serve API + static UI.

    Used on Cloudera AI (no npm) or locally when npm is missing but dist exists.
    """
    return ON_CLOUDERA_AI or (not has_npm() and has_built_frontend())


# ── Dependency installation ───────────────────────────────────────────────────


def pip_env() -> dict[str, str]:
    """
    Build a subprocess environment for pip.

    On local venv installs, CAI's PIP_USER=1 can break the venv; force PIP_USER=0.
    On CAI we install into the platform environment and leave PIP_USER unchanged.
    """
    env = os.environ.copy()
    if use_platform_python():
        return env
    for key in ("PIP_USER", "PIP_USER_SITE"):
        env.pop(key, None)
    env["PIP_USER"] = "0"
    env["PYTHONNOUSERSITE"] = "1"
    return env


def run_checked(cmd: list[str], cwd: Path) -> None:
    """Run a shell command; raise CalledProcessError on non-zero exit."""
    log("$ " + " ".join(cmd))
    subprocess.run(cmd, cwd=cwd, check=True, env=pip_env())


def venv_pip_ok(python: Path) -> bool:
    """True when the venv's pip module runs (not a partial/corrupt install)."""
    result = subprocess.run(
        [str(python), "-m", "pip", "--version"],
        cwd=BACKEND_DIR,
        env=pip_env(),
        capture_output=True,
        text=True,
    )
    return result.returncode == 0


def remove_venv() -> None:
    """Delete backend/venv so the next ensure_venv() creates a clean environment."""
    if VENV_DIR.exists():
        log("removing broken backend/venv")
        shutil.rmtree(VENV_DIR)


def bootstrap_pip(python: Path) -> None:
    """Install or repair pip inside the venv using ensurepip."""
    run_checked([str(python), "-m", "ensurepip", "--upgrade"], BACKEND_DIR)


def ensure_venv() -> Path:
    """Create backend/venv if needed and return the venv Python path."""
    python = venv_python()
    if VENV_DIR.exists() and python.exists() and not venv_pip_ok(python):
        remove_venv()
        python = venv_python()

    if not VENV_DIR.exists():
        log("creating backend/venv")
        run_checked([sys.executable, "-m", "venv", str(VENV_DIR)], BACKEND_DIR)
        python = venv_python()

    if not python.exists():
        raise RuntimeError(f"venv python not found at {python}")

    if not venv_pip_ok(python):
        log("bootstrapping pip in backend/venv")
        bootstrap_pip(python)

    if not venv_pip_ok(python):
        remove_venv()
        log("creating backend/venv")
        run_checked([sys.executable, "-m", "venv", str(VENV_DIR)], BACKEND_DIR)
        python = venv_python()
        bootstrap_pip(python)

    if not venv_pip_ok(python):
        raise RuntimeError(
            "pip is not usable in backend/venv. Delete backend/venv manually and retry."
        )

    return python


def install_python(skip: bool) -> Path:
    """Install requirements into the platform env (CAI) or backend/venv (local)."""
    if use_platform_python():
        python = Path(sys.executable)
        if skip:
            log(f"using platform Python ({python})")
            return python
        requirements = ROOT / "requirements.txt"
        log(f"installing Python packages from {requirements.name} into platform environment")
        run_checked([str(python), "-m", "pip", "install", "-r", str(requirements)], ROOT)
        return python

    if skip:
        return ensure_venv()

    python = ensure_venv()
    requirements = ROOT / "requirements.txt"
    log(f"installing Python packages from {requirements.name} into backend/venv")
    try:
        run_checked([str(python), "-m", "pip", "install", "--upgrade", "pip"], BACKEND_DIR)
    except subprocess.CalledProcessError:
        log("pip upgrade failed; recreating backend/venv and retrying")
        remove_venv()
        python = ensure_venv()
        run_checked([str(python), "-m", "pip", "install", "--upgrade", "pip"], BACKEND_DIR)

    run_checked([str(python), "-m", "pip", "install", "-r", str(requirements)], ROOT)
    return python


def install_frontend_dev(skip: bool) -> None:
    """
    Run npm install for local dev mode.

    Skipped when --skip-install is set, or when using the pre-built dist instead.
    """
    if skip:
        return

    if not has_npm():
        if has_built_frontend():
            log("using pre-built frontend/dist (npm not required)")
            return
        raise RuntimeError(
            "npm is not installed and frontend/dist is missing. "
            "Run 'cd frontend && npm install && npm run build' locally, then commit dist."
        )

    if not (FRONTEND_DIR / "node_modules").exists():
        log("installing frontend packages")
        run_checked(["npm", "install"], FRONTEND_DIR)


# ── Process management ────────────────────────────────────────────────────────


def start_process(
    cmd: list[str],
    cwd: Path,
    extra_env: dict[str, str] | None = None,
) -> subprocess.Popen:
    """Start a child process in its own process group (for clean shutdown)."""
    env = os.environ.copy()
    if extra_env:
        env.update(extra_env)
    log("-> " + " ".join(cmd))
    return subprocess.Popen(cmd, cwd=cwd, env=env, start_new_session=True)


def stop_process(proc: subprocess.Popen | None) -> None:
    """Terminate a process group started by start_process()."""
    if proc is None or proc.poll() is not None:
        return
    try:
        os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
        proc.wait(timeout=10)
    except (ProcessLookupError, subprocess.TimeoutExpired):
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        except ProcessLookupError:
            pass


def wait_for_api(port: int, timeout: float = 120) -> None:
    """Poll /api/health until the backend responds or timeout is reached."""
    url = f"http://{HOST}:{port}/api/health"
    deadline = time.time() + timeout
    request = urllib.request.Request(url, headers={"Connection": "close"})

    while time.time() < deadline:
        try:
            with urllib.request.urlopen(request, timeout=5) as response:
                if response.status == 200:
                    log(f"ready at {url}")
                    return
        except (urllib.error.URLError, TimeoutError, OSError):
            time.sleep(0.25)

    raise RuntimeError(f"server did not start within {timeout}s ({url})")


def uvicorn_cmd(python: Path, port: int, reload: bool = False) -> list[str]:
    """Build the uvicorn command for app.main:app."""
    cmd = [
        str(python), "-m", "uvicorn", "app.main:app",
        "--host", HOST, "--port", str(port),
    ]
    if reload:
        cmd.append("--reload")
    return cmd


# ── Run modes ─────────────────────────────────────────────────────────────────


def run_single_server(python: Path) -> subprocess.Popen:
    """
    Cloudera AI / production mode: one FastAPI server on APP_PORT.

    Serves /api/* and the static UI from frontend/dist.
    """
    if not has_built_frontend():
        raise RuntimeError(
            "frontend/dist is missing. Build locally: cd frontend && npm run build"
        )

    log(f"single-server mode — API + UI on port {APP_PORT}")
    proc = start_process(uvicorn_cmd(python, APP_PORT), BACKEND_DIR)
    wait_for_api(APP_PORT)
    log(f"open the Application URL (docs at /docs)")
    return proc


def run_dev_mode(python: Path, skip_install: bool) -> tuple[subprocess.Popen, subprocess.Popen]:
    """
    Local dev mode: FastAPI on :8000 and Vite on APP_PORT.

    Vite proxies /api to the backend via BACKEND_PROXY_TARGET.
    """
    install_frontend_dev(skip_install)
    log(f"dev mode — API :{DEV_API_PORT}, Vite :{APP_PORT}")

    api_proc = start_process(uvicorn_cmd(python, DEV_API_PORT, reload=True), BACKEND_DIR)
    wait_for_api(DEV_API_PORT)

    ui_proc = start_process(
        ["npm", "run", "dev", "--", "--host", HOST, "--port", str(APP_PORT)],
        FRONTEND_DIR,
        extra_env={
            "BACKEND_PROXY_TARGET": f"http://{HOST}:{DEV_API_PORT}",
            "BACKEND_PROXY_PORT": str(DEV_API_PORT),
        },
    )
    log(f"UI http://{HOST}:{APP_PORT}  API http://{HOST}:{DEV_API_PORT}")
    return api_proc, ui_proc


def supervise(api_proc: subprocess.Popen, ui_proc: subprocess.Popen | None) -> None:
    """Keep running until Ctrl+C or a child process exits unexpectedly."""
    log("press Ctrl+C to stop")
    while True:
        if api_proc.poll() is not None:
            raise RuntimeError("server exited unexpectedly")
        if ui_proc and ui_proc.poll() is not None:
            raise RuntimeError("frontend exited unexpectedly")
        time.sleep(0.5)


# ── CLI entry ─────────────────────────────────────────────────────────────────


def parse_args() -> argparse.Namespace:
    """Parse CLI flags; ignore unknown args (e.g. Jupyter kernel flags)."""
    parser = argparse.ArgumentParser(description="Start Bedrock Playground")
    parser.add_argument("--skip-install", action="store_true", help="Skip pip/npm install")
    args, unknown = parser.parse_known_args()
    if unknown:
        log("ignoring extra arguments: " + " ".join(unknown))
    return args


def main() -> int:
    """
    Install dependencies, start servers, and supervise until shutdown.

    Returns 0 on clean exit (Ctrl+C), 1 on error.
    """
    args = parse_args()
    api_proc: subprocess.Popen | None = None
    ui_proc: subprocess.Popen | None = None

    try:
        python = install_python(args.skip_install)

        if use_single_server():
            api_proc = run_single_server(python)
        else:
            api_proc, ui_proc = run_dev_mode(python, args.skip_install)

        supervise(api_proc, ui_proc)

    except KeyboardInterrupt:
        log("stopping...")
        return 0
    except (RuntimeError, subprocess.CalledProcessError) as exc:
        log(f"error: {exc}")
        return 1
    finally:
        stop_process(ui_proc)
        stop_process(api_proc)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
