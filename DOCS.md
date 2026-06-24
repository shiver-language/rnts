# Project Setup and Structure

To create an `rnts` project, you need a specific directory structure with alongside
the configuration script named `build.py`.

## Directory Structure

Root of your workspace should contain a `build.py` file. Each module defined in said build file 
will look for it's source files in a directory with the module's name.

```
my_workspace/
├── build.py           # the build script
├── backend/           # source directory for the 'backend' module
│   └── main.go
└── frontend/          # source directory for the 'frontend' module
    └── index.html
```

## Writing `build.py`

You define build modules and their tasks in `build.py`. This file is loaded dynamically and 
executed by the CLI.

```python
from pathlib import Path
from rnts.models import Module
from rnts.decorators import command, task, source
from rnts.runtime import rnts
from rnts.context import ctx

class BackendModule(Module):
    def __init__(self):
        # "backend" is the module_name, corresponding to the ./backend directory
        super().__init__("backend")

    @source
    def get_sources(self) -> Path:
        # returns the directory to be hashed and tracked
        return Path(".")

    @task
    def compile(self):
        # make sure that this task depends on a source
        src_dir = self.get_sources()
        # ctx.dest is the automatically managed output directory
        rnts.sh(["go", "build", "-o", str(ctx.dest / "app")], cwd=self.module_dir)
        return ctx.dest / "app"

    @command
    def build(self):
        # @command means a task that is not cached
        binary_path = self.compile()
        print(f"build complete at: {binary_path}")

# instantiate the module to register it with the CLI
BackendModule()
```

## Core Concepts & Decorators

The build graph is constructed using 3 decorators. These define how tasks are ran, trakced and cached.

| Decorator | Purpose | Caching Behavior |
| --- | --- | --- |
| `@command` | CLI entry point. Sets up the initial execution context and destination directory. | It will not be cached. Runs every time invoked. |
| `@task` | Executes build logic, manages dependencies, and returns results. | Cached. Does not run if source hashes and upstream task outputs haven't changed. |
| `@source` | Tracks input directories/files. Hashes directory contents with MD5. | Determines cache. Hashes are compared to previous execution to determine if tasks depending on it will run or not. |

## `CacheManager` & `ProcessCache`

When a `@task` is called, `rnts` performs two cache checks:

1. `ProcessCache`: Checks if the task is already ran during current CLI execution, if so it will return 
the value immediately.
2. `CacheManager`: It reads a `.json` metadata file in `out/hashes/`. It checks the hashes of any `@source`
directories and the return values of any upstraem `@task` dependencies. If everything matches, it deserializes 
the previous result and skips execution.

## `ctx`

`rnts` runs on a variable tracker called `TaskContext` (imported as `ctx`). This allows functions to know where 
they are writing data and who called them.

- `ctx.dest`: Every `@command` and `@task` is assigned an isolated output directory located in `out/modules/<ClassName>/<module_name>/<task_name>`. You must write your build artifacts to `ctx.dest`.
- Execution Stack: `ctx` maintains a stack of active tasks (`push_task`, `pop_task`). This allows `rnts` to implicitly build a dependency tree. If `task a` calls `task b`, `task b` is automatically recorded as an upstream dependency of `task a`.


## Runtime

The `RntsRuntime` class (imported as the `rnts` variable) provides helper methods for writing build scripts safely and concurrently.

### Command Execution and File Operations

* `rnts.sh(args, cwd, env, inherit_stdout)`: A wrapper around `subprocess.run` with `check=True` baked in.
* `rnts.cp(src, dest)`: A copy utility that automatically determines whether to use `shutil.copy2` (for files) 
or `shutil.copytree` (for directories).
* `rnts.relativize(path)`: Converts an absolute path to a path relative to the workspace root.
* `rnts.join_paths(paths)`: Joins paths using the OS-specific path separator.

### Concurrency: `rnts.gather()`

`rnts` supports multi-threading for parallel task execution.

`rnts.gather(*tasks)` takes a list of callable functions, copies the current context (`contextvars.copy_context()`), 
and runs them concurrently in a `ThreadPoolExecutor` sized to the host's CPU core count.

## Type Serialization (`models.py` & Internals)

Because `@task` return values are cached to disk as JSON metadata, `rnts` needs to serialize and deserialize Python objects.

`rnts` uses `dill`, which means it can serialize most Python types. Read [this](https://pypi.org/project/dill/)
to see what types are supported.

## CLI Execution

To run a command, use the `rnts` CLI format from your terminal:

```bash
rnts <module_name>.<command_name>
```

For the example configuration provided above, you would run:

```bash
rnts backend.build
```

## Safety and Locking

To prevent concurrent runs from corrupting the `.json` cache metadata or overwriting artifacts in the `out/` directory, 
`rnts` uses two locking mechanisms:

1. Process Lock: On startup, it makes a file named `.rnts.lock` in the `out/` directory. If another `rnts` instance 
detects this, it immediately exits. You may delete `.rnts.lock` if you are absolutely sure that another instance
is not running.
2. `FileLock`s: Individual hash files and metadata JSON files are locked during read/write operations to ensure 
thread-safety when using `rnts.gather()`.
