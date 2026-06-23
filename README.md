# RNTS

`rnts`, short for "run this", is a build tool / command runner written in Python.

```python
from pathlib import Path
from rnts import Module, task, ctx

class StaticSite(Module):
    @task
    def generate_html(self):
        # ctx.dest is an automatically generated variable that points
        # to where the task output should be at
        # in this case, out/StaticSite/frontend/generate_html
        print(f"generating site assets in: {ctx.dest}")
        
        index_file = ctx.dest / "index.html"
        index_file.write_text("<h1>hello</h1>")

StaticSite(name="frontend")

# run `rnts frontend.generate_html` to execute
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
