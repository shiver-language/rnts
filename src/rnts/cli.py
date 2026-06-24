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
from .models import Module
from .context import output_channel


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

    try:
        # detect / write lock file
        if lock_path.is_file():
            print("\033[91m[RNTS] Another RNTS instance is running\033[0m")
            print(
                "\033[91m[RNTS] If you are certain that it is not, delete "
                + str(lock_path)
                + "\033[0m"
            )
            sys.exit(1)

        lock_path.parent.mkdir(parents=True, exist_ok=True)
        lock_path.touch()

        # find and load the build file
        if not load_user_build_file():
            print(
                "\033[91m[RNTS] Error: No 'build.py' found in the current directory.\033[0m"
            )
            sys.exit(1)

        target = sys.argv[1]
        if "." not in target:
            print(
                f"\033[91m[RNTS] Error: Invalid target format '{target}'. Use 'module_name.command_name'.\033[0m"
            )
            sys.exit(1)

        mod_name, cmd_name = target.split(".", 1)

        # look up modules
        module_instance = Module.get_module(mod_name)
        if not module_instance:
            available_mods = list(Module._registry.keys())  # pyright: ignore[reportPrivateUsage]
            print(f"\033[91m[RNTS] Error: Module '{mod_name}' not found.\033[0m")
            print(f"\033[93m[RNTS] Registered modules: {available_mods}\033[0m")
            sys.exit(1)

        # look up the task or commands
        if not hasattr(module_instance, cmd_name):
            print(
                f"\033[91m[RNTS] Error: Command or Task '{cmd_name}' not found on module '{mod_name}'.\033[0m"
            )
            sys.exit(1)

        # too satisfy pyright
        task_func = cast(Callable[[], None], getattr(module_instance, cmd_name))

        # run this
        try:
            print(f"\033[94m[RNTS] Running this: {mod_name}.{cmd_name}...\033[0m")
            task_func()

            # block until all async channel logs finish printing
            output_channel.wait_completion()
            print("\033[92m[RNTS] This ran successfully.\033[0m")
        except Exception as e:
            output_channel.wait_completion()
            print(f"\033[91m[RNTS] This failed with an exception: {e}\033[0m")
            sys.exit(1)
    finally:
        lock_path.unlink()


if __name__ == "__main__":
    main()
