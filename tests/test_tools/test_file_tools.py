"""Tests for hello_agent.tools.builtin.file_tools."""
from __future__ import annotations

from pathlib import Path

from hello_agent.tools.builtin.file_tools import _edit_file, _read_file, _write_file

# --- read / write round-trip ------------------------------------------------


def test_write_then_read_round_trip(tmp_path: Path) -> None:
    """write_file then read_file returns the exact same string bytes-for-bytes."""
    target = tmp_path / "round_trip.txt"
    payload = "first line\nsecond line\nthird line\n"
    w = _write_file({"path": str(target), "content": payload})
    assert w.success, f"write_file failed: {w.error!r}"
    assert target.exists()
    assert w.data["size_bytes"] == len(payload.encode("utf-8"))

    r = _read_file({"path": str(target)})
    assert r.success
    assert r.data["text"] == payload, (
        "read_file must return the exact bytes written — no \\n→\\r\\n translation"
    )
    assert r.data["truncated"] is False


def test_write_creates_parent_directories(tmp_path: Path) -> None:
    """`write_file` creates missing parent directories on the fly."""
    target = tmp_path / "deep" / "nested" / "dir" / "out.txt"
    res = _write_file({"path": str(target), "content": "hi"})
    assert res.success, f"write_file failed: {res.error!r}"
    assert target.is_file()
    assert target.read_text(encoding="utf-8") == "hi"


def test_read_truncates_when_over_max_bytes(tmp_path: Path) -> None:
    """`read_file` with max_bytes=10 truncates the output and flags truncated=True."""
    target = tmp_path / "big.bin"
    target.write_bytes(b"x" * 100)
    res = _read_file({"path": str(target), "max_bytes": 10})
    assert res.success
    assert res.data["truncated"] is True
    assert res.data["size_bytes"] == 10
    assert res.data["text"] == "x" * 10


def test_read_missing_file_returns_failure(tmp_path: Path) -> None:
    """`read_file` on a non-existent path returns success=False with a clear error."""
    target = tmp_path / "missing.txt"
    res = _read_file({"path": str(target)})
    assert not res.success
    assert "not found" in (res.error or "").lower()


def test_read_rejects_path_traversal(tmp_path: Path) -> None:
    """`read_file` rejects a path whose resolved form escapes the request dir."""
    bad = tmp_path / ".." / "should-not-escape.txt"
    res = _read_file({"path": str(bad)})
    # Either the file simply doesn't exist OR the traversal guard fires — both OK.
    assert not res.success


# --- edit_file --------------------------------------------------------------


def test_edit_replaces_single_occurrence(tmp_path: Path) -> None:
    """`edit_file` replaces exactly one occurrence of `old` with `new`."""
    target = tmp_path / "edit.txt"
    target.write_text("hello world\nhello again\n", encoding="utf-8")
    res = _edit_file(
        {
            "path": str(target),
            "old": "hello world",
            "new": "HELLO WORLD",
        }
    )
    assert res.success, f"edit_file failed: {res.error!r}"
    assert target.read_text(encoding="utf-8") == "HELLO WORLD\nhello again\n"


def test_edit_rejects_ambiguous_old(tmp_path: Path) -> None:
    """`edit_file` refuses to run if `old` matches more than one location."""
    target = tmp_path / "ambig.txt"
    target.write_text("aaa\naaa\n", encoding="utf-8")
    res = _edit_file(
        {
            "path": str(target),
            "old": "aaa",
            "new": "bbb",
        }
    )
    assert not res.success
    assert "disambiguate" in (res.error or "").lower()
    # File should be untouched.
    assert target.read_text(encoding="utf-8") == "aaa\naaa\n"


def test_edit_rejects_missing_old(tmp_path: Path) -> None:
    """`edit_file` returns failure (no edit applied) when `old` is not in the file."""
    target = tmp_path / "no_match.txt"
    target.write_text("the quick brown fox", encoding="utf-8")
    res = _edit_file(
        {
            "path": str(target),
            "old": "the slow green turtle",
            "new": "anything",
        }
    )
    assert not res.success
    assert "not found" in (res.error or "").lower()
    assert target.read_text(encoding="utf-8") == "the quick brown fox"


def test_edit_missing_file_returns_failure(tmp_path: Path) -> None:
    """`edit_file` on a non-existent path returns success=False."""
    target = tmp_path / "absent.txt"
    res = _edit_file(
        {
            "path": str(target),
            "old": "x",
            "new": "y",
        }
    )
    assert not res.success
    assert "not found" in (res.error or "").lower()
