"""Skills route — list / show / install.

The route surface mirrors `hello-agent skills {list,show,install}` so the
CLI and the Web UI share the same backing API.

`POST /api/skills/install` accepts a `multipart/form-data` upload of a
SKILL.md file (the React UI's "Install skill" button uses a `<input
type=file>`). The endpoint reuses `hello_agent.skills.loader.install_skill`
so behavior is identical to `hello-agent skills install <path>`.
"""
from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any

from fastapi import APIRouter, File, HTTPException, UploadFile
from pydantic import BaseModel

from hello_agent.core.logging import get_logger
from hello_agent.skills.loader import install_skill, list_skills, load_skill
from hello_agent.skills.models import SkillError, SkillNotFoundError

logger = get_logger(__name__)

router = APIRouter()


# ----- response models --------------------------------------------------------


class SkillSummary(BaseModel):
    name: str
    description: str
    version: str = "0.1.0"
    author: str = ""
    category: str = "general"
    tags: list[str] = []
    is_builtin: bool = False
    has_procedure_section: bool = False
    triggers: dict[str, list[str]] = {}
    tools: list[str] = []
    path: str = ""


class SkillDetail(SkillSummary):
    body: str = ""
    license: str = "MIT"
    platforms: list[str] = []
    related_skills: list[str] = []
    inputs: dict[str, Any] = {}
    outputs: dict[str, Any] = {}


class InstallResponse(BaseModel):
    name: str
    installed_path: str
    overwritten: bool = False


# ----- helpers ----------------------------------------------------------------


def _summary_dict(s: Any) -> dict[str, Any]:
    """Project a `Skill` into the wire summary shape."""
    return {
        "name": s.name,
        "description": s.description,
        "version": s.frontmatter.version,
        "author": s.frontmatter.author,
        "category": s.frontmatter.category,
        "tags": list(s.frontmatter.tags),
        "is_builtin": s.is_builtin,
        "has_procedure_section": s.has_procedure_section,
        "triggers": {
            "regex": list(s.frontmatter.triggers.regex),
            "keywords": list(s.frontmatter.triggers.keywords),
        },
        "tools": list(s.frontmatter.tools),
        "path": s.path,
    }


def _detail_dict(s: Any) -> dict[str, Any]:
    """Project a `Skill` into the wire detail shape (summary + body)."""
    base = _summary_dict(s)
    base.update(
        {
            "body": s.body,
            "license": s.frontmatter.license,
            "platforms": list(s.frontmatter.platforms),
            "related_skills": list(s.frontmatter.related_skills),
            "inputs": dict(s.frontmatter.inputs),
            "outputs": dict(s.frontmatter.outputs),
        }
    )
    return base


# ----- routes -----------------------------------------------------------------


@router.get("/", response_model=list[SkillSummary])
async def list_all(reload: bool = False) -> list[SkillSummary]:
    """List every loaded skill (sorted by name; builtins + user)."""
    skills = list_skills(use_cache=not reload)
    return [SkillSummary(**_summary_dict(s)) for s in skills]


@router.get("/{name}", response_model=SkillDetail)
async def show(name: str) -> SkillDetail:
    """Return the full SKILL.md (frontmatter + body) for one skill."""
    try:
        skill = load_skill(name)
    except SkillNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except SkillError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return SkillDetail(**_detail_dict(skill))


@router.post("/install", response_model=InstallResponse)
async def install(
    file: UploadFile = File(..., description="SKILL.md contents to install."),  # noqa: B008
    force: bool = False,
) -> InstallResponse:
    """Install a SKILL.md from a multipart upload.

    Writes the upload to a temp file and delegates to
    `install_skill()` so all of its validation (parse, name uniqueness,
    force-overwrite guard) applies. The temp file is removed in
    `finally:` regardless of success.
    """
    if file is None or not file.filename:
        raise HTTPException(status_code=400, detail="file is required")
    if not file.filename.endswith(".md"):
        raise HTTPException(status_code=400, detail="file must be a .md (SKILL.md)")

    tmp_path: Path | None = None
    overwritten = False
    try:
        # Read the upload into memory (SKILL.md files are small; max a few KB).
        body = await file.read()
        if not body:
            raise HTTPException(status_code=400, detail="uploaded file is empty")

        # Stash the body into a temp file so `install_skill()`'s
        # validation (parse + name-collision check) runs unchanged.
        with tempfile.NamedTemporaryFile(
            mode="wb", suffix=".md", delete=False, encoding=None
        ) as tmp:
            tmp.write(body)
            tmp_path = Path(tmp.name)

        # The `force` flag controls the env var the loader consults.
        import os

        prev = os.environ.get("HELLO_AGENT_SKILL_FORCE_INSTALL")
        if force:
            os.environ["HELLO_AGENT_SKILL_FORCE_INSTALL"] = "1"
        else:
            os.environ.pop("HELLO_AGENT_SKILL_FORCE_INSTALL", None)
        try:
            # Was the destination already present *before* this call?
            from hello_agent.skills.loader import get_user_skills_dir

            # Parse the file to know its `name` (so we can check
            # for overwrite). Do a minimal pre-check using the parser.
            from hello_agent.skills.models import parse_skill_markdown

            text = body.decode("utf-8", errors="replace")
            skill = parse_skill_markdown(text, path=tmp_path.name)
            dest = get_user_skills_dir() / f"{skill.name}.md"
            overwritten = dest.exists()

            dest_path = install_skill(tmp_path)
        finally:
            # Restore env var.
            if prev is None:
                os.environ.pop("HELLO_AGENT_SKILL_FORCE_INSTALL", None)
            else:
                os.environ["HELLO_AGENT_SKILL_FORCE_INSTALL"] = prev

        return InstallResponse(
            name=skill.name,
            installed_path=str(dest_path),
            overwritten=overwritten,
        )
    except HTTPException:
        raise
    except SkillNotFoundError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except SkillError as exc:
        raise HTTPException(status_code=400, detail=f"install failed: {exc}") from exc
    except Exception as exc:  # noqa: BLE001
        logger.exception("skills.install: unexpected error")
        raise HTTPException(status_code=500, detail=f"install failed: {exc}") from exc
    finally:
        if tmp_path is not None and tmp_path.exists():
            try:
                tmp_path.unlink()
            except OSError:
                pass  # best-effort cleanup


__all__ = [
    "router",
    "SkillSummary",
    "SkillDetail",
    "InstallResponse",
]
