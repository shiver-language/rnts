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

import subprocess
import shutil
import os
import concurrent.futures
import sys
import contextvars
from pathlib import Path
from typing import Callable, TypeVar

T = TypeVar("T")


# pyright doesn't like the original way of doing it since it is on strict mode
# so we are going to use this helper function
def _run_with_context(ctx: contextvars.Context, task_func: Callable[[], T]) -> T:
    return ctx.run(task_func)


class RntsRuntime:
    def __init__(self) -> None:
        cores = os.cpu_count() or 1
        self._executor: concurrent.futures.ThreadPoolExecutor = (
            concurrent.futures.ThreadPoolExecutor(max_workers=cores)
        )

    @staticmethod
    def sh(
        args: list[str],
        cwd: Path | None = None,
        env: dict[str, str] | None = None,
        inherit_stdout: bool = False,
    ) -> subprocess.CompletedProcess[bytes]:
        if inherit_stdout:
            res = subprocess.run(
                args, cwd=cwd, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE
            )

            # feed data to context interceptor proxy
            if res.stdout:
                _ = sys.stdout.write(res.stdout.decode(errors="replace"))
            if res.stderr:
                _ = sys.stderr.write(res.stderr.decode(errors="replace"))

            if res.returncode != 0:
                raise subprocess.CalledProcessError(
                    res.returncode, args, output=res.stdout, stderr=res.stderr
                )
            return res
        else:
            return subprocess.run(
                args, cwd=cwd, env=env, stdout=subprocess.PIPE, check=True
            )

    @staticmethod
    def cp(src: Path, dest: Path) -> None:
        if src.is_dir():
            _ = shutil.copytree(src, dest, dirs_exist_ok=True)
        else:
            _ = shutil.copy2(src, dest)

    @staticmethod
    def join_paths(paths: list[str]) -> str:
        return os.pathsep.join(paths)

    @staticmethod
    def relativize(path: Path) -> Path:
        """Returns path relative to workspace root directory safely."""
        try:
            return path.relative_to(Path.cwd())
        except ValueError:
            return path

    def gather(self, *tasks: Callable[[], T]) -> list[T]:
        """
        Executes multiple task functions concurrently using the shared,
        process-wide ThreadPoolExecutor.
        """
        results: list[T] = []
        futures: list[concurrent.futures.Future[T]] = []

        for task_func in tasks:
            ctx = contextvars.copy_context()

            future = self._executor.submit(_run_with_context, ctx, task_func)
            futures.append(future)

        for future in futures:
            results.append(future.result())

        return results


rnts = RntsRuntime()
