"""SKILL.md parsing — dataclasses + YAML frontmatter + Markdown body splitting.

The SKILL.md format (a slimmed-down, hello-agent-native cousin of the
agentskills.io spec):

    ---
    name: file_organize
    description: Categorize files in a folder into groups.
    triggers:
      regex:
        - "(?i)\\borganize\\s+(?:my\\s+)?(?:files|folder|downloads?)\\b"
      keywords:
        - file_organize
        - organize files
    tools:
      - file_tools.read_file
      - file_tools.write_file
    inputs:
      folder_path: string
    outputs:
      categorized: list[object]
    ---

    # file_organize

    ## Procedure
    ...

    ## Examples
    ...

    ## Constraints
    ...

The YAML frontmatter is parsed strictly (extra keys raise); the Markdown
body is stored verbatim. `parse_skill_markdown()` is the single entry
point and is used by both the loader and the tests.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

import yaml

# ----- Errors ---------------------------------------------------------------


class SkillError(Exception):
    """Base error for skill parsing / loading failures."""


class SkillParseError(SkillError):
    """A SKILL.md is malformed (frontmatter, body, or required field)."""


class SkillNotFoundError(SkillError):
    """`load_skill(name)` could not find a SKILL.md for that name."""


# ----- Frontmatter ----------------------------------------------------------


@dataclass
class SkillTriggers:
    """Trigger configuration for matching user prompts to a skill.

    Both fields are optional. A skill with empty triggers still loads
    (the LLM can pick it up by name via the `available_skills` block),
    it just won't be auto-matched by trigger matching.
    """

    regex: list[str] = field(default_factory=list)
    keywords: list[str] = field(default_factory=list)


@dataclass
class SkillFrontmatter:
    """Strict view of the YAML frontmatter a SKILL.md must declare.

    All fields except `name` and `description` are optional with sensible
    defaults so power-users can write minimal SKILL.md files.
    """

    name: str
    description: str
    version: str = "0.1.0"
    author: str = ""
    license: str = "MIT"
    platforms: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    category: str = "general"
    related_skills: list[str] = field(default_factory=list)
    triggers: SkillTriggers = field(default_factory=SkillTriggers)
    tools: list[str] = field(default_factory=list)
    inputs: dict[str, Any] = field(default_factory=dict)
    outputs: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SkillFrontmatter:
        """Build a `SkillFrontmatter` from a parsed YAML dict.

        Required keys: `name`, `description`. Missing optional keys keep
        their defaults; unknown keys are silently ignored so we can
        forward-extend the format without breaking older skills.
        """
        if not isinstance(data, dict):
            raise SkillParseError(
                f"frontmatter must be a YAML mapping, got {type(data).__name__}"
            )

        # Required keys
        try:
            name = str(data["name"]).strip()
            description = str(data["description"]).strip()
        except KeyError as exc:
            raise SkillParseError(
                f"frontmatter missing required key: {exc.args[0]!r}"
            ) from exc
        if not name:
            raise SkillParseError("frontmatter.name is empty")
        if not description:
            raise SkillParseError(f"frontmatter.description is empty (skill={name!r})")
        # Hermes-style recommendation: keep descriptions ≤ 60 chars so they
        # fit one line in a terminal UI. We warn-log at the loader level;
        # here we just accept whatever the file says.
        if len(description) > 200:
            raise SkillParseError(
                f"frontmatter.description too long ({len(description)} chars, max 200)"
            )

        triggers_raw = data.get("triggers") or {}
        if not isinstance(triggers_raw, dict):
            raise SkillParseError(
                f"frontmatter.triggers must be a mapping, got {type(triggers_raw).__name__}"
            )
        regex_raw = triggers_raw.get("regex") or []
        keywords_raw = triggers_raw.get("keywords") or []
        if not isinstance(regex_raw, list) or not all(isinstance(x, str) for x in regex_raw):
            raise SkillParseError("frontmatter.triggers.regex must be a list of strings")
        if not isinstance(keywords_raw, list) or not all(
            isinstance(x, str) for x in keywords_raw
        ):
            raise SkillParseError("frontmatter.triggers.keywords must be a list of strings")

        triggers = SkillTriggers(
            regex=[str(x) for x in regex_raw],
            keywords=[str(x).lower() for x in keywords_raw],
        )

        tools_raw = data.get("tools") or []
        if not isinstance(tools_raw, list) or not all(isinstance(x, str) for x in tools_raw):
            raise SkillParseError("frontmatter.tools must be a list of strings")

        def _str_list(key: str) -> list[str]:
            v = data.get(key) or []
            if not isinstance(v, list) or not all(isinstance(x, str) for x in v):
                raise SkillParseError(f"frontmatter.{key} must be a list of strings")
            return [str(x) for x in v]

        def _str_dict(key: str) -> dict[str, Any]:
            v = data.get(key) or {}
            if not isinstance(v, dict):
                raise SkillParseError(
                    f"frontmatter.{key} must be a mapping, got {type(v).__name__}"
                )
            return dict(v)

        return cls(
            name=name,
            description=description,
            version=str(data.get("version", "0.1.0") or "0.1.0"),
            author=str(data.get("author", "") or ""),
            license=str(data.get("license", "MIT") or "MIT"),
            platforms=_str_list("platforms"),
            tags=_str_list("tags"),
            category=str(data.get("category", "general") or "general"),
            related_skills=_str_list("related_skills"),
            triggers=triggers,
            tools=[str(x) for x in tools_raw],
            inputs=_str_dict("inputs"),
            outputs=_str_dict("outputs"),
        )


# ----- Top-level Skill -------------------------------------------------------


@dataclass
class Skill:
    """A parsed SKILL.md file."""

    name: str
    description: str
    frontmatter: SkillFrontmatter
    body: str  # the full markdown body (everything after the frontmatter)
    path: str  # absolute path to the source file
    is_builtin: bool = False  # True if loaded from hello_agent/skills/builtin/

    @property
    def triggers(self) -> SkillTriggers:
        return self.frontmatter.triggers

    @property
    def tools(self) -> list[str]:
        return self.frontmatter.tools

    @property
    def has_procedure_section(self) -> bool:
        """Whether the body contains a `## Procedure` section.

        Per `docs/ENGINEERING.md` §5.9 / §6.10, every well-formed SKILL.md
        must include this section — it's what the LLM reads to know the
        how-to. Built-in skills and third-party skills without a Procedure
        section get a warning at load time (see `loader.load_all_skills`).
        """
        return bool(_SECTION_RE.search(self.body or ""))

    def to_dict(self) -> dict[str, Any]:
        """Public-API serialization for the Web UI / CLI --json output."""
        return {
            "name": self.name,
            "description": self.description,
            "version": self.frontmatter.version,
            "author": self.frontmatter.author,
            "license": self.frontmatter.license,
            "platforms": list(self.frontmatter.platforms),
            "tags": list(self.frontmatter.tags),
            "category": self.frontmatter.category,
            "related_skills": list(self.frontmatter.related_skills),
            "triggers": {
                "regex": list(self.frontmatter.triggers.regex),
                "keywords": list(self.frontmatter.triggers.keywords),
            },
            "tools": list(self.frontmatter.tools),
            "inputs": dict(self.frontmatter.inputs),
            "outputs": dict(self.frontmatter.outputs),
            "path": self.path,
            "is_builtin": self.is_builtin,
            "has_procedure_section": self.has_procedure_section,
        }


# A markdown-level "## Heading" line (heading level 2 only — the format
# documented in ENGINEERING.md §5.9).
_SECTION_RE = re.compile(r"(?m)^##\s+Procedure\b", re.IGNORECASE)


# ----- Parsing ---------------------------------------------------------------


# Match a YAML frontmatter block at the very start of the file:
#
#     ---\n
#     key: value\n
#     ---\n
#
# We anchor on `^---\n` and require the closing `---\n` to be on its own
# line. Anything after the closing fence is the body.
_FRONTMATTER_RE = re.compile(
    r"\A---[ \t]*\r?\n(?P<yaml>.*?)\r?\n---[ \t]*(?:\r?\n|\Z)",
    re.DOTALL,
)


def parse_skill_markdown(text: str, *, path: str = "<string>") -> Skill:
    """Parse a SKILL.md string into a `Skill`.

    `text` is the full file contents. `path` is used in error messages
    (and stored on the resulting `Skill.path`). Raises `SkillParseError`
    on any structural problem.
    """
    if not isinstance(text, str):
        raise SkillParseError(f"SKILL.md must be str, got {type(text).__name__} ({path})")

    match = _FRONTMATTER_RE.match(text)
    if not match:
        raise SkillParseError(
            f"{path}: missing YAML frontmatter (file must start with '---' on line 1)"
        )

    yaml_block = match.group("yaml")
    try:
        data = yaml.safe_load(yaml_block) or {}
    except yaml.YAMLError as exc:
        raise SkillParseError(f"{path}: invalid YAML in frontmatter: {exc}") from exc

    frontmatter = SkillFrontmatter.from_dict(data)
    body = text[match.end():]
    return Skill(
        name=frontmatter.name,
        description=frontmatter.description,
        frontmatter=frontmatter,
        body=body,
        path=path,
        is_builtin=False,  # loader sets this when it knows the source
    )


__all__ = [
    "Skill",
    "SkillFrontmatter",
    "SkillTriggers",
    "SkillError",
    "SkillParseError",
    "SkillNotFoundError",
    "parse_skill_markdown",
]