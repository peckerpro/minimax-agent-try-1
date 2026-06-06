"""Smoke test for the hello_agent.context + hello_agent.memory layers.

Exercises the public surface of §6.5 + §6.6 end-to-end without spinning up
the LLM or any agent loop:

  1. `TokenCounter` — count a mocked message list, and a heuristic-only
     counter for the chars/4 fallback path.
  2. `HistoryManager` sliding window — push 60 messages, assert len == 50
     (the Day-4 spec).
  3. `ObservationTruncator.head_tail` — truncate a 1000-line string and
     verify the marker is present + the line count is reduced.
  4. `ContextBuilder` end-to-end — with all features disabled in config,
     just system + history.
  5. `LongTermMemory` SQLite round-trip — set/get a fact on a tmp db.
  6. `EpisodicMemory` SQLite round-trip — record + list an episode.

Run from the worktree root:
    uv run python scripts/smoke_context.py

Exit codes:
  0   every section passed
  1   a section reported a hard failure
  2   an unexpected exception escaped
"""
from __future__ import annotations

import os
import sys
import tempfile
import traceback
from pathlib import Path

# --- section helpers --------------------------------------------------------


class SmokeError(AssertionError):
    """A section reported a hard failure."""


def _section(title: str) -> None:
    print(f"\n=== {title} ===")


def _ok(msg: str) -> None:
    print(f"  [ok] {msg}")


def _info(msg: str) -> None:
    print(f"  [..] {msg}")


# --- section 1: TokenCounter ------------------------------------------------


def smoke_token_counter() -> None:
    _section("1. TokenCounter")
    from hello_agent.context.token_counter import TokenCounter, count_tokens
    from hello_agent.core.types import Message, Role

    # 1a. Default counter (uses tiktoken if available, else heuristic).
    counter = TokenCounter(model="gpt-4o-mini")
    msgs = [
        Message(role=Role.SYSTEM, content="you are a helpful assistant"),
        Message(role=Role.USER, content="hello world"),
        Message(role=Role.ASSISTANT, content="hi there"),
    ]
    n = counter.count(msgs)
    assert n > 0, f"expected positive token count, got {n}"
    _ok(f"TokenCounter.count(3 messages) = {n} tokens (model={counter.model})")

    n_text = counter.count_text("hello world")
    assert n_text >= 1
    _ok(f"TokenCounter.count_text('hello world') = {n_text} tokens")

    # 1b. Heuristic-only counter (use_tiktoken=False). char/4 path.
    heuristic = TokenCounter(use_tiktoken=False)
    assert heuristic.using_heuristic is True
    text = "a" * 40  # 40 chars → 10 tokens at chars/4
    assert heuristic.count_text(text) == 10
    _ok(f"TokenCounter(use_tiktoken=False).count_text('a' * 40) = {heuristic.count_text(text)}")

    # 1c. Module-level convenience.
    n_module = count_tokens(msgs, model="gpt-4o-mini")
    assert n_module == n
    _ok(f"module-level count_tokens(msgs) == {n_module} (matches class)")


# --- section 2: HistoryManager sliding window --------------------------------


def smoke_history_window() -> None:
    _section("2. HistoryManager sliding window (60 → 50)")
    from hello_agent.context.history import HistoryManager
    from hello_agent.core.types import Message, Role

    # 2a. Default HistoryManager honors the Day-4 cap of 50.
    hm = HistoryManager()
    assert hm.max_messages == 50, f"expected 50, got {hm.max_messages}"
    _ok(f"HistoryManager().max_messages = {hm.max_messages} (config-derived default)")

    # 2b. Push 60 messages → length must clamp to 50.
    for i in range(60):
        hm.append(Message(role=Role.USER, content=f"m{i}"))
    assert len(hm) == 50, f"expected 50 after pushing 60, got {len(hm)}"
    _ok(f"after pushing 60 messages, len(history) = {len(hm)} (cap enforced)")

    # 2c. The oldest messages are the ones that fell off.
    first = hm.to_list()[0]
    assert first.content == "m10", f"expected first message m10, got {first.content!r}"
    last = hm.to_list()[-1]
    assert last.content == "m59"
    _ok(f"window contents: [{first.content!r} ... {last.content!r}]")

    # 2d. System message at index 0 is preserved across appends.
    hm2 = HistoryManager(max_messages=5)
    hm2.set_system("you are brief")
    for i in range(10):
        hm2.append(Message(role=Role.USER, content=f"u{i}"))
    assert hm2.system_message() is not None
    assert hm2.system_message().content == "you are brief"
    _ok("system message survives sliding-window eviction")

    # 2e. Compressed messages are not evicted.
    hm3 = HistoryManager(max_messages=3)
    hm3.set_system("sys")
    hm3.append(Message(role=Role.USER, content="a", compressed=True))
    hm3.append(Message(role=Role.USER, content="b"))
    hm3.append(Message(role=Role.USER, content="c"))
    # Now push more — "a" (compressed) must survive.
    hm3.append(Message(role=Role.USER, content="d"))
    contents = [m.content for m in hm3.to_list()]
    assert "a" in contents, f"compressed message 'a' was evicted: {contents}"
    _ok("compressed messages are not evicted by sliding-window")


# --- section 3: Truncator head_tail ------------------------------------------


def smoke_truncator_head_tail() -> None:
    _section("3. ObservationTruncator.head_tail on a 1000-line string")
    from hello_agent.context.truncator import ObservationTruncator
    from hello_agent.core.types import Message, Role

    # 3a. Build a 1000-line string and truncate with head_lines=10, tail_lines=5.
    body = "\n".join(f"line {i}" for i in range(1000))
    src = Message(role=Role.TOOL, content=body, tool_name="read_file", tool=True)
    trunc = ObservationTruncator(strategy="head_tail", head_lines=10, tail_lines=5)
    out = trunc.truncate(src, max_lines=15)
    assert out is not src, "truncate() must return a new Message"
    assert out.truncated is True, "the new message must have truncated=True"
    _ok("truncate() returns a new Message with truncated=True")

    out_lines = out.content.splitlines() if out.content else []
    # 10 head + 1 marker + 5 tail = 16 logical lines. splitlines() also
    # counts the empty strings around the marker (\n before + \n after),
    # so the actual line count is 10 + 3 (marker + surrounding blanks) + 5 = 18.
    # We just verify head + tail are present and shorter than the input.
    assert len(out_lines) < 1000, f"truncation did not shrink the input: {len(out_lines)}"
    _ok(f"truncated output has {len(out_lines)} lines (was 1000)")

    # The first 10 lines should be the head, the last 5 should be the tail.
    assert out_lines[0] == "line 0"
    assert out_lines[9] == "line 9"
    assert out_lines[-1] == "line 999"
    assert out_lines[-5] == "line 995"
    _ok("head=lines[0..9], tail=lines[-5..-1]")

    # The marker must be present.
    assert any("truncated" in ln for ln in out_lines)
    marker_line = next(ln for ln in out_lines if "truncated" in ln)
    assert "985 lines truncated" in marker_line, marker_line
    _ok(f"marker present: {marker_line.strip()!r}")

    # 3b. No-op when the source is short.
    short = Message(role=Role.TOOL, content="a\nb\nc")
    out2 = trunc.truncate(short, max_lines=10)
    assert out2 is short, "short messages must be returned unchanged"
    _ok("truncate() is a no-op for short messages")


# --- section 4: ContextBuilder end-to-end ------------------------------------


def smoke_context_builder() -> None:
    _section("4. ContextBuilder end-to-end (system + history)")
    from hello_agent.context.builder import ContextBuilder
    from hello_agent.core.types import AgentState, Message, Role

    # 4a. With all features disabled, just system + history → unchanged.
    state = AgentState(
        session_id="sess-smoke",
        messages=[
            Message(role=Role.SYSTEM, content="be brief", system=True),
            Message(role=Role.USER, content="ping"),
            Message(role=Role.ASSISTANT, content="pong"),
        ],
    )
    cb = ContextBuilder(max_context_tokens=100_000, response_reserve_tokens=1_000)
    out = cb.build(state)
    assert len(out) == 3, f"expected 3 messages, got {len(out)}"
    assert out[0].role == Role.SYSTEM
    assert out[0].content == "be brief"
    assert out[-1].content == "pong"
    _ok("system + user + assistant → 3 messages out")

    # 4b. Memory chunks become extra system messages BEFORE history.
    out2 = cb.build(state, memory_chunks=["remember: user prefers terse answers"])
    assert len(out2) == 4
    assert out2[0].content == "be brief"
    assert out2[1].content.startswith("[memory recall]")
    assert out2[1].cache_breakpoint is True
    _ok("memory chunks → extra system messages with cache_breakpoint=True")

    # 4c. RAG chunks become a final system message.
    out3 = cb.build(state, rag_chunks=["doc1: hello", "doc2: world"])
    last = out3[-1]
    assert last.role == Role.SYSTEM
    assert "[relevant documents]" in (last.content or "")
    assert "doc1: hello" in (last.content or "")
    _ok("rag chunks → final system message with [relevant documents] prefix")

    # 4d. Budget enforcement: tiny budget drops oldest non-system messages.
    tiny = ContextBuilder(max_context_tokens=200, response_reserve_tokens=50)
    big_state = AgentState(
        session_id="sess-budget",
        messages=[
            Message(role=Role.SYSTEM, content="be brief", system=True),
            *[
                Message(role=Role.USER, content=f"msg {i} " + "x" * 200)
                for i in range(20)
            ],
        ],
    )
    out4 = tiny.build(big_state)
    # The system message should survive; some user messages should be dropped.
    assert out4[0].role == Role.SYSTEM
    assert len(out4) < 21, f"budget not enforced: {len(out4)} messages"
    _ok(f"tiny budget (200 tokens) trimmed 20-msg history to {len(out4)} messages")


# --- section 5: LongTermMemory SQLite round-trip ----------------------------


def smoke_long_term(db_path: Path) -> None:
    _section("5. LongTermMemory SQLite round-trip")
    from hello_agent.memory.long_term import LongTermMemory

    lt = LongTermMemory(db_path=db_path)
    try:
        rid = lt.set_fact("favorite_editor", "vscode", source="smoke")
        assert rid > 0
        _ok(f"set_fact('favorite_editor', 'vscode') -> id={rid}")

        v = lt.get_fact("favorite_editor")
        assert v == "vscode", f"expected 'vscode', got {v!r}"
        _ok(f"get_fact('favorite_editor') = {v!r}")

        # Upsert: same key, new value.
        lt.set_fact("favorite_editor", "zed", source="smoke")
        v2 = lt.get_fact("favorite_editor")
        assert v2 == "zed"
        assert lt.count() == 1, f"upsert must not create a duplicate row; count={lt.count()}"
        _ok(f"upsert updates the same row (count still {lt.count()})")

        # JSON-encoded value (non-string scalar).
        lt.set_fact("editor_count", 3, source="smoke")
        assert lt.get_fact("editor_count") == 3
        _ok("set_fact with int value round-trips as JSON")

        # list_facts + source filter.
        lt.set_fact("language", "python", source="user")
        all_facts = lt.list_facts()
        assert {f["key"] for f in all_facts} == {"favorite_editor", "editor_count", "language"}
        user_only = lt.list_facts(source="user")
        assert {f["key"] for f in user_only} == {"language"}
        _ok(f"list_facts(source='user') = {[f['key'] for f in user_only]}")

        # search.
        hits = lt.search("editor")
        assert {h["key"] for h in hits} >= {"favorite_editor", "editor_count"}
        _ok(f"search('editor') found {len(hits)} hits")

        # delete.
        assert lt.delete_fact("language") is True
        assert lt.delete_fact("nonexistent") is False
        _ok("delete_fact() returns True/False correctly")
    finally:
        lt.close()


# --- section 6: EpisodicMemory SQLite round-trip -----------------------------


def smoke_episodic(db_path: Path) -> None:
    _section("6. EpisodicMemory SQLite round-trip")
    from hello_agent.memory.episodic import EpisodicMemory

    ep = EpisodicMemory(db_path=db_path, summarize_every_n_turns=20)
    try:
        assert ep.should_summarize(0) is False
        assert ep.should_summarize(20) is True
        assert ep.should_summarize(40) is True
        assert ep.should_summarize(10) is False
        _ok("should_summarize(20|40) == True, should_summarize(10) == False")

        eid = ep.record_episode("sess-smoke", "helped user install zed editor")
        assert eid > 0
        _ok(f"record_episode(...) -> id={eid}")

        ep.record_episode("sess-smoke", "translated 200 lines of Japanese")
        ep.record_episode("sess-other", "debugged a numpy broadcasting issue")
        _ok(f"recorded 3 episodes; total count = {ep.count()}")

        # list_recent + session_id filter.
        recent = ep.list_recent(limit=10)
        assert len(recent) == 3
        sess_smoke = ep.list_recent(session_id="sess-smoke", limit=10)
        assert len(sess_smoke) == 2
        _ok(f"list_recent(session_id='sess-smoke') returned {len(sess_smoke)} entries")

        # search.
        hits = ep.search("numpy")
        assert len(hits) == 1
        assert "numpy" in hits[0]["summary"]
        _ok(f"search('numpy') found {len(hits)} episode(s)")
    finally:
        ep.close()


# --- driver -----------------------------------------------------------------


def main() -> int:
    failures: list[str] = []
    with tempfile.TemporaryDirectory(prefix="smoke_context_") as td:
        tmp_dir = Path(td)
        db_path = tmp_dir / "memory_smoke.db"
        _info(f"tmp dir = {tmp_dir}")
        _info(f"db path = {db_path}")

        sections: list[tuple[str, callable]] = [
            ("smoke_token_counter", smoke_token_counter),
            ("smoke_history_window", smoke_history_window),
            ("smoke_truncator_head_tail", smoke_truncator_head_tail),
            ("smoke_context_builder", smoke_context_builder),
            ("smoke_long_term", lambda: smoke_long_term(db_path)),
            ("smoke_episodic", lambda: smoke_episodic(db_path)),
        ]

        for name, fn in sections:
            try:
                fn()
            except SmokeError as exc:
                print(f"  [FAIL] {name}: {exc}", file=sys.stderr)
                failures.append(name)
            except Exception as exc:  # noqa: BLE001
                print(f"  [CRASH] {name}: {type(exc).__name__}: {exc}", file=sys.stderr)
                traceback.print_exc()
                failures.append(name)

    if failures:
        print(
            f"\n[smoke_context] FAIL: {len(failures)} section(s) failed: {failures}",
            file=sys.stderr,
        )
        return 1
    print("\n[smoke_context] OK: all 6 sections passed")
    return 0


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--workdir" and len(sys.argv) > 2:
        os.chdir(sys.argv[2])
    sys.exit(main())
