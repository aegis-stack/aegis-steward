"""Windows-friendly developer commands with no bash-only shell logic.

Both the Makefile and the ``uv run poe`` tasks call into this module, so
there is exactly one implementation of anything that used to need bash (the
``serve``/``serve-bg`` port-resolution + ``eval`` dance, ``serve-prod``'s
env-file ternary, ``migrate-reset``'s confirmation prompt).
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import platform
import shutil
import signal
import subprocess
import sys

from dotenv import dotenv_values

from scripts.resolve_ports import docs_port, resolve_ports

_COMPOSE_DEV = [
    "docker",
    "compose",
    "-f",
    "docker-compose.yml",
    "-f",
    "docker-compose.dev.yml",
]
_COMPOSE_PROD = [
    "docker",
    "compose",
    "-f",
    "docker-compose.yml",
    "-f",
    "docker-compose.prod.yml",
]

# The project's .env, which compose also reads for its own variables.
_DOTENV = Path(".env")


def _env_file() -> Path:
    """The containers' env file, found the way compose finds it
    (``${AEGIS_STACK_ENV_FILE:-.env}``): the shell's variable, else the one
    ``.env`` names, else ``.env`` itself. A shell variable set but empty
    still wins over ``.env``, and ``:-`` reads it as ``.env``."""
    named = os.environ.get("AEGIS_STACK_ENV_FILE")
    if named is None and _DOTENV.exists():
        named = dotenv_values(_DOTENV).get("AEGIS_STACK_ENV_FILE")
    return Path(named) if named else _DOTENV


# Kokoro-FastAPI runs on the host, on its GPU (a Mac's, which Docker cannot
# reach), and compose starts containers only: serve starts it with make
# kokoro's command and keeps its pid here; stop stops it.
_SPEECH_PID = Path(".kokoro.pid")
_SPEECH_LOG = Path(".kokoro.log")


def _env_value(key: str) -> str | None:
    """One variable of the containers' env file (``_env_file``)."""
    env_file = _env_file()
    return dotenv_values(env_file).get(key) if env_file.exists() else None


def _speech_checkout() -> bool:
    """A Kokoro-FastAPI checkout at SPEECH_SERVER_DIR, or its default, as
    ``inference kokoro`` finds it."""
    from app.core.speech_settings import SpeechServerSettings

    named = _env_value("SPEECH_SERVER_DIR") or (
        SpeechServerSettings.model_fields["SPEECH_SERVER_DIR"].default
    )
    return Path(named).expanduser().is_dir()


def _speech_running() -> bool:
    """The Kokoro-FastAPI an earlier serve started (``serve-bg``) is still up."""
    try:
        os.kill(int(_SPEECH_PID.read_text()), 0)
    except (FileNotFoundError, ValueError, ProcessLookupError):
        return False
    except PermissionError:
        return True  # alive, as someone else
    return True


def _start_speech() -> None:
    """Kokoro-FastAPI in its own process group, logging to ``.kokoro.log``:
    Ctrl-C on serve reaches compose, and serve stops it after. One already
    up is kept: a second could not bind its port, and its pid would hide
    the first from stop."""
    if not _speech_checkout() or _speech_running():
        return
    with _SPEECH_LOG.open("ab") as log:
        started = subprocess.Popen(
            ["uv", "run", "aegis-steward", "inference", "kokoro"],
            stdout=log,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
    _SPEECH_PID.write_text(str(started.pid))
    print(f"Kokoro-FastAPI started on the host (log: {_SPEECH_LOG})")


def _signal_group(pid: int) -> None:
    """Its start script and the server it runs; Windows has no groups."""
    try:
        if hasattr(os, "killpg"):
            os.killpg(pid, signal.SIGTERM)
        else:
            os.kill(pid, signal.SIGTERM)
    except (ProcessLookupError, PermissionError):
        pass  # already gone


def _stop_speech() -> None:
    if _SPEECH_PID.exists():
        _signal_group(int(_SPEECH_PID.read_text()))
        _SPEECH_PID.unlink()


def _plaid_configured() -> bool:
    """The tunnel carries only Plaid's webhook, so it starts only with Plaid."""
    return bool(_env_value("PLAID_CLIENT_ID"))


def _aegis_checkout() -> str | None:
    """The aegis-stack checkout this stack was generated from (``aegis init
    --dev``), from ``.copier-answers.yml``; None for a released aegis. The
    agent runs it: the pinned release may predate what its templates use."""
    answers = Path(".copier-answers.yml")
    lines = answers.read_text().splitlines() if answers.is_file() else []
    source = next(
        (x.partition(":")[2].strip() for x in lines if x.startswith("_src_path:")), ""
    )
    folder = Path(source.removeprefix("git+file://"))
    if source.startswith("git+file://") and (folder / "pyproject.toml").is_file():
        return str(folder)
    return None


def _deploy_agent_ready(env: dict[str, str]) -> None:
    """What the ``deploy-agent`` service takes from this machine: the
    checkout at its own path (``AEGIS_PROJECT_ROOT``), ``known_hosts``
    (made, as Docker would mount a missing one as a directory), and the
    ssh-agent holding a key, as the key itself never enters the container
    (added once per login; ssh-add asks for its passphrase if it has one)."""
    if os.name != "nt":  # a Windows path is no container path
        env["AEGIS_PROJECT_ROOT"] = str(Path.cwd())
        checkout = _aegis_checkout()
        if checkout and "AEGIS_STACK_SOURCE" not in env:
            env["AEGIS_STACK_SOURCE"] = checkout
    known = Path.home() / ".ssh" / "known_hosts"
    known.parent.mkdir(mode=0o700, exist_ok=True)
    known.touch()
    if shutil.which("ssh-add") is None:
        return
    held = subprocess.run(["ssh-add", "-l"], capture_output=True, env=env)
    if held.returncode == 1:  # an agent, holding no key
        keychain = ["--apple-use-keychain"] if sys.platform == "darwin" else []
        subprocess.run(["ssh-add", *keychain], env=env)


def _host_os() -> tuple[str, str]:
    """This machine's OS and its home page (for its mark), which the
    containers cannot see: they run Linux whatever runs Docker. Omarchy
    keeps Arch's os-release, so its own directory names it."""
    if sys.platform == "darwin":
        return "macOS", "https://apple.com"
    if sys.platform == "win32":
        return "Windows", "https://microsoft.com"
    if (Path.home() / ".local/share/omarchy").is_dir():
        return "Omarchy", "https://omarchy.org"
    try:
        release = platform.freedesktop_os_release()
    except OSError:
        return "Linux", "https://kernel.org"
    return release.get("NAME", "Linux"), release.get("HOME_URL", "https://kernel.org")


def serve(*, detach: bool = False) -> None:
    print(
        "Starting services in background..."
        if detach
        else "Starting services... (Press Ctrl+C to stop)"
    )
    ports = resolve_ports(
        ingress=True,
        postgres=False,
        redis=True,
        ollama=False,
        browser=False,
        storage=False,
        hearing=True,
    )
    env = {**os.environ, **{key: str(value) for key, value in ports.items()}}
    # `make serve ENGINE=granian LOOP=rloop`: make exports command-line
    # variables, so each short name arrives here and becomes the setting
    # the app reads.
    for flag, setting in (("ENGINE", "WEBSERVER_ENGINE"), ("LOOP", "WEBSERVER_LOOP")):
        if value := os.environ.get(flag):
            env[setting] = value
    profiles = ["--profile", "dev"]
    if _plaid_configured():
        profiles += ["--profile", "plaid"]
    cmd = [*_COMPOSE_DEV, *profiles, "up", "--remove-orphans"]
    if detach:
        cmd.append("-d")
    env["HOST_OS"], env["HOST_OS_URL"] = _host_os()
    _deploy_agent_ready(env)
    _start_speech()
    try:
        subprocess.run(cmd, env=env, check=True)
    finally:
        if not detach:
            _stop_speech()


def stop() -> None:
    print("Stopping services...")
    _stop_speech()
    subprocess.run(
        [*_COMPOSE_DEV, "--profile", "dev", "down", "--remove-orphans"], check=True
    )


def serve_bg() -> None:
    serve(detach=True)


def serve_prod() -> None:
    env_file = ".env.deploy" if Path(".env.deploy").exists() else ".env"
    print(f"Starting services (production profile), reading {env_file}...")
    print(
        "Set APP_ENV=production and a real SECRET_KEY there before booting outside dev."
    )
    env = {**os.environ, "AEGIS_STACK_ENV_FILE": env_file}
    subprocess.run([*_COMPOSE_PROD, "build", "webserver"], env=env, check=True)
    subprocess.run(
        [*_COMPOSE_PROD, "--profile", "prod", "up", "--remove-orphans"],
        env=env,
        check=True,
    )


def docs() -> None:
    """Serve the documentation on a port that is actually free."""
    port = docs_port()
    subprocess.run(
        ["uv", "run", "mkdocs", "serve", "--dev-addr", f"127.0.0.1:{port}"],
        check=True,
    )


def clean_cache() -> None:
    """Remove __pycache__ dirs and .pyc files (cross-platform, no find/rm)."""
    root = Path(".")
    for pycache in root.rglob("__pycache__"):
        shutil.rmtree(pycache, ignore_errors=True)
    for pyc in root.rglob("*.pyc"):
        pyc.unlink(missing_ok=True)


def status() -> None:
    print("Current system status:")
    print()
    print("Docker containers:")
    try:
        subprocess.run(["docker", "compose", "ps"], check=True)
    except FileNotFoundError:
        print("Docker not installed (or not on PATH)")
    except subprocess.CalledProcessError:
        print("No containers running")
    print()
    print("Dependencies:")
    try:
        result = subprocess.run(
            ["uv", "pip", "list"], check=True, capture_output=True, text=True
        )
        print("\n".join(result.stdout.splitlines()[:20]))
    except FileNotFoundError:
        print("uv not installed (or not on PATH)")
    except subprocess.CalledProcessError:
        print("Dependencies not installed")


def migrate_reset() -> None:
    print("WARNING: This will destroy all data in the database!")
    try:
        answer = input("Are you sure? Type 'yes' to continue: ")
    except EOFError:
        answer = ""
    if answer != "yes":
        sys.exit(1)
    subprocess.run(
        [
            "docker",
            "compose",
            "exec",
            "webserver",
            "uv",
            "run",
            "alembic",
            "-c",
            "alembic/alembic.ini",
            "downgrade",
            "base",
        ],
        check=True,
    )
    subprocess.run(
        [
            "docker",
            "compose",
            "exec",
            "webserver",
            "uv",
            "run",
            "alembic",
            "-c",
            "alembic/alembic.ini",
            "upgrade",
            "head",
        ],
        check=True,
    )
    print("Database reset complete")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "action",
        choices=[
            "serve",
            "serve-bg",
            "serve-prod",
            "stop",
            "docs",
            "migrate-reset",
        ],
    )
    args = parser.parse_args(argv)

    try:
        if args.action == "serve":
            serve()
        elif args.action == "serve-bg":
            serve_bg()
        elif args.action == "serve-prod":
            serve_prod()
        elif args.action == "stop":
            stop()
        elif args.action == "docs":
            docs()
        else:
            migrate_reset()
    except subprocess.CalledProcessError as exc:
        sys.exit(exc.returncode)


if __name__ == "__main__":
    main()
