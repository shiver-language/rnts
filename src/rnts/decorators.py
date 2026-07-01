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

import functools
import io
import hashlib
import json
from pathlib import Path
import threading
from typing import Callable, TypeVar, ParamSpec, Concatenate, cast, overload
from filelock import FileLock
import dill  # pyright: ignore[reportMissingTypeStubs]
import base64
from datetime import datetime
from rich import print
from rich.markup import escape
from .context import (
    ctx,
    output_channel,
    task_stderr_buffer,
    task_stdout_buffer,
    task_interactive,
)
from .models import Module

P = ParamSpec("P")
R = TypeVar("R")
M = TypeVar("M", bound=Module)


class ProcessCache:
    def __init__(self) -> None:
        self._storage: dict[tuple[str, str], object] = {}
        self._lock: threading.RLock = threading.RLock()

    def get(self, module_name: str, func_name: str) -> object | None:
        with self._lock:
            return self._storage.get((module_name, func_name))

    def set(self, module_name: str, func_name: str, value: object) -> None:
        with self._lock:
            self._storage[(module_name, func_name)] = value

    def has(self, module_name: str, func_name: str) -> bool:
        with self._lock:
            return (module_name, func_name) in self._storage

    def clear(self) -> None:
        with self._lock:
            self._storage.clear()


# cache for process results keyed by module name and function name
_PROCESS_CACHE = ProcessCache()


def compute_dir_hash(path: Path) -> str:
    # return empty string if path does not exist
    if not path.exists():
        return ""

    hasher = hashlib.md5()

    if path.is_file():
        # a single file
        with open(path, "rb") as f:
            while chunk := f.read(65536):
                hasher.update(chunk)

    elif path.is_dir():
        # sort paths to ensure deterministic hashing for directories
        for sub_path in sorted(path.rglob("*")):
            if sub_path.is_file():
                # hash the relative path string to catch file moves/renames
                hasher.update(str(sub_path.relative_to(path)).encode("utf-8"))
                # read file in chunks to avoid blowing up the RAM
                with open(sub_path, "rb") as f:
                    while chunk := f.read(65536):
                        hasher.update(chunk)
    else:
        raise Exception("Hashing Error")

    return hasher.hexdigest()


def _serialize_val(val: object) -> str:
    binary_data = dill.dumps(val)  # pyright: ignore[reportUnknownMemberType]
    return base64.b64encode(binary_data).decode("utf-8")


def _deserialize_val(val: object) -> object:
    if isinstance(val, str):
        binary_data = base64.b64decode(val.encode("utf-8"))
        return cast(object, dill.loads(binary_data))  # pyright: ignore[reportUnknownMemberType]
    return val


def _rotate_and_write_log(
    module_name: str, task_name: str, stdout_text: str, stderr_text: str
) -> None:
    # skip if there are no logs to write
    if not stdout_text and not stderr_text:
        return

    # make the log dir
    log_dir = Path.cwd() / "out" / "logs" / module_name / task_name
    log_dir.mkdir(parents=True, exist_ok=True)

    # using timestamp as log name
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    log_file = log_dir / f"{timestamp}.log"

    with open(log_file, "w", encoding="utf-8") as f:
        if stdout_text:
            _ = f.write("--- stdout ---\n")
            _ = f.write(stdout_text)
            if not stdout_text.endswith("\n"):
                _ = f.write("\n")
        if stderr_text:
            _ = f.write("--- stderr ---\n")
            _ = f.write(stderr_text)
            if not stderr_text.endswith("\n"):
                _ = f.write("\n")

    # rotate logs, keeping only the 5 most recent
    max_logs = 5
    existing_logs = sorted(log_dir.glob("*.log"))
    if len(existing_logs) > max_logs:
        for old_log in existing_logs[:-max_logs]:
            try:
                old_log.unlink()
            except Exception:
                pass


class CacheManager:
    """Manages reading, verifying, and writing metadata caches for tasks."""

    def __init__(self, module: Module, func_name: str) -> None:
        self.module_name: str = module.module_name
        self.func_name: str = func_name
        self.module_class_name: str = module.__class__.__name__

        self.out_base: Path = (
            Path.cwd() / "out" / "modules" / self.module_class_name / self.module_name
        )
        self.meta_file: Path = (
            Path.cwd()
            / "out"
            / "hashes"
            / self.module_class_name
            / self.module_name
            / f"{func_name}.json"
        )

    def check_cache_validity(self) -> tuple[bool, object | None]:
        if not self.meta_file.exists():
            return False, None

        try:
            meta_lock = FileLock(f"{self.meta_file}.lock")
            with meta_lock:
                meta = cast(dict[str, object], json.loads(self.meta_file.read_text()))

            # verify tracked source file hashes
            sources = meta.get("sources")
            if isinstance(sources, list):
                for src_item in cast(list[object], sources):
                    if isinstance(src_item, list):
                        typed_src = cast(list[object], src_item)
                        if len(typed_src) == 3:
                            src_mod_name, src_name, expected_hash = typed_src

                            mod = Module.get_module(str(src_mod_name))
                            if not mod:
                                return False, None

                            cast(Callable[[], None], getattr(mod, str(src_name)))()

                            curr_hash_file = (
                                Path.cwd()
                                / "out"
                                / "hashes"
                                / mod.__class__.__name__
                                / str(src_mod_name)
                                / str(src_name)
                            )

                            hash_lock = FileLock(f"{curr_hash_file}.lock")
                            with hash_lock:
                                if not curr_hash_file.exists():
                                    return False, None
                                curr_hash_val = curr_hash_file.read_text().strip()

                            if curr_hash_val != str(expected_hash):
                                return False, None
                    else:
                        return False, None

            # verify output values of upstream tasks
            tasks = meta.get("tasks")
            if isinstance(tasks, list):
                for task_item in cast(list[object], tasks):
                    if isinstance(task_item, list):
                        typed_task = cast(list[object], task_item)
                        if len(typed_task) == 3:
                            dep_mod_name, dep_task_name, expected_val_serialized = (
                                typed_task
                            )

                            mod = Module.get_module(str(dep_mod_name))
                            if not mod:
                                return False, None

                            curr_task = cast(
                                Callable[[], object], getattr(mod, str(dep_task_name))
                            )
                            curr_val = curr_task()

                            if _serialize_val(curr_val) != expected_val_serialized:
                                return False, None
                    else:
                        return False, None

            return True, meta.get("return_value")

        except Exception:
            return False, None

    def write_cache(self, result: object) -> object:
        deps = ctx.get_dependencies(self.module_name, self.func_name)
        serialized_res = _serialize_val(result)
        meta_data = {
            "sources": deps["sources"],
            "tasks": deps["tasks"],
            "return_value": serialized_res,
        }

        self.meta_file.parent.mkdir(parents=True, exist_ok=True)

        meta_lock = FileLock(f"{self.meta_file}.lock")
        with meta_lock:
            _ = self.meta_file.write_text(json.dumps(meta_data, indent=4))

        return serialized_res


def task(func: Callable[Concatenate[M, P], R]) -> Callable[Concatenate[M, P], R]:
    # decorator to cache and track build tasks based on dependencies
    @functools.wraps(func)
    def wrapper(self: M, *args: P.args, **kwargs: P.kwargs) -> R:
        if _PROCESS_CACHE.has(self.module_name, func.__name__):
            return cast(R, _PROCESS_CACHE.get(self.module_name, func.__name__))

        cache_mgr = CacheManager(self, func.__name__)
        is_valid, serialized_val = cache_mgr.check_cache_validity()

        if is_valid:
            cached_res = _deserialize_val(serialized_val)
            _PROCESS_CACHE.set(self.module_name, func.__name__, cached_res)
            ctx.record_upstream_hit(self.module_name, func.__name__, serialized_val)
            return cast(R, cached_res)

        # notify task start in terminal
        print(
            f"[blue][RNTS] Running this: {escape(self.module_name)}.{escape(func.__name__)}...[/blue]"
        )

        # setup string buffers for current thread context
        stdout_buf = io.StringIO()
        stderr_buf = io.StringIO()
        token_out = task_stdout_buffer.set(stdout_buf)
        token_err = task_stderr_buffer.set(stderr_buf)

        # force interactive off for background tasks so they always buffer correctly
        # this stops gather() threads from leaking into an interactive stdout
        token_interactive = task_interactive.set(False)

        # doesn't exist, lets run the underlying task
        ctx.push_task(self.module_name, func.__name__)
        out_dir = cache_mgr.out_base / func.__name__
        out_dir.mkdir(parents=True, exist_ok=True)

        try:
            with ctx.set_dest(out_dir):
                result = func(self, *args, **kwargs)

            _PROCESS_CACHE.set(self.module_name, func.__name__, result)
            serialized_res = cache_mgr.write_cache(result)
            ctx.record_upstream_miss(self.module_name, func.__name__, serialized_res)
            return result
        finally:
            ctx.pop_task()
            # reset context vars
            task_interactive.reset(token_interactive)
            task_stdout_buffer.reset(token_out)
            task_stderr_buffer.reset(token_err)

            stdout_val = stdout_buf.getvalue()
            stderr_val = stderr_buf.getvalue()

            # write task logs to disk and rotate old ones
            _rotate_and_write_log(
                self.module_name, func.__name__, stdout_val, stderr_val
            )

            # offload task logs as a single batch to the channel
            # then it will be printed sometimes in future
            output_channel.put("stdout", stdout_val)
            output_channel.put("stderr", stderr_val)

    setattr(wrapper, "__is_rnts_task__", True)
    return cast(Callable[Concatenate[M, P], R], wrapper)


def source(func: Callable[[M], Path]) -> Callable[[M], Path]:
    @functools.wraps(func)
    def wrapper(self: M) -> Path:
        src_dir = func(self)
        current_hash = compute_dir_hash(self.module_dir / src_dir)

        hash_file = (
            Path.cwd()
            / "out"
            / "hashes"
            / self.__class__.__name__
            / self.module_name
            / func.__name__
        )
        hash_file.parent.mkdir(parents=True, exist_ok=True)

        hash_lock = FileLock(f"{hash_file}.lock")
        with hash_lock:
            _ = hash_file.write_text(current_hash)

        ctx.record_source(self.module_name, func.__name__, current_hash)
        return src_dir

    return wrapper


@overload
def command(func: Callable[Concatenate[M, P], R]) -> Callable[Concatenate[M, P], R]: ...


@overload
def command(
    *, interactive: bool
) -> Callable[[Callable[Concatenate[M, P], R]], Callable[Concatenate[M, P], R]]: ...


def command(
    func: Callable[Concatenate[M, P], R] | None = None,
    *,
    interactive: bool = False,
) -> (
    Callable[Concatenate[M, P], R]
    | Callable[[Callable[Concatenate[M, P], R]], Callable[Concatenate[M, P], R]]
):
    def decorator(fn: Callable[Concatenate[M, P], R]) -> Callable[Concatenate[M, P], R]:
        @functools.wraps(fn)
        def wrapper(self: M, *args: P.args, **kwargs: P.kwargs) -> R:
            # toggle interactive mode for stream proxy
            token = task_interactive.set(interactive)
            ctx.push_task(self.module_name, fn.__name__)
            out_dir = (
                Path.cwd()
                / "out"
                / "modules"
                / self.__class__.__name__
                / self.module_name
                / fn.__name__
            )
            out_dir.mkdir(parents=True, exist_ok=True)
            try:
                with ctx.set_dest(out_dir):
                    return fn(self, *args, **kwargs)
            finally:
                ctx.pop_task()
                task_interactive.reset(token)

        return cast(Callable[Concatenate[M, P], R], wrapper)

    if func is None:
        return decorator
    return decorator(func)
