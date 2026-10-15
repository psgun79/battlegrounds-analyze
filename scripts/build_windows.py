"""Build a portable ZIP from an explicit file list, never from the working tree."""
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import shutil
import struct
import subprocess
import sys
import tempfile
import tomllib
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def build():
    if os.name != "nt" or struct.calcsize("P") != 8 or platform.machine().lower() not in ("amd64", "x86_64"):
        raise SystemExit("Build with 64-bit x86 Python on Windows.")
    version = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]
    sys.path.insert(0, str(ROOT))
    from bg_review import __version__
    if version != __version__:
        raise SystemExit("pyproject.toml and bg_review.__version__ must match.")
    tag = os.environ.get("GITHUB_REF", "")
    if tag.startswith("refs/tags/") and tag != f"refs/tags/v{version}":
        raise SystemExit(f"Release tag must be v{version}.")

    output = ROOT / "release-dist"
    output.mkdir(exist_ok=True)
    build_root = ROOT / "build"
    build_root.mkdir(exist_ok=True)
    # TemporaryDirectory only cleans its unique child within the resolved build root.
    with tempfile.TemporaryDirectory(prefix="windows-", dir=build_root.resolve()) as tmp:
        work = Path(tmp).resolve()
        assert work.is_relative_to(build_root.resolve())
        subprocess.run([
            sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean",
            "--onedir", "--console", "--noupx", "--name", "bg-review",
            "--paths", str(ROOT), "--collect-data", "bg_review",
            "--distpath", str(work / "dist"), "--workpath", str(work / "work"),
            "--specpath", str(work), str(ROOT / "scripts/windows_entry.py"),
        ], cwd=ROOT, check=True)
        bundle = work / "dist/bg-review"
        for name in ("LICENSE", "THIRD_PARTY_NOTICES.md"):
            shutil.copy2(ROOT / name, bundle / name)
        (bundle / "사용안내.txt").write_text(
            (ROOT / "docs/windows-quickstart.txt").read_text(encoding="utf-8"), encoding="utf-8-sig")
        shutil.copy2(ROOT / "docs/review-prompt.md", bundle / "AI-복기-프롬프트.md")
        licenses = bundle / "licenses"
        licenses.mkdir()
        shutil.copy2(Path(sys.base_prefix) / "LICENSE.txt", licenses / "Python-LICENSE.txt")
        distribution = importlib.metadata.distribution("pyinstaller")
        license_files = [p for p in distribution.files if p.name == "COPYING.txt"]
        if not license_files:
            raise RuntimeError("PyInstaller license was not found.")
        shutil.copy2(distribution.locate_file(license_files[0]), licenses / "PyInstaller-COPYING.txt")
        info = {
            "version": version, "platform": "windows-x64", "python": platform.python_version(),
            "pyinstaller": importlib.metadata.version("pyinstaller"),
            "pyinstallerHooks": importlib.metadata.version("pyinstaller-hooks-contrib"),
        }
        (bundle / "build-info.json").write_text(json.dumps(info, indent=2) + "\n", encoding="utf-8")
        name = f"battlegrounds-review-logger-{version}-windows-x64"
        archive = output / f"{name}.zip"
        with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as z:
            for path in sorted(bundle.rglob("*")):
                if path.is_file():
                    z.write(path, Path(name) / path.relative_to(bundle))
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    checksum = archive.with_suffix(".zip.sha256")
    checksum.write_text(f"{digest}  {archive.name}\n", encoding="ascii")
    print(f"Created: {archive}\nSHA256: {digest}")


if __name__ == "__main__":
    build()
