"""Skills (SKILL.md) loader + bundled skills.

Public surface (re-exported here for convenience):

- `loader` — `hello_agent.skills.loader`
- `registry` — `hello_agent.skills.registry`
- `models` — `hello_agent.skills.models`
- `Skill` — the parsed-SKILL.md dataclass
- `SkillFrontmatter` — the YAML frontmatter dataclass
- `SkillTriggers` — the triggers sub-dataclass
- `SkillMatch` — a `match()` result
- `parse_skill_markdown(text)` — the single parsing entry point
- `load_skill(name)` / `list_skills()` — the loader's procedural API
- `match_skill(prompt)` / `match_skills(prompt)` — the registry's matching API
- `activate_skill(...)` / `deactivate_skill(...)` — per-session activation
- `inject_skills_into_system_prompt(...)` — for the ReAct agent
- `resolve_skill_tool(tool_ref)` — for the Web UI's "uses tools" badge

The split is:

- `models.py` — pure data: `Skill`, `SkillFrontmatter`, `parse_skill_markdown()`
- `loader.py` — disk I/O: scans `~/.hello_agent/skills/` + `builtin/`, caches
- `registry.py` — runtime: trigger matching, per-session activation, prompt injection

`loader`, `models`, and `registry` are the three submodules; this `__init__`
re-exports the most common entry points so callers can write
`from hello_agent.skills import load_skill, match_skill, Skill`.
"""
from __future__ import annotations

# Re-import submodules so they appear as attributes on this package
# (ruff F822 checks __all__ against actual module attributes).
from hello_agent.skills import loader, models, registry
from hello_agent.skills.loader import (
 SkillLoader,
 ensure_user_skills_dir,
 get_active_skills_dir,
 get_builtin_skills_dir,
 get_loader,
 get_skill_command_prompt,
 get_user_skills_dir,
 install_skill,
 list_skills,
 load_skill,
 reload_skills,
 reset_loader,
 skill_fingerprint,
)
from hello_agent.skills.models import (
 Skill,
 SkillError,
 SkillFrontmatter,
 SkillNotFoundError,
 SkillParseError,
 SkillTriggers,
 parse_skill_markdown,
)
from hello_agent.skills.registry import (
 RegistryError,
 SkillActivationError,
 SkillMatch,
 SkillRegistry,
 activate_skill,
 active_skills_for,
 build_available_skills_block,
 deactivate_skill,
 get_registry,
 inject_skills_into_system_prompt,
 match_skill,
 match_skills,
 reset_registry,
 resolve_skill_tool,
)

__version__ = "0.1.0"

__all__ = [
 # submodules
 "loader",
 "models",
 "registry",
 # models
 "Skill",
 "SkillFrontmatter",
 "SkillTriggers",
 "SkillError",
 "SkillParseError",
 "SkillNotFoundError",
 "parse_skill_markdown",
 # loader
 "SkillLoader",
 "get_loader",
 "reset_loader",
 "list_skills",
 "load_skill",
 "reload_skills",
 "install_skill",
 "get_skill_command_prompt",
 "skill_fingerprint",
 "get_user_skills_dir",
 "ensure_user_skills_dir",
 "get_active_skills_dir",
 "get_builtin_skills_dir",
 # registry
 "SkillMatch",
 "RegistryError",
 "SkillActivationError",
 "SkillRegistry",
 "get_registry",
 "reset_registry",
 "match_skill",
 "match_skills",
 "active_skills_for",
 "activate_skill",
 "deactivate_skill",
 "build_available_skills_block",
 "inject_skills_into_system_prompt",
 "resolve_skill_tool",
]
