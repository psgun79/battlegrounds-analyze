"""Crash-tolerant output and byte-aware file tailing. Source files are opened read-only."""
from datetime import datetime, timezone, timedelta
import json
import os
from pathlib import Path
import re

from .engine import Match
from .document import review_document
from .exporter import markdown
from .compact_review import export_review
from .card_data import catalog_or_unresolved
from .parser import PowerParser


def atomic_text(path, text):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    with temp.open("w", encoding="utf-8", newline="\n") as f:
        f.write(text)
        f.flush()
        os.fsync(f.fileno())
    os.replace(temp, path)


def source_date(path):
    match = re.search(r"Hearthstone_(\d{4})_(\d{2})_(\d{2})", str(path))
    return "-".join(match.groups()) if match else None


class Session:
    def __init__(self, output, source, date=None, local_player=None, cards=None, stream="GameState", review_mode="compact", metadata_options=None):
        self.output = Path(output)
        self.output.mkdir(parents=True, exist_ok=True)
        self.source = str(source)
        self.date = date or source_date(source)
        self.local_player = local_player
        self.cards = cards
        self.review_mode = review_mode
        self.metadata_options = metadata_options or {}
        self.catalogs = {}
        self.parser = PowerParser(stream)
        self.match = None
        self.paths = []
        self.errors = 0
        self.telemetry = None
        self.last_seconds = None

    def feed(self, line):
        try:
            r = self.parser.parse(line)
            if not r: return
            h, m, seconds = r["time"].split(":")
            clock_seconds = int(h) * 3600 + int(m) * 60 + float(seconds)
            if self.date and self.last_seconds is not None and self.last_seconds - clock_seconds > 12 * 3600:
                self.date = (datetime.fromisoformat(self.date) + timedelta(days=1)).date().isoformat()
            self.last_seconds = clock_seconds
            r["timestamp"] = f"{self.date}T{r['time']}" if self.date else r["time"]
            if r["kind"] == "create_game":
                if self.match:
                    if not self.match.ended: self.match.finish("incomplete")
                    self.save()
                if self.telemetry: self.telemetry.close()
                self.match = Match(r, self.source, self.date, self.local_player, self.cards)
                self.telemetry = (self.output / f"{self.match.data['match']['id']}.events.jsonl").open("w", encoding="utf-8")
            if self.match:
                self.telemetry.write(json.dumps(r, ensure_ascii=False, separators=(",", ":")) + "\n")
                self.match.consume(r)
        except (ValueError, KeyError, TypeError, IndexError, RecursionError) as exc:
            self.errors += 1
            if self.match: self.match.warning(f"Parser error at line {self.parser.line_number}: {type(exc).__name__}: {exc}")
            with (self.output / "errors.jsonl").open("a", encoding="utf-8") as f:
                f.write(json.dumps({"source": self.source, "line": self.parser.line_number, "error": str(exc)}, ensure_ascii=False) + "\n")

    def save(self):
        if not self.match or not self.match.is_bg: return None
        data = review_document(self.match.checkpoint())
        if self.telemetry and not self.telemetry.closed:
            self.telemetry.flush(); os.fsync(self.telemetry.fileno())
        stem = re.sub(r"[^\w.-]", "_", data["match"]["startedAt"]) + "_" + data["match"]["id"]
        path = self.output / f"{stem}.json"
        atomic_text(path, json.dumps(data, ensure_ascii=False, separators=(",", ":")))
        atomic_text(path.with_suffix(".audit.md"), markdown(data))
        dictionary_path = path.with_suffix('.dictionary.json')
        build=data['match'].get('build')
        complete=data['result']['status']=='completed'
        key=(build,complete)
        if key not in self.catalogs:
            options=dict(self.metadata_options)
            offline=options.pop('offline',False)
            options['fetch']=complete and not offline
            self.catalogs[key]=catalog_or_unresolved(build,**options)
        review, dictionary = export_review(data, self.review_mode, dictionary_path.name, self.catalogs[key])
        atomic_text(dictionary_path, json.dumps(dictionary, ensure_ascii=False, indent=2))
        atomic_text(path.with_suffix(".review.md"), review)
        if path not in self.paths: self.paths.append(path)
        return path

    def close(self):
        if self.match and not self.match.ended: self.match.finish("incomplete")
        self.save()
        if self.telemetry: self.telemetry.close()


class Tail:
    """Only returns complete newline-terminated records, even across UTF-8 split reads.

    Detects truncation, replacement and truncate/regrow by rechecking the last read bytes.
    The caller starts a new Session on reset so entities from different games never mix.
    """
    def __init__(self, path):
        self.path = Path(path)
        self.offset = 0
        self.identity = None
        self.pending = b""
        self.anchor = b""
        self.generation = 0

    def poll(self):
        with self.path.open("rb") as f:
            stat = os.fstat(f.fileno())
            identity = (stat.st_dev, stat.st_ino)
            reset = self.identity is not None and (identity != self.identity or stat.st_size < self.offset)
            if self.offset and not reset:
                f.seek(self.offset - len(self.anchor))
                reset = f.read(len(self.anchor)) != self.anchor
            if reset:
                self.offset = 0; self.pending = b""; self.anchor = b""; self.generation += 1
            self.identity = identity
            f.seek(self.offset)
            chunk = f.read(1024 * 1024)
            self.offset += len(chunk)
            if chunk:
                self.anchor = (self.anchor + chunk)[-128:]
            parts = (self.pending + chunk).split(b"\n")
            self.pending = parts.pop()
            return [part.decode("utf-8", errors="replace") + "\n" for part in parts], reset


class Journal:
    def __init__(self, path, source, **options):
        self.file = Path(path).open("x", encoding="utf-8", newline="\n")
        self.file.write(json.dumps({"journalVersion": 1, "source": str(source), "options": options,
                                    "createdAt": datetime.now(timezone.utc).isoformat()}) + "\n")
        self.sync()

    def append(self, lines):
        for line in lines: self.file.write(json.dumps({"line": line}, ensure_ascii=False) + "\n")
        if lines: self.sync()

    def sync(self):
        self.file.flush(); os.fsync(self.file.fileno())

    def close(self):
        self.sync(); self.file.close()
