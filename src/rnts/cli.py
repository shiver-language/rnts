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

import importlib.util
import sys
from pathlib import Path
from typing import Callable, cast
import shutil
from rich import print
from rich.markup import escape
from rnts.decorators import compute_dir_hash
from .context import output_channel
from .models import Module

sys.pycache_prefix = "/out/rnts/pycache/"


def load_user_build_file() -> bool:
    """Looks for and dynamically executes the user's build script to populate the registry."""
    build_path = Path.cwd() / "build.py"
    if build_path.exists():
        spec = importlib.util.spec_from_file_location("rnts_user_config", build_path)
        if spec and spec.loader:
            user_module = importlib.util.module_from_spec(spec)
            # excludes this file
            # we dont want it to run this
            spec.loader.exec_module(user_module)
            return True
    return False


def main() -> None:
    sys.dont_write_bytecode = True
    if len(sys.argv) < 2:
        print("Usage: rnts <module_name>.<command_name>")
        sys.exit(1)

    lock_path = Path.cwd() / "out" / ".rnts.lock"
    rnts_path = Path.cwd() / "out" / "rnts"

    try:
        # detect / write lock file
        if lock_path.is_file():
            print("[red][RNTS] Another RNTS instance is running[/red]")
            print(
                f"[red][RNTS] If you are certain that it is not, delete {lock_path}[/red]"
            )
            sys.exit(1)

        # find and load the build file
        if not load_user_build_file():
            print(
                "[red][RNTS] Error: No 'build.py' found in the current directory.[/red]"
            )
            sys.exit(1)

        lock_path.parent.mkdir(parents=True, exist_ok=True)
        lock_path.touch()

        # invalidate all hashes if the build script had been changed
        rnts_path.mkdir(exist_ok=True)
        build_hash_file = rnts_path / "build_hash"
        build_hash = compute_dir_hash(Path.cwd() / "build.py")
        if build_hash_file.is_file():
            if build_hash != build_hash_file.read_text(encoding="utf-8"):
                shutil.rmtree(Path.cwd() / "out" / "hashes")
                shutil.rmtree(Path.cwd() / "out" / "modules")
                _ = build_hash_file.write_text(build_hash, encoding="utf-8")
        else:
            _ = build_hash_file.touch()
            _ = build_hash_file.write_text(build_hash, encoding="utf-8")

        target = sys.argv[1]
        if "." not in target:
            print(
                f"[red][RNTS] Error: Invalid target format '{escape(target)}'. Use 'module_name.command_name'.[/red]"
            )
            sys.exit(1)

        mod_name, cmd_name = target.split(".", 1)

        # look up modules
        module_instance = Module.get_module(mod_name)
        if not module_instance:
            available_mods = list(Module._registry.keys())  # pyright: ignore[reportPrivateUsage]
            print(f"[red][RNTS] Error: Module '{escape(mod_name)}' not found.[/red]")
            print(
                f"[yellow][RNTS] Registered modules: {escape(str(available_mods))}[/yellow]"
            )
            sys.exit(1)

        # look up the task or commands
        if not hasattr(module_instance, cmd_name):
            print(
                f"[red][RNTS] Error: Command or Task '{escape(cmd_name)}' not found on module '{escape(mod_name)}'.[/red]"
            )
            sys.exit(1)

        # too satisfy pyright
        task_func = cast(Callable[[], None], getattr(module_instance, cmd_name))

        # run this
        try:
            print(
                f"[blue][RNTS] Running this: {escape(mod_name)}.{escape(cmd_name)}...[/blue]"
            )
            task_func()

            # block until all async channel logs finish printing
            output_channel.wait_completion()
            print("[green][RNTS] This ran successfully.[/green]")
        except Exception as e:
            output_channel.wait_completion()
            print(f"[red][RNTS] This failed with an exception: {escape(str(e))}[/red]")
            sys.exit(1)
    finally:
        lock_path.unlink()


if __name__ == "__main__":
    main()
