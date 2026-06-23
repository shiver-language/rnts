# RNTS

`rnts`, short for "run this", is a build tool / command runner written in Python.

```python
from pathlib import Path
from rnts import rnts, Module, source, task, command, PathRef, ctx

class CProjectBuilder(Module):
    def __init__(self):
        # register this module with the name "game_engine"
        super().__init__("game_engine") 

    @source
    def c_source(self) -> Path:
        # @sources tracks change in the source directory for caching
        return Path("src")

    @task
    def compile_core(self) -> PathRef:
        # register this task as a dependency to the c_source path
        # ensures that this task won't run again if there is no change in source
        self.c_source()
        
        # ctx.dest points to out/modules/CProjectBuilder/game_engine/compile_core/
        output_obj = ctx.dest / "core.o"
        
        # invoke compiler via the runtime helper
        rnts.sh(["echo", "clang -c src/core.c -o", str(output_obj)], inherit_stdout=False)

        output_obj.write_text("/* compiled c object: core engine */")
        
        return PathRef(output_obj)

    @task
    def compile_physics(self) -> PathRef:
        # concurrently compile the physics engine
        self.c_source()
        output_obj = ctx.dest / "physics.o"
        
        rnts.sh(["echo", "clang -c src/physics.c -o", str(output_obj)], inherit_stdout=False)
        output_obj.write_text("/* compiled c object: physics engine */")
        
        return PathRef(output_obj)

    @command
    def build_all(self) -> None:
        # compile core.c and physics.c at the same time
        core_obj, physics_obj = rnts.gather(self.compile_core, self.compile_physics)
        print(f"generated objects: {core_obj}, {physics_obj}")

        # as this is a @command, it runs every time to link the objects
        executable = ctx.dest / "engine"
        executable.write_text(f"/* linked binary: {core_obj.path.name} + {physics_obj.path.name} */")
        print(f"binary linked at: {executable}")

# instantiate to register with the CLI runner
CProjectBuilder()

# run `rnts frontend.build_all` to execute
```

## Building
You will need `uv`.
```bash
uv tool install --editable .
```

## What is RNTS?

`rnts` is intended as a build tool for the Shiver language project, but it is not 
just a specialized tool, rather, it is a framework that allows you to write intuitive
build scripts. In other words, you can adapt `rnts` to build any languages you like.

## How does RNTS work?

`rnts` is heavily inspired by the Mill build tool. It allows you to define sources and make tasks 
depend on it. Tasks may depend on other tasks. For example:
```
[ pull dependency task ]
          |
( library source code )              ( project source code )
          |                                     |
   [ compile task ]                     [ compile task ]
          |                                     |
   ( object code )                       ( object code )
          |                                     |
          ---------------------------------------
                            |
                      [ link task ]
                            |
                      ( binaries )
                            |
       [ release task ]------------[ install task ]
              |                           
        ( app.tar.gz )              
```
You can execute any tasks. `rnts` will run all the dependency tasks of it. Say
you request `rnts` to execute the link task, the pull dependency and the 
two compile tasks will be ran, followed by running the actual link task. 

Features:
- caching: tasks that are already ran won't have to run again if the sources it depends on remain unchanged
- concurrency: tasks can run in parallel to each other whenever possible
- intuitive: easy to write, easy to reason about, you can express any build pipelines with this model
- powerful: build scripts are written in Python

## Why?

We see issues in a lot of build systems out there.
- Maven: bloated XML config
- Gradle: highly complicated
- Cmake: invented its own language that is counterintuitive
- Make: not cross platform
- Mill: depends on JVM

`rnts` aims to address all of the above issues.

### Why Python? 

- Most developers have Python installed already
- Most developers know Python, if not, it is easy to learn
- Allows the build scripts to be cross platform
- Scripting languages like Python is well suited for writing build... scripts
