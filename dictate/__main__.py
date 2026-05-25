from __future__ import annotations

import argparse
import importlib
import importlib.metadata
import platform
import sys


def _dictate_version() -> str:
    try:
        return importlib.metadata.version("dictate")
    except importlib.metadata.PackageNotFoundError:
        return "dev"


def _print_version() -> None:
    mac_version = platform.mac_ver()[0] or "unknown"
    python_version = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
    arch = platform.machine() or "unknown"
    print(f"dictate {_dictate_version()}")
    print(f"Python {python_version} ({arch})")
    print(f"macOS {mac_version}")


def _check_vocab_files(config) -> None:  # noqa: ANN001
    vocab_dir = config.root / "config" / "vocab"
    missing = [
        name for name in ("code.txt", "work.txt", "personal.txt") if not (vocab_dir / name).exists()
    ]
    if missing:
        raise FileNotFoundError(f"missing vocab file(s): {', '.join(missing)}")


def _dry_run() -> int:
    try:
        from dictate.config import load_config

        config = load_config()
        for module in (
            "dictate.commands",
            "dictate.config",
            "dictate.health",
            "dictate.history",
            "dictate.logging_setup",
            "dictate.redact",
            "dictate.vocab",
        ):
            importlib.import_module(module)
        _check_vocab_files(config)
    except Exception as exc:  # noqa: BLE001
        print(f"dictate dry-run: FAILED: {exc}")
        return 1
    print("dictate dry-run: OK")
    return 0


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="dictate")
    parser.add_argument("--version", action="store_true", help="print version information and exit")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="validate config and imports without starting the app",
    )
    subparsers = parser.add_subparsers(dest="command")
    subparsers.add_parser("doctor", help="print diagnostics for support and triage")
    sp_start = subparsers.add_parser("start", help="start dictate in the background")
    sp_start.add_argument(
        "--foreground", action="store_true", help="run in the foreground (do not detach)"
    )
    subparsers.add_parser("stop", help="stop the running dictate instance")
    subparsers.add_parser("restart", help="restart the running dictate instance")
    subparsers.add_parser("status", help="show whether dictate is running")
    sp_web = subparsers.add_parser("web", help="control the local history WebUI")
    web_sub = sp_web.add_subparsers(dest="web_action")
    sp_web_run = web_sub.add_parser("run", help="run the WebUI in the foreground (default)")
    sp_web_run.add_argument("--host", default=None)
    sp_web_run.add_argument("--port", type=int, default=None)
    web_sub.add_parser("open", help="open the running WebUI in your default browser")
    web_sub.add_parser("url", help="print the WebUI URL")
    sp_purge = subparsers.add_parser("purge", help="delete history entries older than N days")
    sp_purge.add_argument("--older-than", type=int, required=True, metavar="DAYS",
                          help="delete entries older than this many days")
    return parser


def _url_args(argv: list[str]) -> list[str]:
    return [arg for arg in argv if arg.startswith("dictate://")]


def run_app(startup_urls: list[str] | None = None) -> None:
    from dictate.app import run_app as _run_app

    _run_app(startup_urls=startup_urls)


def main(argv: list[str] | None = None) -> int:
    raw_argv = list(sys.argv[1:] if argv is None else argv)
    foreground_internal = "--_internal-foreground" in raw_argv
    raw_argv = [a for a in raw_argv if a != "--_internal-foreground"]
    startup_urls = _url_args(raw_argv)
    parser_argv = [arg for arg in raw_argv if arg not in startup_urls]
    parser = _build_parser()
    args = parser.parse_args(parser_argv)
    if args.version:
        _print_version()
        return 0
    if args.dry_run:
        return _dry_run()
    if args.command == "doctor":
        from dictate.doctor import run

        return run()
    if args.command in {"start", "stop", "restart", "status"}:
        from dictate import daemon

        if args.command == "start":
            return daemon.cmd_start(foreground=getattr(args, "foreground", False))
        if args.command == "stop":
            return daemon.cmd_stop()
        if args.command == "restart":
            return daemon.cmd_restart()
        return daemon.cmd_status()
    if args.command == "web":
        from dictate.config import load_config

        cfg = load_config()
        host = getattr(args, "host", None) or cfg.get("webui.host", "127.0.0.1") or "127.0.0.1"
        port = int(getattr(args, "port", None) or cfg.get("webui.port", 47843) or 47843)
        action = getattr(args, "web_action", None) or "run"
        if action == "url":
            print(f"http://{host}:{port}")
            return 0
        if action == "open":
            import subprocess

            subprocess.run(["open", f"http://{host}:{port}"], check=False)
            return 0
        from dictate.webui.server import run as run_web

        run_web(cfg, host=host, port=port)
        return 0

    if args.command == "purge":
        from dictate.config import load_config
        from dictate.history import purge_older_than

        days = int(args.older_than)
        if days <= 0:
            print("purge: --older-than must be > 0", file=sys.stderr)
            return 2
        cfg = load_config()
        deleted = purge_older_than(cfg, days)
        print(f"purged {deleted} entries older than {days} day{'s' if days != 1 else ''}")
        return 0

    if foreground_internal:
        from dictate import daemon

        daemon.write_pid()
        try:
            run_app(startup_urls=startup_urls)
        finally:
            daemon.clear_pid()
        return 0
    run_app(startup_urls=startup_urls)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
