"""Exercise the delivered ZIP outside the source tree with no Python on PATH."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def smoke(archive):
    archive = archive.resolve()
    expected = archive.with_suffix(".zip.sha256").read_text(encoding="ascii").split()[0]
    assert hashlib.sha256(archive.read_bytes()).hexdigest() == expected, "ZIP checksum mismatch"
    with tempfile.TemporaryDirectory(prefix="bg-review-smoke-") as tmp:
        base = Path(tmp).resolve()
        unpacked = base / "한글 경로 with spaces"
        unpacked.mkdir()
        with zipfile.ZipFile(archive) as z:
            for member in z.namelist():
                assert (unpacked / member).resolve().is_relative_to(unpacked), "Unsafe ZIP path"
            z.extractall(unpacked)
        executables = list(unpacked.glob("*/bg-review.exe"))
        assert len(executables) == 1
        executable = executables[0]
        env = os.environ.copy()
        env["PATH"] = str(Path(os.environ["SYSTEMROOT"]) / "System32")
        env.pop("PYTHONPATH", None)
        env.pop("PYTHONHOME", None)
        env["LOCALAPPDATA"] = str(base / "AppData")
        env["APPDATA"] = str(base / "Roaming")
        env["PYTHONIOENCODING"] = "utf-8"
        env["PYTHONUTF8"] = "1"

        def run(*args, input=None):
            result = subprocess.run([str(executable), *map(str, args)], cwd=base, env=env,
                                    input=input, capture_output=True, text=True,
                                    encoding="utf-8", errors="replace", timeout=60)
            if result.returncode:
                raise RuntimeError(f"{args}: {result.returncode}\n{result.stdout}\n{result.stderr}")
            return result.stdout

        assert "watch" in run("--help")
        version = json.loads((executable.parent / "build-info.json").read_text())["version"]
        menu = run(input="4\nq\n")
        assert version in menu and "전장 복기 로거" in menu
        config = base / "log.config"
        config.write_text("[Existing]\nValue=keep\n", encoding="utf-8")
        run("configure-logging", "--config", config)
        assert "Value=keep" in config.read_text(encoding="utf-8")
        assert list(base.glob("log.config.*.bak"))
        output = base / "output"
        fixture = ROOT / "tests/fixtures/sample.Power.log"
        run("replay", fixture, "--date", "2026-09-14", "--output", output, "--offline")
        reviews = list(output.glob("*.review.md"))
        assert len(reviews) == 1
        match = reviews[0].with_name(reviews[0].name.removesuffix(".review.md") + ".json")
        data = json.loads(match.read_text(encoding="utf-8"))
        assert data["result"]["status"] == "completed"
        assert data["result"]["placement"] == 7
        run("validate", match)
        run("validate", next(output.glob("*.dictionary.json")))
        run("export", match, "--offline")
        watched = base / "watched"
        run("watch", "--log-root", fixture, "--output", watched, "--once", "--offline", "--date", "2026-09-14")
        assert json.loads((watched / "watch-status.json").read_text())["status"] == "stopped"
        assert list(watched.glob("*.review.md"))
        run("recover", next(watched.glob("capture-*.jsonl")), "--output", base / "recovered", "--offline")
        assert list((base / "recovered").glob("*.review.md"))
        assert list(executable.parent.glob("_internal/bg_review/*.json")), "Missing packaged schemas"
    print("PASS: portable menu, config backup, replay, validate, export, watch, recovery; no Python on PATH.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("archive", type=Path)
    smoke(parser.parse_args().archive)
