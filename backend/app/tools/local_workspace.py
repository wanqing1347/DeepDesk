from pathlib import Path


class WorkspaceBoundaryError(ValueError):
    """Raised when a local tool tries to escape its configured workspace root."""


class SafeWorkspace:
    def __init__(self, root: str | Path) -> None:
        raw_root = Path(root).expanduser()
        self._root = raw_root.resolve(strict=False)

    @property
    def root(self) -> Path:
        return self._root

    def ensure_root(self) -> Path:
        self._root.mkdir(parents=True, exist_ok=True)
        return self._root

    def resolve(self, path: str | None, *, must_exist: bool = False) -> Path:
        raw = str(path or ".").strip() or "."
        if raw.startswith("~"):
            raise WorkspaceBoundaryError(f"Path traversal not allowed: {raw}")

        candidate_path = Path(raw)
        candidate = candidate_path if candidate_path.is_absolute() else self._root / candidate_path
        resolved = candidate.resolve(strict=False)
        if not resolved.is_relative_to(self._root):
            raise WorkspaceBoundaryError(f"Path {resolved} outside workspace root: {self._root}")
        if must_exist and not resolved.exists():
            raise FileNotFoundError(f"Path does not exist: {raw}")
        return resolved

    def display(self, path: Path) -> str:
        resolved = path.resolve(strict=False)
        if not resolved.is_relative_to(self._root):
            raise WorkspaceBoundaryError(f"Path {resolved} outside workspace root: {self._root}")
        relative = resolved.relative_to(self._root)
        return "." if not relative.parts else relative.as_posix()
