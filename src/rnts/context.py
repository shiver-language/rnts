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

from contextlib import contextmanager
from pathlib import Path
from collections.abc import Generator
from contextvars import ContextVar
from typing import TextIO, cast
import sys
import threading
import queue
import io

task_stdout_buffer: ContextVar[io.StringIO | None] = ContextVar(
    "task_stdout_buffer", default=None
)
task_stderr_buffer: ContextVar[io.StringIO | None] = ContextVar(
    "task_stderr_buffer", default=None
)
# tracks if the current execution stack allows direct terminal interaction
task_interactive: ContextVar[bool] = ContextVar("task_interactive", default=False)


class OutputChannel:
    # for printing logs by batch
    def __init__(self) -> None:
        self._queue: queue.Queue[tuple[str, str]] = queue.Queue()
        self._consumer_thread: threading.Thread = threading.Thread(
            target=self._consume, daemon=True
        )
        self._consumer_thread.start()

    def put(self, stream_type: str, text: str) -> None:
        if text:
            self._queue.put((stream_type, text))

    def _consume(self) -> None:
        while True:
            stream_type, text = self._queue.get()
            try:
                if stream_type == "stdout" and sys.__stdout__ is not None:
                    _ = sys.__stdout__.write(text)
                    sys.__stdout__.flush()
                elif stream_type == "stderr" and sys.__stderr__ is not None:
                    _ = sys.__stderr__.write(text)
                    sys.__stderr__.flush()
                else:
                    print("Fail to write to stdout or stderr.")
            except Exception:
                pass
            finally:
                self._queue.task_done()

    def wait_completion(self) -> None:
        # blocks until all logs are printed
        self._queue.join()


output_channel = OutputChannel()


class ContextStream:
    # proxies writes to a context specific buffer if active
    # otherwise go back to original

    def __init__(
        self,
        original_stream: TextIO,
        context_var: ContextVar[io.StringIO | None],
    ) -> None:
        self.original_stream: TextIO = original_stream
        self.context_var: ContextVar[io.StringIO | None] = context_var

    def write(self, text: str) -> int:
        buf = self.context_var.get()
        # bypass buffer if interactive mode is set
        if buf is not None and not task_interactive.get():
            return buf.write(text)
        _ = self.original_stream.write(text)
        return len(text)

    def flush(self) -> None:
        buf = self.context_var.get()
        # bypass buffer if interactive mode is set
        if buf is not None and not task_interactive.get():
            buf.flush()
        else:
            self.original_stream.flush()

    def __getattr__(self, name: str) -> object:
        return cast(object, getattr(self.original_stream, name))


# it might be none
sys.stdout = cast(TextIO, cast(object, ContextStream(sys.stdout, task_stdout_buffer)))
sys.stderr = cast(TextIO, cast(object, ContextStream(sys.stderr, task_stderr_buffer)))


class TaskContext:
    # current build destination path
    _dest_var: ContextVar[Path | None] = ContextVar("dest", default=None)

    # stack to track active tasks
    _stack_var: ContextVar[list[tuple[str, str]]] = ContextVar("task_stack")
    # task keys -> source and task dependencies
    _deps_var: ContextVar[dict[tuple[str, str], dict[str, list[object]]]] = ContextVar(
        "tracked_deps"
    )

    # thread local storage to track build context across threads
    def __init__(self) -> None:
        if not self._has_context():
            _ = self._stack_var.set([])
            _ = self._deps_var.set({})

    def _has_context(self) -> bool:
        try:
            _ = self._stack_var.get()
            return True
        except LookupError:
            return False

    @property
    def dest(self) -> Path:
        dest = self._dest_var.get()
        if dest is None:
            raise RuntimeError("ctx.dest accessed outside of an active task execution.")
        return dest

    @dest.setter
    def dest(self, path: Path) -> None:
        _ = self._dest_var.set(path)
        return None

    @contextmanager
    def set_dest(self, path: Path) -> Generator[None, None, None]:
        # temporarily override the destination path and restore it after
        token = self._dest_var.set(path)
        try:
            yield
        finally:
            self._dest_var.reset(token)

    def push_task(self, module_name: str, task_name: str) -> None:
        # make new task on the execution stack and init tracking maps
        key = (module_name, task_name)

        # shallow copy stack so child contexts don't mutate parent context stacks
        current_stack = list(self._stack_var.get())
        current_stack.append(key)
        _ = self._stack_var.set(current_stack)

        current_deps = dict(self._deps_var.get())
        current_deps[key] = {"sources": [], "tasks": []}
        _ = self._deps_var.set(current_deps)

    def pop_task(self) -> None:
        # p u r g e the top task from the stack once execution is done
        current_stack = list(self._stack_var.get())
        if current_stack:
            _ = current_stack.pop()
            _ = self._stack_var.set(current_stack)

    def record_source(self, mod_name: str, fn_name: str, current_hash: str) -> None:
        stack = self._stack_var.get()
        if stack:
            active_key = stack[-1]
            deps = self._deps_var.get()
            record: list[object] = [mod_name, fn_name, current_hash]
            # do not duplicate identical source records
            if record not in deps[active_key]["sources"]:
                deps[active_key]["sources"].append(record)

    def record_upstream_hit(
        self, mod_name: str, fn_name: str, serialized_val: object
    ) -> None:
        # log a cache hit into current task deps
        stack = self._stack_var.get()
        if stack:
            parent_key = stack[-1]
            deps = self._deps_var.get()
            record: list[object] = [mod_name, fn_name, serialized_val]
            deps[parent_key]["tasks"].append(record)

    def record_upstream_miss(
        self, mod_name: str, fn_name: str, serialized_val: object
    ) -> None:
        # log a cache miss into parent task as it started this subtask
        stack = self._stack_var.get()
        if len(stack) > 1:
            parent_key = stack[-2]
            deps = self._deps_var.get()
            record: list[object] = [mod_name, fn_name, serialized_val]
            deps[parent_key]["tasks"].append(record)

    def get_dependencies(
        self, module_name: str, task_name: str
    ) -> dict[str, list[object]]:
        # get collected source and task dependencies for a specific task
        return self._deps_var.get().get(
            (module_name, task_name), {"sources": [], "tasks": []}
        )


# global thread local for context management
ctx = TaskContext()
