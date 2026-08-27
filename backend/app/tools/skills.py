import asyncio
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, ClassVar

import yaml


@dataclass(slots=True, frozen=True)
class SkillMetadata:
    name: str
    description: str
    base_path: Path
    skill_file: Path
    allowed_tools: tuple[str, ...] = ()


class SkillRegistry:
    def __init__(self, directories: list[str | Path]) -> None:
        self._directories = [Path(path).expanduser().resolve(strict=False) for path in directories]
        self._skills: dict[str, SkillMetadata] | None = None

    def list_all(self) -> list[SkillMetadata]:
        self._load()
        assert self._skills is not None
        return [self._skills[name] for name in sorted(self._skills)]

    def get(self, name: str) -> SkillMetadata | None:
        self._load()
        assert self._skills is not None
        return self._skills.get(name)

    def read(self, name: str) -> str:
        metadata = self.get(name)
        if metadata is None:
            raise ValueError(f"未找到技能: {name}")
        resolved = metadata.skill_file.resolve(strict=True)
        if not any(resolved.is_relative_to(root) for root in self._directories):
            raise ValueError(f"技能文件越过允许目录: {resolved}")
        return resolved.read_text(encoding="utf-8")

    def reload(self) -> None:
        self._skills = None

    def prompt_fragment(self) -> str:
        skills = self.list_all()
        if not skills:
            return "当前没有可用技能。"
        rows = ["<available_skills>"]
        for skill in skills:
            rows.append(f'<skill name="{skill.name}">{skill.description}</skill>')
        rows.append("</available_skills>")
        return "\n".join(rows)

    def _load(self) -> None:
        if self._skills is not None:
            return
        discovered: dict[str, SkillMetadata] = {}
        for root in self._directories:
            if not root.is_dir():
                continue
            for skill_file in sorted(root.rglob("SKILL.md"), key=lambda path: path.as_posix().lower()):
                try:
                    resolved = skill_file.resolve(strict=True)
                except OSError:
                    continue
                if not resolved.is_relative_to(root) or not resolved.is_file():
                    continue
                content = resolved.read_text(encoding="utf-8")
                frontmatter, body = _split_frontmatter(content)
                raw_name = frontmatter.get("name") if isinstance(frontmatter, dict) else None
                name = str(raw_name or resolved.parent.name).strip()
                if not name:
                    continue
                raw_description = frontmatter.get("description") if isinstance(frontmatter, dict) else None
                description = str(raw_description or _first_paragraph(body) or f"Skill: {name}").strip()
                raw_tools = frontmatter.get("allowedTools") if isinstance(frontmatter, dict) else None
                allowed_tools = tuple(str(item) for item in raw_tools) if isinstance(raw_tools, list) else ()
                discovered[name] = SkillMetadata(name, description, resolved.parent, resolved, allowed_tools)
        self._skills = discovered


class ReadSkillTool:
    name = "read_skill"
    definition: ClassVar[dict[str, Any]] = {
        "type": "function",
        "function": {
            "name": name,
            "description": "加载指定技能的完整 SKILL.md。技能加载后应直接遵循技能指令，不要重复加载同一技能。",
            "parameters": {
                "type": "object",
                "properties": {"skill": {"type": "string", "description": "技能名称"}},
                "required": ["skill"],
            },
        },
    }

    def __init__(self, registry: SkillRegistry) -> None:
        self._registry = registry

    async def call(self, arguments: str) -> str:
        try:
            payload = json.loads(arguments or "{}")
        except json.JSONDecodeError:
            return json.dumps({"success": False, "error": "工具参数必须是 JSON object"}, ensure_ascii=False)
        if not isinstance(payload, dict):
            return json.dumps({"success": False, "error": "工具参数必须是 JSON object"}, ensure_ascii=False)
        skill = str(payload.get("skill") or "").strip()
        if not skill:
            return json.dumps({"success": False, "error": "skill 不能为空"}, ensure_ascii=False)
        try:
            content = await asyncio.to_thread(self._registry.read, skill)
            metadata = self._registry.get(skill)
            return json.dumps(
                {
                    "skill": skill,
                    "content": content,
                    "basePath": str(metadata.base_path) if metadata else None,
                    "success": True,
                    "error": None,
                },
                ensure_ascii=False,
            )
        except Exception as exc:
            return json.dumps(
                {"skill": skill, "content": None, "success": False, "error": str(exc)},
                ensure_ascii=False,
            )


def _split_frontmatter(content: str) -> tuple[dict[str, Any], str]:
    normalized = content.lstrip("\ufeff")
    lines = normalized.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}, normalized
    for index in range(1, len(lines)):
        if lines[index].strip() == "---":
            frontmatter_text = "\n".join(lines[1:index])
            value = yaml.safe_load(frontmatter_text) or {}
            return (value if isinstance(value, dict) else {}), "\n".join(lines[index + 1 :]).strip()
    return {}, normalized


def _first_paragraph(content: str) -> str:
    parts: list[str] = []
    for line in content.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            if parts:
                break
            continue
        parts.append(stripped)
    return " ".join(parts)
