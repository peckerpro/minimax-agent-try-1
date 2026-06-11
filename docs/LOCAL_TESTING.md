# hello-agent-2 鏈湴娴嬭瘯閫熸煡

> 宸ヤ綔鐩綍绾﹀畾锛氭湰椤垫墍鏈夊懡浠ら粯璁ゅ湪 worktree 鏍圭洰褰曟墽琛岋細
> `D:\Minimax-project\hello-agent-2\.worktrees\wt-e5bdcb08`
>
> 濡傛灉浣犲湪涓?checkout 閲岋紝璺緞鏄?`D:\Minimax-project\hello-agent-2\`銆?
---

## 0. 鐜鍓嶇疆

```powershell
# 蹇呴』鐨勫伐鍏?uv --version        # >= 0.11
python --version    # 3.11 / 3.12 / 3.13 浠讳竴

# 绗竴娆¤繘 worktree锛堝彧闇€瑕佷竴娆★級
uv sync --all-extras
```

---

## 1. 5 绉掑揩閫熼獙璇侊紙"鎴戞病鏀逛笢瑗匡紝OK 鍚楋紵"锛?
```powershell
# lint + 鍏ㄦ祴锛堟渶甯歌鐨勫悎骞跺墠妫€鏌ワ級
uv run ruff check hello_agent/ scripts/ tests/
uv run pytest -q
```

**棰勬湡杈撳嚭**锛?- ruff: `All checks passed!`
- pytest: `486 passed in ~75s`锛堝惈 v0.2.1 鍙屽悜缁戝畾鐨勬柊澧?47 涓?case锛?
---

## 2. 鎸夋ā鍧楄窇锛?鎴戝彧鏀逛簡 X 妯″潡"锛?
```powershell
# 鍏?memory 妯″潡锛坰hort_term / long_term / episodic / obsidian_sync / git_sync锛?uv run pytest tests/test_memory/ -q

# 鍗曟枃浠?uv run pytest tests/test_memory/test_obsidian_sync.py -q
uv run pytest tests/test_memory/test_git_sync.py -q
uv run pytest tests/test_memory/test_long_term.py -q

# 鍏朵粬妯″潡
uv run pytest tests/test_agents/    -q
uv run pytest tests/test_cli/       -q
uv run pytest tests/test_context/   -q
uv run pytest tests/test_core/      -q
uv run pytest tests/test_protocols/ -q   # Day 6 MCP
uv run pytest tests/test_rag/       -q
uv run pytest tests/test_skills/    -q   # Day 7
uv run pytest tests/test_web/       -q   # Day 8
uv run pytest tests/test_windows/   -q   # Day 9 (Windows only)

# 璺戞煇涓叿浣撶殑娴嬭瘯鍑芥暟
uv run pytest tests/test_memory/test_long_term.py::test_reconcile_adds_new_facts_from_vault -v
```

---

## 3. Smoke 鑴氭湰锛堜笉渚濊禆 pytest 鐨勭鍒扮 smoke锛?
```powershell
uv run python scripts/smoke_agents.py
uv run python scripts/smoke_cli.py
uv run python scripts/smoke_context.py
uv run python scripts/smoke_core.py
uv run python scripts/smoke_rag.py
uv run python scripts/smoke_skills.py
uv run python scripts/smoke_tools.py
```

姣忎釜 smoke 鑴氭湰绂荤嚎鍙窇锛堢害 1-3 绉掞級锛屾墦鍗?`[OK] section X` / `[FAIL]` 琛屻€?
---

## 4. 5 涓?runnable example

```powershell
# 绂荤嚎 self-test锛堜笉闇€瑕?LLM key锛?uv run python examples/01_quick_chat.py --self-test
uv run python examples/02_rag_index_and_query.py --self-test
uv run python examples/03_rag_index_and_query.py --self-test
uv run python examples/04_obsidian_export.py --self-test
uv run python examples/05_mcp_round_trip.py --self-test

# 鐪?LLM 璋冪敤锛堥渶瑕?.env 閲岀殑 LLM_API_KEY / LLM_BASE_URL锛?uv run python examples/01_quick_chat.py
uv run python hello-agent run "鐢ㄤ竴鍙ヨ瘽鍛婅瘔鎴?hello-agent 椤圭洰鏄仛浠€涔堢殑"
```

---

## 5. Obsidian vault 鍙屽悜缁戝畾锛坴0.2.1 鏂板锛?
### 5.1 鐪?vault 鐘舵€?
```powershell
# 鍏ㄩ儴 13 涓?check锛堝惈 vault reachability锛?uv run hello-agent doctor run

# 鐪?vault 閲岀殑 fact 鍒楄〃
uv run hello-agent memory show

# 鎵嬪姩瑙﹀彂 vault 鈫?SQLite 鎷夊彇
uv run hello-agent memory reconcile
uv run hello-agent memory reconcile --json
```

### 5.2 鍐欎竴涓?fact锛堜細鍚屾椂钀?SQLite + vault .md锛?
```powershell
# 鍐欎竴鏉″瓧绗︿覆 fact
uv run hello-agent memory export "agent prefers dark mode" --id theme_preference --tags "ui"

# 鍐欎竴鏉℃洿缁撴瀯鍖栫殑 fact
uv run hello-agent memory export "agent's project: hello-agent-2, v0.2.1" --id project_meta --title "Project metadata" --tags "meta"
```

钀界洏浣嶇疆锛歚D:\hello_agent_obsidian_1\memory\<YYYY-MM-DD>_<slug>.md`
锛坴ault 鏍圭洰褰曠敱 `.env` 閲岀殑 `OBSIDIAN_VAULT_PATH` 鍐冲畾锛?
### 5.3 鎺ㄩ€佸埌 GitHub

```powershell
# 鍗曟 commit + push
uv run hello-agent memory sync --force

# 鍚庡彴瀹堟姢绾跨▼锛堟瘡 5min commit锛屾瘡 15min push锛?uv run hello-agent memory sync

# 鐪?push 缁撴灉
git -C 'D:\hello_agent_obsidian_1' log --oneline -5
git -C 'D:\hello_agent_obsidian_1' status -sb
```

> 鎺ㄤ笉鍔ㄦ椂鐨勯噸璇曟槸鑷姩鐨勶紙`_try_push` 鍐呯疆 3 娆?脳 5s 閲嶈瘯 + non-fast-forward
> 鑷姩 fetch + force-with-lease锛夈€傚鏋?GitHub 缃戠粶鏁存涓嶉€氾紝閿欒浼氬師鏍?> 鎶ュ洖鏉ワ紝鍛戒护涓嶄細鍗℃銆?
### 5.4 鍦?Obsidian Desktop 閭ｈ竟

- 鎶?`D:\hello_agent_obsidian_1` 浣滀负 vault 鍦?Obsidian 閲屾墦寮€
- 瑁?**Obsidian Git** 鎻掍欢锛圕ommunity plugins锛夛紝璁惧畾 remote = `https://github.com/peckerpro/minimax-hello-agent-obsidian-knowledge-db.git`
- Obsidian Git 鎻掍欢璐熻矗 pull 浣犺繙绔?`main` 鐨勬洿鏂?- 浣犲湪 Obsidian 閲屾敼瀹?.md 鈫?鎻掍欢 commit + push 鈫?涓嬫 agent 璺?`reconcile` 鏃惰兘鐪嬭

---

## 6. Release 鍓嶇殑纭€?gate

```powershell
# ruff 蹇呴』 0 error
uv run ruff check hello_agent/ scripts/ tests/

# 鍏ㄦ祴蹇呴』 0 failed
uv run pytest -q

# version bump 鍚屾锛坃_version__ / pyproject.toml / CHANGELOG.md 涓夊锛?uv run hello-agent --version
```

瀹屾暣 release 妫€鏌ワ細
```powershell
.\scripts\release_check.ps1
```

---

## 7. 鏁呴殰鎺掓煡閫熸煡

| 鐥囩姸 | 鎺掓煡鍛戒护 |
|---|---|
| ruff 鎶?`PLW1514`锛堟枃浠舵墦寮€娌℃樉寮?encoding锛?| 鏀规垚 `open(path, "r", encoding="utf-8")` |
| 娴嬭瘯鎶?`ModuleNotFoundError` | `uv sync --all-extras` |
| `hello-agent` 鎵句笉鍒?| `uv run hello-agent ...`锛堝繀椤荤敤 `uv run`锛?|
| LLM 鐪熻皟鐢ㄦ姤 `APIConnectionError` | `.env` 閲?`LLM_BASE_URL` 杩樻湁鍗犱綅绗︼紝鎴栫綉缁滀笉閫?|
| Obsidian push 鎶?"non-fast-forward" | 宸茶嚜鍔?fetch + force-with-lease锛涘鏋滆繕鎸傦紝鐪?`.env` 閲岀殑 `OBSIDIAN_GIT_REPO` 鍜?`OBSIDIAN_GIT_TOKEN` |
| 娴嬭瘯鍥犵鍙ｅ啿绐佸伓鍙戝け璐?| `uv run pytest -q -p no:cacheprovider` 涓茶閲嶈窇锛屾垨鍗曟枃浠惰窇 |
| `doctor` 鎶?vault `not a standard Obsidian vault` | 姝ｅ父 鈥斺€?浣?vault 鏍圭洰褰曟病鏈?`.obsidian/`锛汷bsidian 鍚姩鏃朵細鑷繁鍒涘缓 |

---

## 8. 涓€娆℃€ц剼鏈悎闆?
```powershell
# 瀹屾暣鏈湴 verify锛坙int + 鍏ㄦ祴 + doctor + reconcile锛?uv run ruff check hello_agent/ scripts/ tests/ && `
uv run pytest -q && `
uv run hello-agent doctor run && `
uv run hello-agent memory reconcile
```

濡傛灉涓婇潰杩欎竴鏉￠摼鍏ㄧ豢锛屼綘鐨勫伐浣滃氨鏄?mergeable 鐨勩€?