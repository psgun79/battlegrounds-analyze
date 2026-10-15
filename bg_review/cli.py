import argparse
from datetime import datetime
import json
import os
from pathlib import Path
import sys
import time
import uuid

from .exporter import markdown
from .compact_review import export_review
from .card_data import catalog_or_unresolved, prepare_catalog, default_cache
from .storage import Journal, Session, Tail, atomic_text


def default_output():
    return Path(os.getenv("LOCALAPPDATA", Path.home())) / "BattlegroundsReview" / "output"


def discover_logs(root=None):
    roots = [Path(root)] if root else [Path(os.getenv("ProgramFiles(x86)", "C:/Program Files (x86)")) / "Hearthstone" / "Logs",
                                       Path(os.getenv("ProgramFiles", "C:/Program Files")) / "Hearthstone" / "Logs"]
    if not root and os.name == "nt":
        import winreg
        for view in (winreg.KEY_WOW64_32KEY, winreg.KEY_WOW64_64KEY):
            try:
                with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\Hearthstone", 0, winreg.KEY_READ | view) as key:
                    roots.append(Path(winreg.QueryValueEx(key, "InstallLocation")[0]) / "Logs")
            except OSError: pass
    files = []
    for folder in roots:
        if folder.is_file(): files.append(folder)
        elif folder.exists(): files.extend(folder.glob("**/Power.log"))
    return sorted(set(files), key=lambda p: (p.parent.name, p.stat().st_mtime_ns))


def read_cards(path):
    if not path: return None
    data = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    return {c["id"]: c for c in data} if isinstance(data, list) else data


def report(session):
    for path in session.paths: print(path.resolve())
    if session.errors: print(f"{session.errors} parser errors; see errors.jsonl", file=sys.stderr)
    if not session.paths: print("No Battlegrounds matches found. Check Power logging and CREATE_GAME presence.", file=sys.stderr)


def metadata_options(args):
    return dict(locale=args.locale,cache=args.card_cache,source=args.card_data,offline=args.offline)


def replay(args):
    s = Session(args.output, args.log, args.date, args.local_player, read_cards(args.cards), args.stream, args.review_mode, metadata_options(args))
    with Path(args.log).open(encoding="utf-8-sig", errors="replace") as f:
        for line in f: s.feed(line)
    s.close(); report(s)
    return 1 if s.errors or not s.paths else 0


def recover(args):
    with Path(args.journal).open(encoding="utf-8") as f:
        header = json.loads(next(f))
        options = header.get("options", {})
        s = Session(args.output, header["source"], options.get("date"), options.get("local_player"),
                    read_cards(args.cards), options.get("stream", "GameState"), args.review_mode, metadata_options(args))
        # Only an interrupted final JSONL row is discardable. Middle corruption is an error.
        for line in f:
            if not line.endswith("\n"):
                print("Ignored interrupted final journal record", file=sys.stderr); break
            s.feed(json.loads(line)["line"])
    s.close(); report(s)
    return 1 if s.errors or not s.paths else 0


def watch(args):
    output = Path(args.output); output.mkdir(parents=True, exist_ok=True)
    # Exclusive OS lock is released even on process death; prevents two watchers writing the same matches.
    lock = (output / "watch.lock").open("a+b")
    lock.seek(0); lock.write(b"0"); lock.flush(); lock.seek(0)
    try:
        if os.name == "nt":
            import msvcrt
            msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        print("A watcher already owns this output directory.", file=sys.stderr); lock.close(); return 2
    cards = read_cards(args.cards)
    stop_file = output / "stop-request"
    if stop_file.exists(): stop_file.unlink()
    current = None; tail = None; session = None; journal = None
    last_save = 0; last_saved_offset = -1; last_scan = 0; candidates = []; stopped = False
    print(f"Watching Power.log (read-only). Output: {output.resolve()}. Ctrl+C stops.", flush=True)
    try:
        while not stopped:
            if stop_file.exists():
                stop_file.unlink(); break
            now = time.monotonic()
            if now - last_scan >= 2:
                candidates = discover_logs(args.log_root)
                last_scan = now
            latest = candidates[-1] if candidates else None
            if latest and latest != current:
                if session: session.close(); report(session)
                if journal: journal.close()
                current = latest; tail = Tail(current); last_saved_offset = -1
                session = Session(output, current, args.date, args.local_player, cards, args.stream, args.review_mode, metadata_options(args))
                journal = Journal(output / f"capture-{uuid.uuid4().hex}.jsonl", current,
                                  date=args.date, local_player=args.local_player, stream=args.stream)
                print(f"Source: {current}", flush=True)
            if tail:
                try:
                    lines, reset = tail.poll()
                    if reset:
                        session.close(); journal.close()
                        session = Session(output, current, args.date, args.local_player, cards, args.stream, args.review_mode, metadata_options(args))
                        journal = Journal(output / f"capture-{uuid.uuid4().hex}.jsonl", current,
                                          date=args.date, local_player=args.local_player, stream=args.stream)
                        print("Log replaced/truncated: started a separate capture.", flush=True)
                    # WAL before reducing: a logger crash can be recovered deterministically.
                    journal.append(lines)
                    for line in lines: session.feed(line)
                    if now - last_save >= args.checkpoint:
                        if tail.offset != last_saved_offset:
                            session.save(); last_saved_offset = tail.offset
                        last_save = now
                        atomic_text(output / "watch-status.json", json.dumps({"pid": os.getpid(), "status": "watching",
                            "source": str(current), "offset": tail.offset, "updatedAt": datetime.now().isoformat(),
                            "matchId": session.match.data["match"]["id"] if session.match else None,
                            "turn": session.match.turn if session.match else None,
                            "parserErrors": session.errors, "output": str(output.resolve())}, ensure_ascii=False))
                except OSError as exc:
                    print(f"Logger I/O failure (game unaffected): {exc}", file=sys.stderr, flush=True)
                    # Do not consume more bytes after a failed write; restart/recover rather than lose data silently.
                    stopped = True
            if args.once: break
            time.sleep(args.poll)
    except KeyboardInterrupt:
        print("Stopping and exporting available data.")
    finally:
        if session: session.close(); report(session)
        if journal: journal.close()
        atomic_text(output / "watch-status.json", json.dumps({"pid": os.getpid(), "status": "stopped", "updatedAt": datetime.now().isoformat()}))
        lock.close()
    return 1 if stopped or (session and session.errors) else 0


def configure(args):
    """Only the standard logging config is edited, with a backup; no game binaries/assets."""
    import configparser
    path = Path(args.config) if args.config else Path(os.getenv("LOCALAPPDATA", Path.home())) / "Blizzard/Hearthstone/log.config"
    config = configparser.ConfigParser(strict=False)
    config.optionxform = str
    old = path.read_text(encoding="utf-8-sig") if path.exists() else ""
    config.read_string(old)
    if not config.has_section("Power"): config.add_section("Power")
    for key, value in {"LogLevel": "1", "FilePrinting": "true", "ConsolePrinting": "false", "ScreenPrinting": "false", "Verbose": "true"}.items():
        config.set("Power", key, value)
    if old:
        backup = path.with_name(f"log.config.{datetime.now():%Y%m%d-%H%M%S}-{uuid.uuid4().hex[:6]}.bak")
        atomic_text(backup, old)
        print(f"Backup: {backup}")
    from io import StringIO
    content = StringIO(); config.write(content, space_around_delimiters=False)
    atomic_text(path, content.getvalue())
    print(f"Configured: {path}. Restart Hearthstone to activate logging.")
    return 0


def doctor(args):
    files = discover_logs(args.log_root)
    print(f"Python: {sys.version.split()[0]} | Output: {Path(args.output).resolve()}")
    print("HDT dependency: none; source stream: GameState.DebugPrintPower")
    for p in files[-5:]: print(f"{p} ({p.stat().st_size:,} bytes)")
    if not files: print("No Power.log found; use configure-logging, restart game, or --log-root.")
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description="Read-only Hearthstone Battlegrounds post-game decision logger")
    sub = parser.add_subparsers(dest="command", required=True)
    def semantic(p):
        p.add_argument('--card-data',help='Versioned card catalog JSON or CardDefs XML/directory')
        p.add_argument('--card-cache',default=str(default_cache()))
        p.add_argument('--locale',default='koKR')
        p.add_argument('--offline',action='store_true',help='Do not download missing exact-build metadata')
    def common(p):
        p.add_argument("--output", default=str(default_output()))
        p.add_argument("--date", help="Client local date YYYY-MM-DD; otherwise inferred from source folder")
        p.add_argument("--local-player", type=int, help="Override PlayerID, never lobby rank")
        p.add_argument("--cards", help="Optional HearthstoneJSON card array (e.g. koKR/cards.json)")
        p.add_argument("--stream", choices=["GameState", "PowerTaskList"], default="GameState")
        p.add_argument("--review-mode", choices=["compact", "debug"], default="compact")
        semantic(p)
    p = sub.add_parser("replay"); p.add_argument("log"); common(p); p.set_defaults(run=replay)
    p = sub.add_parser("recover"); p.add_argument("journal"); p.add_argument("--output", default=str(default_output())); p.add_argument("--cards"); p.set_defaults(run=recover)
    p.add_argument("--review-mode", choices=["compact", "debug"], default="compact")
    semantic(p)
    p = sub.add_parser("watch"); common(p); p.add_argument("--log-root"); p.add_argument("--poll", type=float, default=0.25)
    p.add_argument("--checkpoint", type=float, default=5); p.add_argument("--once", action="store_true", help=argparse.SUPPRESS); p.set_defaults(run=watch)
    p = sub.add_parser("doctor"); p.add_argument("--log-root"); p.add_argument("--output", default=str(default_output())); p.set_defaults(run=doctor)
    p = sub.add_parser("configure-logging"); p.add_argument("--config"); p.set_defaults(run=configure)
    p = sub.add_parser("export"); p.add_argument("json"); p.add_argument("--markdown")
    p.add_argument("--format", choices=["both", "review", "audit"], default="both")
    p.add_argument("--review-mode", choices=["compact", "debug"], default="compact")
    semantic(p)
    def export(args):
        path = Path(args.json); data = json.loads(path.read_text(encoding="utf-8"))
        if data.get("schemaVersion") != 1: raise ValueError("Unsupported schemaVersion")
        if args.markdown and args.format == "both":
            raise ValueError("Use --format review or --format audit with --markdown")
        if args.format in ('both', 'audit'):
            dest = Path(args.markdown) if args.markdown else path.with_suffix('.audit.md')
            atomic_text(dest, markdown(data)); print(dest.resolve())
        if args.format in ('both', 'review'):
            dest = Path(args.markdown) if args.markdown else path.with_suffix('.review.md')
            stem = dest.name.removesuffix('.review.md') if dest.name.endswith('.review.md') else dest.stem
            dictionary_path = dest.with_name(stem + '.dictionary.json')
            options=metadata_options(args);options['fetch']=not options.pop('offline')
            catalog=catalog_or_unresolved(data['match'].get('build'),**options)
            review, dictionary = export_review(data, args.review_mode, dictionary_path.name,catalog)
            atomic_text(dictionary_path, json.dumps(dictionary, ensure_ascii=False, indent=2))
            atomic_text(dest, review); print(dest.resolve()); print(dictionary_path.resolve())
        return 0
    p.set_defaults(run=export)
    p = sub.add_parser('prepare-cards');p.add_argument('--build',required=True);semantic(p)
    def prepare(args):
        if args.offline and not args.card_data:raise ValueError('--offline prepare-cards requires --card-data')
        catalog=prepare_catalog(args.build,args.locale,args.card_cache,args.card_data)
        print(f"Cached {len(catalog['cards'])} cards for build {catalog['build']}, {catalog['locale']}")
        return 0
    p.set_defaults(run=prepare)
    p = sub.add_parser("validate"); p.add_argument("json")
    def validate(args):
        from .validate import validate_document, validate_dictionary
        data = json.loads(Path(args.json).read_text(encoding="utf-8"))
        errors = validate_dictionary(data) if 'dictionaryVersion' in data else validate_document(data)
        for error in errors: print(error, file=sys.stderr)
        if not errors: print("References and event causality validated.")
        return 1 if errors else 0
    p.set_defaults(run=validate)
    args = parser.parse_args(argv)
    if getattr(args, "poll", 1) <= 0 or getattr(args, "checkpoint", 1) <= 0: parser.error("poll/checkpoint must be positive")
    try: return args.run(args)
    except (OSError, ValueError) as exc:
        print(f"Logger failed; game was not modified: {exc}", file=sys.stderr); return 2


if __name__ == "__main__":
    raise SystemExit(main())
