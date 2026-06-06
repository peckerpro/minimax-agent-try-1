"""Tests for hello_agent.rag.loader.

Per ENGINEERING.md §7.2.1:
  - text-native extensions are read directly
  - office / pdf / image go through `document_parser` (MinerU → markitdown → pypdf)
  - 50 MB hard limit per file
  - supported_extensions() reflects config + defaults
"""
from __future__ import annotations

from pathlib import Path

import pytest

from hello_agent.rag.loader import (
    load_directory,
    load_file,
    load_files,
    supported_extensions,
)


class TestLoadFile:
    def test_load_markdown_file(self, tmp_path: Path) -> None:
        p = tmp_path / "note.md"
        p.write_text("# hello\n\nThis is a note.", encoding="utf-8")
        result = load_file(p)
        assert result["source"] == str(p.resolve())
        assert "hello" in result["text"]
        assert result["loader"] == "text"
        assert result["metadata"]["size_bytes"] > 0
        assert result["metadata"]["extension"] == ".md"

    def test_load_python_file(self, tmp_path: Path) -> None:
        p = tmp_path / "script.py"
        p.write_text("def hello():\n    return 42\n", encoding="utf-8")
        result = load_file(p)
        assert "def hello" in result["text"]
        assert result["loader"] == "text"

    def test_load_yaml_file(self, tmp_path: Path) -> None:
        p = tmp_path / "config.yaml"
        p.write_text("key: value\nlist:\n  - a\n  - b\n", encoding="utf-8")
        result = load_file(p)
        assert "key: value" in result["text"]
        assert result["loader"] == "text"

    def test_load_json_file(self, tmp_path: Path) -> None:
        p = tmp_path / "data.json"
        p.write_text('{"name": "hello", "n": 42}', encoding="utf-8")
        result = load_file(p)
        assert '"name"' in result["text"]

    def test_load_csv_file(self, tmp_path: Path) -> None:
        p = tmp_path / "rows.csv"
        p.write_text("a,b,c\n1,2,3\n", encoding="utf-8")
        result = load_file(p)
        assert "a,b,c" in result["text"]

    def test_load_nonexistent_file_raises(self) -> None:
        with pytest.raises(FileNotFoundError):
            load_file("/nonexistent/path/file.md")

    def test_load_directory_raises(self, tmp_path: Path) -> None:
        with pytest.raises(IsADirectoryError):
            load_file(tmp_path)

    def test_load_file_too_large_raises(self, tmp_path: Path, monkeypatch) -> None:
        """51 MB file should be rejected."""
        from hello_agent.rag import loader as loader_mod

        # Don't actually write 51MB — patch the constant.
        monkeypatch.setattr(loader_mod, "_MAX_FILE_BYTES", 100)
        p = tmp_path / "big.md"
        p.write_text("x" * 200, encoding="utf-8")
        with pytest.raises(ValueError, match="too large"):
            load_file(p)

    def test_load_handles_invalid_utf8(self, tmp_path: Path) -> None:
        p = tmp_path / "note.md"
        p.write_bytes(b"valid text \xff\xfe invalid bytes \xc3\x28")
        # Should not raise — we use errors="replace".
        result = load_file(p)
        assert "valid text" in result["text"]


class TestLoadFiles:
    def test_load_files_batch(self, tmp_path: Path) -> None:
        files = []
        for name in ("a.md", "b.py", "c.txt"):
            p = tmp_path / name
            p.write_text(f"content of {name}", encoding="utf-8")
            files.append(p)
        results = load_files(files)
        assert len(results) == 3
        for r in results:
            assert r["loader"] == "text"

    def test_load_files_skips_failures(self, tmp_path: Path) -> None:
        good = tmp_path / "good.md"
        good.write_text("hello", encoding="utf-8")
        results = load_files([good, "/nonexistent/file.md"])
        # Only the good one comes back; the missing one is logged and skipped.
        assert len(results) == 1
        assert results[0]["source"] == str(good.resolve())


class TestLoadDirectory:
    def test_load_directory_non_recursive(self, tmp_path: Path) -> None:
        (tmp_path / "a.md").write_text("a", encoding="utf-8")
        (tmp_path / "b.md").write_text("b", encoding="utf-8")
        sub = tmp_path / "sub"
        sub.mkdir()
        (sub / "c.md").write_text("c", encoding="utf-8")

        results = load_directory(tmp_path, recursive=False)
        sources = {Path(r["source"]).name for r in results}
        assert sources == {"a.md", "b.md"}

    def test_load_directory_recursive(self, tmp_path: Path) -> None:
        (tmp_path / "a.md").write_text("a", encoding="utf-8")
        sub = tmp_path / "sub"
        sub.mkdir()
        (sub / "b.md").write_text("b", encoding="utf-8")
        deeper = sub / "deeper"
        deeper.mkdir()
        (deeper / "c.md").write_text("c", encoding="utf-8")

        results = load_directory(tmp_path, recursive=True)
        names = {Path(r["source"]).name for r in results}
        assert names == {"a.md", "b.md", "c.md"}

    def test_load_directory_filters_by_extension(self, tmp_path: Path) -> None:
        (tmp_path / "keep.md").write_text("keep", encoding="utf-8")
        (tmp_path / "skip.exe").write_text("skip", encoding="utf-8")
        (tmp_path / "also.md").write_text("also", encoding="utf-8")

        results = load_directory(tmp_path, recursive=True, extensions=[".md"])
        names = {Path(r["source"]).name for r in results}
        assert names == {"keep.md", "also.md"}

    def test_load_directory_nonexistent_raises(self) -> None:
        with pytest.raises(FileNotFoundError):
            load_directory("/nonexistent/dir")

    def test_load_directory_on_file_raises(self, tmp_path: Path) -> None:
        f = tmp_path / "x.md"
        f.write_text("hi", encoding="utf-8")
        with pytest.raises(NotADirectoryError):
            load_directory(f)

    def test_load_directory_empty(self, tmp_path: Path) -> None:
        assert load_directory(tmp_path) == []


class TestSupportedExtensions:
    def test_includes_markdown(self) -> None:
        exts = supported_extensions()
        assert ".md" in exts

    def test_includes_python(self) -> None:
        exts = supported_extensions()
        assert ".py" in exts

    def test_includes_pdf(self) -> None:
        exts = supported_extensions()
        assert ".pdf" in exts

    def test_sorted(self) -> None:
        exts = supported_extensions()
        assert exts == sorted(exts)
