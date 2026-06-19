import functools
import hashlib
import json
from pathlib import Path
from typing import Callable, TypeVar, ParamSpec, Concatenate, cast
from .context import ctx
from .models import Module, PathRef

P = ParamSpec("P")
R = TypeVar("R")
M = TypeVar("M", bound=Module)

# cache for process results keyed by module name and function name
_PROCESS_CACHE: dict[tuple[str, str], object] = {}


def _compute_dir_hash(directory: Path) -> str:
    # return empty string if path does not exist or is not a directory
    if not directory.exists() or not directory.is_dir():
        return ""
    hasher = hashlib.md5()
    # sort paths to ensure deterministic hashing
    for path in sorted(directory.rglob("*")):
        if path.is_file():
            # hash the relative path string
            hasher.update(str(path.relative_to(directory)).encode("utf-8"))
            # read file in chunks to avoid blowing up the RAM
            with open(path, "rb") as f:
                while chunk := f.read(65536):
                    hasher.update(chunk)
    return hasher.hexdigest()


def _serialize_val(val: object) -> object:
    # convert pathref objects to typed dictionaries
    if isinstance(val, PathRef):
        return {"__type__": "PathRef", "path": str(val.path)}
    # convert path objects to typed dictionaries
    if isinstance(val, Path):
        return {"__type__": "Path", "path": str(val)}
    # recursively serialize list elements
    if isinstance(val, list):
        return [_serialize_val(v) for v in cast(list[object], val)]
    # convert tuples to typed dictionaries with serialized items
    if isinstance(val, tuple):
        return {
            "__type__": "tuple",
            "items": [_serialize_val(v) for v in cast(tuple[object, ...], val)],
        }
    # recursively serialize dictionary keys and values
    if isinstance(val, dict):
        return {
            str(k): _serialize_val(v)
            for k, v in cast(dict[object, object], val).items()
        }
    return val


def _deserialize_val(val: object) -> object:
    if isinstance(val, dict):
        d = cast(dict[str, object], val)
        t = d.get("__type__")
        # reconstruct pathref from metadata dict
        if t == "PathRef":
            return PathRef(str(d.get("path", "")))
        # reconstruct path from metadata dict
        if t == "Path":
            return Path(str(d.get("path", "")))
        # reconstruct tuple from item list
        if t == "tuple":
            items = d.get("items")
            if isinstance(items, list):
                return tuple(_deserialize_val(v) for v in cast(list[object], items))
        # recursively deserialize plain dictionary values
        return {str(k): _deserialize_val(v) for k, v in d.items()}
    # recursively deserialize list elements
    if isinstance(val, list):
        return [_deserialize_val(v) for v in cast(list[object], val)]
    return val


def task(func: Callable[Concatenate[M, P], R]) -> Callable[Concatenate[M, P], R]:
    # decorator to cache and track build tasks based on dependencies
    @functools.wraps(func)
    def wrapper(self: M, *args: P.args, **kwargs: P.kwargs) -> R:
        key = (self.module_name, func.__name__)

        # check if the result is already in the cache
        if key in _PROCESS_CACHE:
            return cast(R, _PROCESS_CACHE[key])

        # define the path where task metadata and cache state are saved
        meta_file = (
            self.module_dir
            / "out"
            / "hashes"
            / self.module_name
            / f"{func.__name__}.json"
        )

        # this part is atrocious
        if meta_file.exists():
            try:
                # load existing metadata for validation
                meta = cast(dict[str, object], json.loads(meta_file.read_text()))

                # verify if the tracked source file hashes still match
                sources_match = True
                sources = meta.get("sources")
                if isinstance(sources, list):
                    for src_item in cast(list[object], sources):
                        if isinstance(src_item, list):
                            src_list = cast(list[object], src_item)
                            if len(src_list) == 3:
                                src_mod_name = src_list[0]
                                src_name = src_list[1]
                                expected_hash = src_list[2]

                                mod = Module.get_module(str(src_mod_name))
                                if mod:
                                    # invoke source function to recalculate current state
                                    cast(
                                        Callable[[], None], getattr(mod, str(src_name))
                                    )()
                                    curr_hash_file = (
                                        mod.module_dir
                                        / "out"
                                        / "hashes"
                                        / str(src_mod_name)
                                        / str(src_name)
                                    )
                                    # invalidate if hash file is missing or contents differ
                                    if (
                                        not curr_hash_file.exists()
                                        or curr_hash_file.read_text().strip()
                                        != str(expected_hash)
                                    ):
                                        sources_match = False
                                        break
                                else:
                                    sources_match = False
                                    break

                # verify if the output values of upstream tasks still match
                tasks_match = True
                if sources_match:
                    tasks = meta.get("tasks")
                    if isinstance(tasks, list):
                        for task_item in cast(list[object], tasks):
                            if isinstance(task_item, list):
                                task_list = cast(list[object], task_item)
                                if len(task_list) == 3:
                                    dep_mod_name = task_list[0]
                                    dep_task_name = task_list[1]
                                    expected_val_serialized = task_list[2]

                                    mod = Module.get_module(str(dep_mod_name))
                                    if mod:
                                        # evaluate dependent task to get its current value
                                        curr_task = cast(
                                            Callable[[], object],
                                            getattr(mod, str(dep_task_name)),
                                        )
                                        curr_val = curr_task()
                                        # invalidate if current serialization deviates from cached value
                                        if (
                                            _serialize_val(curr_val)
                                            != expected_val_serialized
                                        ):
                                            tasks_match = False
                                            break
                                    else:
                                        tasks_match = False
                                        break

                # if sources and dependent tasks match, reuse the cached return value
                if sources_match and tasks_match:
                    return_val = meta.get("return_value")
                    cached_res = _deserialize_val(return_val)
                    _PROCESS_CACHE[key] = cached_res

                    ctx.record_upstream_hit(self.module_name, func.__name__, return_val)
                    return cast(R, cached_res)
            except Exception:
                # fall back to executing the task if any parsing or verification error occurs
                pass

        # track task execution context and establish dedicated output directory
        ctx.push_task(self.module_name, func.__name__)
        out_dir = self.module_dir / "out" / self.module_name / func.__name__
        out_dir.mkdir(parents=True, exist_ok=True)

        try:
            # execute the underlying task function with isolated destination path
            with ctx.set_dest(out_dir):
                result = func(self, *args, **kwargs)

            _PROCESS_CACHE[key] = result

            # harvest metadata details to persist cache state on disk
            deps = ctx.get_dependencies(self.module_name, func.__name__)
            serialized_res = _serialize_val(result)
            meta_data = {
                "sources": deps["sources"],
                "tasks": deps["tasks"],
                "return_value": serialized_res,
            }
            meta_file.parent.mkdir(parents=True, exist_ok=True)
            _ = meta_file.write_text(json.dumps(meta_data, indent=4))

            ctx.record_upstream_miss(self.module_name, func.__name__, serialized_res)
            return result
        finally:
            # ensure context scope pops back up when complete
            ctx.pop_task()

    # tag the wrapper so framework can recognize valid tasks
    setattr(wrapper, "__is_rnts_task__", True)
    return cast(Callable[Concatenate[M, P], R], wrapper)


def source(func: Callable[[M], Path]) -> Callable[[M], Path]:
    # decorator to register and compute hashes for module source directories
    @functools.wraps(func)
    def wrapper(self: M) -> Path:
        src_dir = func(self)
        current_hash = _compute_dir_hash(self.module_dir / src_dir)

        # write computed hash tracking file to disk
        hash_file = (
            self.module_dir / "out" / "hashes" / self.module_name / func.__name__
        )
        hash_file.parent.mkdir(parents=True, exist_ok=True)
        _ = hash_file.write_text(current_hash)

        ctx.record_source(self.module_name, func.__name__, current_hash)
        return src_dir

    return wrapper


def command(func: Callable[Concatenate[M, P], R]) -> Callable[Concatenate[M, P], R]:
    # simple passthrough decorator for basic tasks without implicit cache rules
    @functools.wraps(func)
    def wrapper(self: M, *args: P.args, **kwargs: P.kwargs) -> R:
        return func(self, *args, **kwargs)

    return cast(Callable[Concatenate[M, P], R], wrapper)
