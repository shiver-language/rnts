import threading
from contextlib import contextmanager
from pathlib import Path
from collections.abc import Generator


class TaskContext(threading.local):
    def __init__(self) -> None:
        self._dest: Path | None = None
        self._task_stack: list[tuple[str, str]] = []
        self._tracked_deps: dict[tuple[str, str], dict[str, list[object]]] = {}

    @property
    def dest(self) -> Path:
        if self._dest is None:
            raise RuntimeError("ctx.dest accessed outside of an active task execution.")
        return self._dest

    @dest.setter
    def dest(self, path: Path) -> None:
        self._dest = path

    @contextmanager
    def set_dest(self, path: Path) -> Generator[None, None, None]:
        old_dest = self._dest
        self._dest = path
        try:
            yield
        finally:
            self._dest = old_dest

    def push_task(self, module_name: str, task_name: str) -> None:
        key = (module_name, task_name)
        self._task_stack.append(key)
        self._tracked_deps[key] = {"sources": [], "tasks": []}

    def pop_task(self) -> None:
        if self._task_stack:
            _ = self._task_stack.pop()

    def record_source(self, mod_name: str, fn_name: str, current_hash: str) -> None:
        if self._task_stack:
            active_key = self._task_stack[-1]
            record: list[object] = [mod_name, fn_name, current_hash]
            if record not in self._tracked_deps[active_key]["sources"]:
                self._tracked_deps[active_key]["sources"].append(record)

    def record_upstream_hit(
        self, mod_name: str, fn_name: str, serialized_val: object
    ) -> None:
        if self._task_stack:
            parent_key = self._task_stack[-1]
            record: list[object] = [mod_name, fn_name, serialized_val]
            self._tracked_deps[parent_key]["tasks"].append(record)

    def record_upstream_miss(
        self, mod_name: str, fn_name: str, serialized_val: object
    ) -> None:
        if len(self._task_stack) > 1:
            parent_key = self._task_stack[-2]
            record: list[object] = [mod_name, fn_name, serialized_val]
            self._tracked_deps[parent_key]["tasks"].append(record)

    def get_dependencies(
        self, module_name: str, task_name: str
    ) -> dict[str, list[object]]:
        return self._tracked_deps.get(
            (module_name, task_name), {"sources": [], "tasks": []}
        )


ctx = TaskContext()
