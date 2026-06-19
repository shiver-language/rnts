from pathlib import Path
from typing import final, override, ClassVar


@final
class PathRef:
    """Wraps a path and handles hashing for change-detection."""

    def __init__(self, path: Path | str):
        self.path = Path(path)

    @override
    def __repr__(self) -> str:
        return f"PathRef({self.path})"


class Module:
    """Base class for organizing groups of related tasks."""

    module_name: str
    module_dir: Path
    _registry: ClassVar[dict[str, "Module"]] = {}

    def __init__(self, name: str | None = None):
        self.module_name = name or self.__class__.__name__
        self.module_dir = Path.cwd()
        Module._registry[self.module_name] = self

    @classmethod
    def get_module(cls, name: str) -> "Module | None":
        """Public accessor lookup to bypass explicit internal dictionary checks."""
        return cls._registry.get(name)
