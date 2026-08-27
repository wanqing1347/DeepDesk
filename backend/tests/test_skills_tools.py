import asyncio
import json
from pathlib import Path

from app.config import Settings
from app.tools.bash import RestrictedBashTool
from app.tools.filesystem import FileSystemToolset
from app.tools.grep import GrepTool
from app.tools.local_workspace import SafeWorkspace, WorkspaceBoundaryError
from app.tools.skills import ReadSkillTool, SkillRegistry


def test_safe_workspace_rejects_parent_and_absolute_escape(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    workspace = SafeWorkspace(root)

    assert workspace.resolve("nested/file.txt") == (root / "nested/file.txt").resolve()

    try:
        workspace.resolve("../outside.txt")
    except WorkspaceBoundaryError:
        pass
    else:
        raise AssertionError("parent traversal should be rejected")

    outside = tmp_path / "outside.txt"
    try:
        workspace.resolve(str(outside))
    except WorkspaceBoundaryError:
        pass
    else:
        raise AssertionError("absolute path outside workspace should be rejected")


def test_filesystem_tools_read_write_edit_glob_and_list(tmp_path: Path) -> None:
    async def scenario() -> None:
        root = tmp_path / "workspace"
        root.mkdir()
        (root / "src").mkdir()
        (root / "src" / "a.py").write_text("alpha\nbeta\ngamma\n", encoding="utf-8")
        tools = FileSystemToolset(SafeWorkspace(root), default_line_limit=2)

        read = await tools.call("read_file", json.dumps({"filePath": "src/a.py", "offset": 1}))
        assert "2\tbeta" in read
        assert "3\tgamma" in read

        created = await tools.call("write_file", json.dumps({"filePath": "notes/new.txt", "content": "one two"}))
        assert created.startswith("Successfully created file:")
        refused = await tools.call("write_file", json.dumps({"filePath": "notes/new.txt", "content": "overwrite"}))
        assert "already exists" in refused
        assert (root / "notes" / "new.txt").read_text(encoding="utf-8") == "one two"

        edited = await tools.call(
            "edit_file",
            json.dumps({"filePath": "notes/new.txt", "oldString": "two", "newString": "three"}),
        )
        assert edited.startswith("Successfully edited file:")
        assert (root / "notes" / "new.txt").read_text(encoding="utf-8") == "one three"

        globbed = await tools.call("glob_files", json.dumps({"pattern": "**/*.py"}))
        assert globbed == "src/a.py"
        listed = await tools.call("list_files", json.dumps({"path": ".", "recursive": True}))
        assert "src/" in listed
        assert "src/a.py" in listed
        assert "notes/new.txt" in listed

        escaped = await tools.call("read_file", json.dumps({"filePath": "../secret.txt"}))
        assert "outside workspace root" in escaped

    asyncio.run(scenario())


def test_filesystem_edit_rejects_ambiguous_match_without_replace_all(tmp_path: Path) -> None:
    async def scenario() -> None:
        root = tmp_path / "workspace"
        root.mkdir()
        (root / "dup.txt").write_text("x x", encoding="utf-8")
        tools = FileSystemToolset(SafeWorkspace(root))

        result = await tools.call(
            "edit_file",
            json.dumps({"filePath": "dup.txt", "oldString": "x", "newString": "y"}),
        )
        assert "出现 2 次" in result
        assert (root / "dup.txt").read_text(encoding="utf-8") == "x x"

        result = await tools.call(
            "edit_file",
            json.dumps({"filePath": "dup.txt", "oldString": "x", "newString": "y", "replaceAll": True}),
        )
        assert result.startswith("Successfully edited file:")
        assert (root / "dup.txt").read_text(encoding="utf-8") == "y y"

    asyncio.run(scenario())


def test_grep_tool_supports_modes_context_and_workspace_boundary(tmp_path: Path) -> None:
    async def scenario() -> None:
        root = tmp_path / "workspace"
        root.mkdir()
        (root / "a.txt").write_text("before\nError one\nafter\nerror two\n", encoding="utf-8")
        (root / "b.md").write_text("Error markdown", encoding="utf-8")
        grep = GrepTool(SafeWorkspace(root), head_limit=20)

        content = await grep.call(
            json.dumps(
                {
                    "pattern": "error",
                    "glob": "*.txt",
                    "ignoreCase": True,
                    "beforeContext": 1,
                    "afterContext": 1,
                }
            )
        )
        assert "a.txt:2:Error one" in content
        assert "a.txt:4:error two" in content
        assert "a.txt-1-before" in content

        files = await grep.call(json.dumps({"pattern": "Error", "outputMode": "files_with_matches"}))
        assert files.splitlines() == ["a.txt", "b.md"]
        counts = await grep.call(json.dumps({"pattern": "error", "ignoreCase": True, "outputMode": "count"}))
        assert "a.txt:2" in counts
        assert "b.md:1" in counts

        escaped = await grep.call(json.dumps({"pattern": ".*", "path": ".."}))
        assert "outside workspace root" in escaped

    asyncio.run(scenario())


def test_skill_registry_discovers_frontmatter_and_read_skill(tmp_path: Path) -> None:
    async def scenario() -> None:
        skill_root = tmp_path / "skills"
        skill_dir = skill_root / "code-review"
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text(
            """---
name: code-review
description: Review code safely
allowedTools:
  - read_file
  - grep
---
# Code Review
Inspect the code and report risks.
""",
            encoding="utf-8",
        )
        fallback_dir = skill_root / "fallback"
        fallback_dir.mkdir()
        (fallback_dir / "SKILL.md").write_text("# Fallback\nFirst useful paragraph.\n", encoding="utf-8")

        registry = SkillRegistry([skill_root])
        skills = registry.list_all()
        assert [skill.name for skill in skills] == ["code-review", "fallback"]
        assert skills[0].description == "Review code safely"
        assert skills[0].allowed_tools == ("read_file", "grep")
        assert skills[1].description == "First useful paragraph."
        assert "<available_skills>" in registry.prompt_fragment()

        tool = ReadSkillTool(registry)
        result = json.loads(await tool.call(json.dumps({"skill": "code-review"})))
        assert result["success"] is True
        assert "Inspect the code" in result["content"]
        missing = json.loads(await tool.call(json.dumps({"skill": "missing"})))
        assert missing["success"] is False
        assert "未找到技能" in missing["error"]

    asyncio.run(scenario())


def test_restricted_bash_defaults_disabled_and_never_spawns_shell_metacharacters(tmp_path: Path) -> None:
    async def scenario() -> None:
        root = tmp_path / "workspace"
        root.mkdir()
        (root / "visible.txt").write_text("ok", encoding="utf-8")
        workspace = SafeWorkspace(root)

        disabled = RestrictedBashTool(workspace, enabled=False, allowed_commands=[])
        result = await disabled.call(json.dumps({"command": "pwd"}))
        assert "默认关闭" in result

        enabled = RestrictedBashTool(workspace, enabled=True, allowed_commands=[])
        pwd = await enabled.call(json.dumps({"command": "pwd"}))
        assert Path(pwd) == root.resolve()
        listed = await enabled.call(json.dumps({"command": "ls"}))
        assert listed == "visible.txt"
        blocked = await enabled.call(json.dumps({"command": "ls | more"}))
        assert "不允许 shell chaining" in blocked
        disallowed = await enabled.call(json.dumps({"command": "python -c pass"}))
        assert "命令不在允许列表" in disallowed

    asyncio.run(scenario())


def test_restricted_bash_process_lifecycle_propagates_cancellation(tmp_path: Path) -> None:
    class BlockingStream:
        async def read(self, _: int) -> bytes:
            await asyncio.Future()
            return b""

    class FakeProcess:
        def __init__(self) -> None:
            self.stdout = BlockingStream()
            self.returncode: int | None = None
            self.terminated = False

        def kill(self) -> None:
            self.terminated = True
            self.returncode = -9

        async def wait(self) -> int:
            return self.returncode or 0

    async def scenario() -> None:
        root = tmp_path / "workspace"
        root.mkdir()
        tool = RestrictedBashTool(SafeWorkspace(root), enabled=True, allowed_commands=[])
        process = FakeProcess()
        task = asyncio.create_task(tool._finish_process(process, 30.0))  # type: ignore[arg-type]
        await asyncio.sleep(0)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        else:
            raise AssertionError("cancelled process lifecycle must propagate cancellation")
        assert process.terminated is True

    asyncio.run(scenario())


def test_restricted_bash_process_lifecycle_enforces_output_limit(tmp_path: Path) -> None:
    class OversizedStream:
        def __init__(self) -> None:
            self.sent = False

        async def read(self, _: int) -> bytes:
            if self.sent:
                return b""
            self.sent = True
            return b"0123456789"

    class FakeProcess:
        def __init__(self) -> None:
            self.stdout = OversizedStream()
            self.returncode: int | None = None
            self.terminated = False

        def kill(self) -> None:
            self.terminated = True
            self.returncode = -9

        async def wait(self) -> int:
            if self.returncode is None:
                self.returncode = 0
            return self.returncode

    async def scenario() -> None:
        root = tmp_path / "workspace"
        root.mkdir()
        tool = RestrictedBashTool(
            SafeWorkspace(root),
            enabled=True,
            allowed_commands=[],
            max_output_bytes=5,
        )
        process = FakeProcess()
        result = await tool._finish_process(process, 30.0)  # type: ignore[arg-type]

        assert result.startswith("01234")
        assert "output truncated; process terminated" in result
        assert process.terminated is True

    asyncio.run(scenario())


def test_skills_settings_parse_comma_separated_directories_and_commands() -> None:
    settings = Settings(
        skills_directories="./skills-a, ./skills-b",
        skills_bash_allowed_commands="git, custom-readonly",
    )

    assert settings.skills_directory_list == ["./skills-a", "./skills-b"]
    assert settings.skills_bash_allowed_command_list == ["git", "custom-readonly"]
