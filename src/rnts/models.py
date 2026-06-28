#          Copyright 2026 Shiver Contributors
#
#  Licensed under the Apache License, Version 2.0 (the "License");
#  you may not use this file except in compliance with the License.
#  You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
#  Unless required by applicable law or agreed to in writing, software
#  distributed under the License is distributed on an "AS IS" BASIS,
#  WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#  See the License for the specific language governing permissions and
#  limitations under the License.

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

    def __init__(self, name: str):
        if not name or not name.strip():
            raise ValueError(
                "Module 'name' must be explicitly defined and cannot be empty."
            )

        if name in Module._registry:
            raise ValueError(
                f"Module name '{name}' is already registered. Module names must be unique."
            )

        self.module_name = name
        # source base starts directly at the project workspace root / module name
        self.module_dir = Path.cwd() / name
        Module._registry[self.module_name] = self

    @classmethod
    def get_module(cls, name: str) -> Module | None:
        return cls._registry.get(name)
