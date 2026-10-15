import io
import sys

from bg_review.launcher import main


def test_menu_supports_korean_on_western_windows(monkeypatch):
    output = io.BytesIO()
    stdout = io.TextIOWrapper(output, encoding="cp1252")
    stdin = io.TextIOWrapper(io.BytesIO(b"q\n"), encoding="cp1252")
    stderr = io.TextIOWrapper(io.BytesIO(), encoding="cp1252")
    monkeypatch.setattr(sys, "stdout", stdout)
    monkeypatch.setattr(sys, "stdin", stdin)
    monkeypatch.setattr(sys, "stderr", stderr)
    assert main([]) == 0
    stdout.flush()
    assert "전장 복기 로거" in output.getvalue().decode("utf-8")
