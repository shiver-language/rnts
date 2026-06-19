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
from pathlib import Path


class RntsRuntime:
    @staticmethod
    def sh(
        args: list[str],
        cwd: Path | None = None,
        env: dict[str, str] | None = None,
        inherit_stdout: bool = False,
    ) -> subprocess.CompletedProcess[bytes]:
        stdout = None if inherit_stdout else subprocess.PIPE
        return subprocess.run(args, cwd=cwd, env=env, stdout=stdout, check=True)

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


rnts = RntsRuntime()
