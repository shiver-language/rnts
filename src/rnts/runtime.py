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
