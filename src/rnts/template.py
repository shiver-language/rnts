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
from types import ModuleType
import urllib.request
import sys
from pathlib import Path


def load_template(url: str, template_name: str) -> ModuleType:
    """Fetches a remote template, caches it, and loads it into the registry."""
    cache_dir = Path.cwd() / "out" / "templates"
    cache_dir.mkdir(parents=True, exist_ok=True)

    template_file = cache_dir / f"{template_name}.py"

    if not template_file.exists():
        print(
            f"\033[94m[RNTS] Pulling template '{template_name}' from remote...\033[0m"
        )
        try:
            _ = urllib.request.urlretrieve(url, template_file)
        except Exception as e:
            print(
                f"\033[91m[RNTS] Failed to download template '{template_name}': {e}\033[0m"
            )
            sys.exit(1)

    spec = importlib.util.spec_from_file_location(template_name, template_file)
    if spec and spec.loader:
        template_module = importlib.util.module_from_spec(spec)

        # inject it into sys.modules so the rest of the program can use it
        sys.modules[template_name] = template_module

        try:
            spec.loader.exec_module(template_module)
            return template_module
        except Exception as e:
            print(
                f"\033[91m[RNTS] Failed to execute template '{template_name}': {e}\033[0m"
            )
            sys.exit(1)

    raise ImportError(
        f"Could not load or resolve module spec for template '{template_name}'."
    )
