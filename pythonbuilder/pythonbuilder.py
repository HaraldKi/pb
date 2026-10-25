"""Decorate functions returning `Target` with @`task` to create a build task.

## Introduction

The canonical way to define a task to update a target looks like:
```python
@task
def stuff() -> Target[Path]:
  dep1 = dependency1()
  dep2 = dependency2()
  t = target(Path("build/file"), dep1, dep2, state="file"):
  if t.outdated:
    pbexec("compile", f, dep1.item, dep2.item)
  return t
```

where the `@task` converts the function `stuff` into a build task. Lets go
through the details:

- `-> Target[...]` is the required return type of a function to be used as a
  @`task`.

- `dependency1()` and `dependency2()` must also be `@task` decorated functions
  returning a `Target[X]` for some type `X`. They are aptly named to show them
  as the dependencies of the target we are about to construct here.

- `t = target(...)` creates a new target, in this case supposed to create or
  update the file `build/file`. For `state=file` see `target()`. The `target`
  function does a whole lot of work, in particular it computes a checksum for
  the file and uses it to check whether it needs to be (re-)created. If yes,
  `t.outdated` is set to `True`.

- `t.outdated`, if `True` tells us that the file is out of date, in which case
  we proceed to

- `pbexec(...)`: Any python code can be used to update the file. The example
  uses `pbexec()` to run an external command.

- Finally, the target **must** be returned.

During the build process, the decorated function `stuff()` may be called more
than once, but the `@task` decorator makes sure the plain one will be called at
most once.

<hr>

"""

## See https://stackoverflow.com/a/33533514/2954288
## for use of class as type annotations before class is fully defined
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import subprocess
import time
from abc import abstractmethod
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from functools import wraps
from pathlib import Path
from types import FunctionType
from typing import (
  Any,
  Final,
  Generic,
  Literal,
  ParamSpec,
  Protocol,
  Self,
  TypeVar,
)

from pythonbuilder._public import public

########################################################################

CURRENTBUILD = None
DEFINED_TASKS: dict[str, Callable[[], Target[Any]]] = dict()


@public
def clearTasks() -> None:
  DEFINED_TASKS.clear()


class Build:
  def __init__(self) -> None:
    self._targets: dict[str, Target[Any]] = dict()
    self.states = _StateStore(getStatefile())
    self.doGraph = False
    self._forced: set[str] = set()
    self._taskStack: list[str] = []
    self._active: set[str] = set()

  def current(self) -> str:
    return self._taskStack[-1]

  def depth(self) -> int:
    return len(self._taskStack)

  def getTarget(self, name: str) -> Target[Any] | None:
    return self._targets.get(name, None)

  def newTarget(
    self,
    item: T,
    *dependencies: Target[Any],
    state: str | Callable[[T], str] | None = None,
  ) -> Target[T]:
    name = self.current()
    if name in self._targets:
      raise BuildException(
        f"'{name}' defined already,"
        + " check if you called a dependency function missing a @task decorator"
      )
    forced = name in self._forced
    t = Target(item, *dependencies, state=state, name=name, forced=forced)
    self._targets[name] = t
    return t

  def enter(self, taskName: str) -> None:
    if taskName in self._active:
      names = list(self._taskStack)
      names.reverse()
      raise BuildException(
        "dependency loop detected for: '%s'<-'%s'" % (taskName, str(names))
      )
    self._active.add(taskName)
    self._taskStack.append(taskName)

  def leave(self) -> None:
    taskName = self._taskStack.pop()
    self._active.remove(taskName)

  def force(self, taskName: str) -> None:
    self._forced.add(taskName)


P = ParamSpec("P")
"""Generic parameter type for the functions we annotate with `task`."""


@public
def task(updater: Callable[P, Target[T]]) -> Callable[P, Target[T]]:
  """A decorator which wraps a function as a task.

  The resulting task makes sure that the wrapped function is called at most
  once during a build, caching the target returned.

  **NOTE**: After changing some input, calling the same task directly again is
  useless, because its result is cached by the build. To force a new build, call
  `newBuild()` first.

  See the [introduction](#introduction) for an example.

  ### Parameters

  - updater: task function, which must return a `Target`. The function may have
  parameters, but at least for functions to be called as a command line
  parameter, the parameters must be optional. If `toGraphviz` is used, *all*
  task functions' parameters must be unused outside the code guarded by the
  canonical `if target.outdated`.

  """
  return wrapTask(updater, False)


@public
def internalTask(updater: Callable[P, Target[T]]) -> Callable[P, Target[T]]:
  """Same as `task` except that the decorated function name will not be
  available when using `main` to process a command line.

  """
  return wrapTask(updater, True)


def wrapTask(
  updater: Callable[P, Target[T]], internal: bool
) -> Callable[P, Target[T]]:
  taskName = updater.__name__
  if taskName in DEFINED_TASKS:
    raise BuildException(f"{taskName} already defined")

  @wraps(updater)
  def taskWrapper(*args: P.args, **kwargs: P.kwargs) -> Target[T]:
    build = currentBuild()
    target = build.getTarget(taskName)
    if target is not None:
      return target

    build.enter(taskName)
    try:
      target = updater(*args, **kwargs)
      finish(build, target, taskName)
      return target
    finally:
      if build.depth() == 1:
        build.states.save()
      build.leave()

  setattr(taskWrapper, "internal", internal)
  DEFINED_TASKS[taskName] = taskWrapper
  return taskWrapper


@public
def inputTask(
  item: T,
  state: str | Callable[[T], str] | None = None,
  name: str | None = None,
) -> Callable[[], Target[T]]:
  """Simplified creation of a task for a target without dependencies.

  Instead of
  ```python
  @internalTask
  def stuff() -> Target[...]:
     return target(...)
  ```
  you may write
  ```python
  stuff = inputTask(..., name="stuff")
  ```
  The resulting task is always an @`internalTask`.

  ### Parameters

  - item: see `target()`
  - state: see `target()`
  - name: defaults to `str(item)` but using the name of the
    variable to which the result is assigned is recommended.

  ### Return
  An `@internalTask`.
  """
  taskName = name if name is not None else str(item)

  def f() -> Target[T]:
    return target(item, state=state)

  result = renameFunction(f, taskName)
  return internalTask(result)


# FIXME: the state strings could be a Literal[...]
@public
def target(
  item: T,
  *dependencies: Target[Any],
  state: str | Callable[[T], str] | None = None,
) -> Target[T]:
  """Creates a target from within a `@task` decorated function.

  This is, in fact, required. And each `@task` may only call `target()` once and
  the task must return this same target. Some violations are captured, but
  beware.

  ### Parameters
  - item: the item to keep up-to-date, like a file or directory name
  - dependencies: the dependencies of this target
  - state: describes how to generate a state (checksum, fingerprint) for
      the item. The function must generate a small fingerprint string.

      If `state` is not provided, the `item` must denote an **existing** file or
      directory for a default of `stateFileContent` or `stateDirContent`, or
      implement `StateProvider`, in which case the item's
      `StateProvider.provideState` function is used to generate its state.

      If given as a string, it must be "dir", "file", "new", "fixed" or "value"
      for `stateDirContent`, `stateFileContent`, `stateNew`, `stateFixed` or
      `stateValue` respectively.

      Otherwise it must be a function which creates a short fingerprint string
      from the `item`.

  ### Return

  A `Target` with field `Target.outdated` set to `True` if the target's item was
  determined to be out of date.  The `Target.name` is the name of the calling
  `@task` function.

  """
  build = currentBuild()
  if build.depth() == 0:
    raise BuildException("no current task, call target() only from a @task")
  target = build.newTarget(item, *dependencies, state=state)
  target._startNanos = time.time_ns()

  depsDigest = hashlib.sha256()
  for d in target.dependencies:
    depsDigest.update(build.states.getOwnHash(d).encode())
    if d.outdated:
      target._triggeringDeps.append(d.name)

  target._stateBeforeCmd = (
    target._stateGenerator.provideState(),
    depsDigest.hexdigest(),
  )
  combinedOld = build.states.get(target)
  target.outdated = not build.doGraph and (
    combinedOld != target._stateBeforeCmd or target.forced
  )

  LOG.debug(
    "  %s:\n  old %s\n  new %s\n  force=%s",
    target.name,
    combinedOld,
    target._stateBeforeCmd,
    target.forced,
  )
  if not target.outdated and not build.doGraph:
    LOG.log(VERBOSE, "- " + target.name)
  return target


def finish(build: Build, target: Target[T], currentTask: str) -> None:
  took = _formatNanoDelta(target._startNanos, time.time_ns())
  stateAfter = target._stateGenerator.provideState()
  if LOG.isEnabledFor(VERBOSE) and target.outdated:
    trigger = ""
    if len(target._triggeringDeps) > 0:
      trigger = " <- " + ",".join(target._triggeringDeps)
    elif target.outdated and not target.forced:
      trigger = " <- outdated"
    elif target.forced:
      trigger = " <- forced"
    changed = "+" if target._stateBeforeCmd[0] != stateAfter else "."
    LOG.log(
      VERBOSE,
      "%s %s(%s%s) (%s)",
      changed,
      currentTask,
      target.name,
      trigger,
      took,
    )

  build.states.setHashes(target, stateAfter, target._stateBeforeCmd[1])


def triggerAllTargets() -> dict[str, Target[Any]]:
  global CURRENTBUILD
  keptBuild = currentBuild()
  build = newBuild()
  build.doGraph = True
  try:
    for f in DEFINED_TASKS.values():
      if not getattr(f, "internal", False):
        f()
    return build._targets
  finally:
    CURRENTBUILD = keptBuild


@public
def main(argv: list[str]) -> Literal[0, 1]:
  """Provides command line parsing and calling of tasks named on the command line.

  Use it like
  ```python
  sys.exit(pbutil.main(*(sys.argv[1:])))
  ```

  The arguments on the command line are used as follows:

  - `ll=` sets the log level, where level can be any string abbreviating one of
  the lowercase loglevel keywords, `debug`, `verbose`, `info`, `warning`,
  `error`, `critical`. An example is `ll=v` to switch to `VERBOSE` logging.

  - `force=...` forces all tasks in the comma separated list (no whitespace) to be handled
  as if out-of-date. This is useful for debugging a build step, for example `doc`, which
  produces its output files but with wrong content. By using `force=doc` the build step
  for `doc` can be re-run without other more cumbersome ways of invalidating its state
  hash, like deleting an output file. More than one task name can be provided like
  `force=doc,coverage`. All `force` tasks are also added to the list of tasks to
  consider for building. So when providing the command line arguments `doc
  force=doc,apidoc`, the `doc` argument is redundant and `apidoc` will be build even if
  `doc` does not depend on it.

  - **Other arguments** are assumed to be names of functions decorated with @`task` (not
  @`internalTask`), even if they contain an equal sign. Put another way, only the
  prefixes `ll=` and `force=` are interpreted as options. All task functions are then
  called in the order in which they appeared, `force` tasks first.

  If, in the end, there is no task specified, all tasks names are listed on the console.

  **NOTE 1:** There is no `--` in front of the option names, following the only UNIX
  command which does this right, namely
  [dd](https://man.archlinux.org/man/dd.1.en).☺


  **NOTE 2**: there is nothing wrong with having your own main() to call tasks. The
  defined tasks are available as `getTaskNames()` and `getTask()`. To configure the
  logger, get it via `pythonbuilder.pythonbuilder.getLogger()`.

  ### Parameters

  - argv should typically be `sys.argv` stripped of `argv[0]`, or a trimmed version of
  it if you have your own command line parsing.

  ### Return
  0 or 1 ready to be used with `sys.exit()`, i.e. 1 means we had a problem.

  """
  build = newBuild()
  (taskNames, forced, ll) = parseArgv(argv)
  if ll is not None:
    if not _setLogLevel(ll):
      return 1
  for t in forced:
    build.force(t)
  taskNames = forced + taskNames

  if not taskNames:
    ## FIXME: filter out or mark the internalTasks
    try:
      targets = triggerAllTargets()
    except BuildException as e:
      LOG.error(e)
    else:
      printTargets(targets.values())
    return 0
  return runTasks(taskNames)


@public
def runTasks(taskNames: list[str]) -> Literal[0, 1]:
  """Runs all tasks given by name and provides some nice logging with timings.

  Before running `runTasks()` on the same paramters again, consider
  `newBuild()`.

  ### Return
  1 if the build failed with an exception, otherwise 0. **NOTE** the inverted
  logic geared towards using with `sys.exit()`.

  """

  buildStart = time.time_ns()
  ## Somewhat off as it excludes sleep times, found no way to get those.
  ## Do not use psutil.create_time() it can be off by 999ms.
  ## BUT: according to docs, process_time_ns() has an undefined reference
  ## point, yet at least on Linux so far this seems to be close to 0 at
  ## process start. Hmm.
  startNanos = buildStart - time.process_time_ns()
  LOG.log(
    VERBOSE, "  startup took %s", _formatNanoDelta(startNanos, buildStart)
  )

  resultState = ansiGreen("build ✔")
  buildOK = True
  try:
    for taskName in taskNames:
      task = getTask(taskName)
      if task is None:
        LOG.error(f"{taskName}: no task with this name defined")
        return 1
      task()
  except Exception as e:
    buildOK = False
    resultState = ansiRed("build ✘")
    if LOG.isEnabledFor(VERBOSE):
      logging.error(e, exc_info=True)
    else:
      logging.error(e)

  buildEnd = time.time_ns()
  LOG.info(
    resultState + ", took %s, total %s",
    _formatNanoDelta(buildStart, buildEnd),
    _formatNanoDelta(startNanos, buildEnd),
  )
  return 0 if buildOK else 1


@public
def newBuild() -> Build:
  """Resets the build state to be able to re-run a build.

  This does not remove the persisted target states, only the targets kept in
  memory.

  Calling this is only needed in special situations, like the following:
  - you run an `@task` function directly (rather than using `runTasks` or `main`.
  - then you change an input of the build
  - and want to run the `@task` again.

  Without `newBuild()` befor the last step, the new input is not even looked
  at. There is no need to run `newBuild()` initially, as an one is defined up
  front automatically.

  """
  global CURRENTBUILD
  CURRENTBUILD = Build()
  return CURRENTBUILD


def currentBuild() -> Build:
  """Returns the current build object."""
  global CURRENTBUILD
  if CURRENTBUILD is None:
    CURRENTBUILD = Build()
  return CURRENTBUILD


@public
def getTaskNames() -> list[str]:
  return list(DEFINED_TASKS.keys())


@public
def getTask(name: str) -> Callable[[], Target[Any]] | None:
  return DEFINED_TASKS.get(name, None)


def parseArgv(argv: list[str]) -> tuple[list[str], list[str], str | None]:
  """Returns target names, forced target names and the last `ll` value on the
  command line as described for `main`.
  """

  targets: list[str] = []
  forced: list[str] = []
  ll: str | None = None

  for arg in argv:
    parts = arg.split("=", 1)
    if len(parts) != 2:
      targets.append(arg)
      continue

    if parts[0] == "ll":
      ll = parts[1]
      continue

    if parts[0] == "force":
      forced.append(parts[1])
      continue
    targets.append(arg)
  return (targets, forced, ll)


def printTargets(
  targets: Iterable[Target[Any]], seen: set[str] = set()
) -> None:
  depths = [(_targetDepth(t), t) for t in targets]
  for pair in sorted(depths, key=lambda pair: (pair[0], pair[1].name)):
    t = pair[1]
    if t.name in seen:
      continue
    printTargets(t.dependencies, seen)
    deps = "<- " + ", ".join([d.name for d in t.dependencies])
    print(f"{'.' * pair[0]}•", t.name, "" if len(deps) == 3 else deps)
    # if t.__doc__ is not None:
    #  print(f"{' ' * pair[0]}  ", t.__doc__)
    seen.add(t.name)


@public
class BuildException(Exception):
  """Raised on failures detected by pythonbuilder."""

  def __init__(self, message: str) -> None:
    self.message = message


public("VERBOSE")
VERBOSE = logging.INFO - 5

logging.addLevelName(VERBOSE, "VERBOSE")

## REMINDER: Do not just import LOG, as importing copies the referenc to
## the logger into a new module global variable. If we set LOG to a different
## logger, the importing module will not know
LOG = logging.getLogger()
LOG.setLevel("INFO")
LOG.addHandler(logging.StreamHandler())


@public
def getLogger() -> logging.Logger:
  """The logger we use.

  For consistent logging, the build script can import and use it too, rather than creating
  its own. This logger is used by `pythonbuilder` throughout. If the environment
  variable PBLOGLEVEL is set, it is used as the default, otherwise it is `"INFO"`. The
  levels are used as follows:

  - INFO: Show only output from `logcmd` which, in particular, is used by `pbexec`, but
    is also recommended to be used for target generating commands which don't call
    external programs.

  - VERBOSE: also shows targets considered and whether they are determined up-to-date or
    not (see `levelVerbose`)

  - DEBUG: also shows internal steps and data

  """
  global LOG
  return LOG


## Note: Could benefit from memoization, but for builds with
## a typical number of targets, that would be overkill
def _targetDepth(target: Target[T]) -> int:
  if not target.dependencies:
    return 0
  return 1 + max([_targetDepth(dep) for dep in target.dependencies])


def _setLogLevel(shortcut: str) -> bool:
  """Helper for `main`."""
  levels = [lev.lower() for lev in list(logging.getLevelNamesMapping().keys())]
  matches = [level for level in levels if level.startswith(shortcut)]
  if len(matches) < 1:
    LOG.error("no log level starts with " + shortcut)
    return False
  LOG.setLevel(matches[0].upper())
  return True


########################################################################


# FIXME: should go into the Build class
_STATEFILE = Path("build", "pbstates")


@public
def setStatefile(path: Path) -> None:
  """Sets the `Path` of the file in which to persist target states.

  Defaults to `Path("build", "pbstates")`.

  Set this before calling `updateTargets`. To force all targets to be rebuild,
  delete this file.
  """
  global _STATEFILE
  _STATEFILE = path


@public
def getStatefile() -> Path:
  """Gets the `Path` of the file where target states are persisted. See `setStatefile`."""
  global _STATEFILE
  return _STATEFILE


## From Python 3.12, not needed anymore, see:
## https://mypy.readthedocs.io/en/stable/generics.html
T = TypeVar("T")
"""The data type wrapped by a `Target`."""


@public
class StateProvider(Protocol):
  """ """

  @abstractmethod
  def provideState(self) -> str:
    """Provides a state string for `self`.

    Objects with this function don't require a separate `state=` parameter
    when calling `target`. Instead this function is used to get the state
    representation.

    """
    ...


@dataclass
class StateProviderImpl(StateProvider, Generic[T]):
  item: T
  generator: Callable[[T], str]

  def provideState(self) -> str:
    return self.generator(self.item)


@dataclass(init=False, eq=False)
@public
class Target(Generic[T]):
  """Represents a target with an item to create. Call `target` to create one."""

  def __init__(
    self,
    item: T,
    *dependencies: Target[Any],
    state: str | Callable[[T], str] | None,
    name: str | None,
    forced: bool,
  ) -> None:
    self.item: Final[T] = item
    """The item of the target, often a file or directory path."""

    self.outdated: bool = False
    """Set by `target` if the target's item is out-of-date and should be
    updated by the calling task."""

    self.name: Final[str] = str(item) if name is None else name
    """The target's name, set by the @`task` which creates it."""

    self.dependencies: Final[tuple[Target[Any], ...]] = dependencies
    """The target's dependencies."""

    self.forced: bool = forced
    """Whether `target` was forcibly set outdated as requested by the build
    process. There is currently no way to see if the target was also naturally
    out-of-date.
    """

    self._stateGenerator: Final[StateProvider] = _getStateGenerator(item, state)
    """State generator for the target."""

    self._startNanos = -1
    """When we started working on the target itself, after doing the deps."""

    self._stateBeforeCmd: tuple[str, str] = ("", "")
    """Set by `target()` to the state of target and dependencies after
    computing dependencies and before returning the target to the task."""

    self._triggeringDeps: list[str] = []
    """Dependencies which where out of date and are therefore a reason for the
    target being out of date. Set bey `target()`."""

    self._nameOnly: bool = False
    """When showing a `Target`, don't include a `str(item)`."""

  def showNameOnly(self) -> Self:
    """Suggest to tools like `toGraphviz` not to show a string representation of
    the item, but instead only use the name. If no explicit name was provided,
    calling this function is silly, as in that case the name is `str(item)`
    anyway.

    This is typically used for targets whose string representation reveals a
    developer's local setup, like environment variables. If the representation
    ends up committed, like the dependency graph, targets which change
    frequently, like file names containing a version, may also opt to use
    `showNameOnly()`.

    """
    self._nameOnly = True
    return self

  def __str__(self) -> str:
    """Readable short form for a `Target`"""
    deps = ", ".join([d.name for d in self.dependencies])
    if len(deps) == 0:
      deps = ""

    if isinstance(self._stateGenerator, StateProviderImpl):
      stateGen = getattr(self._stateGenerator, "generator")
      s = getattr(stateGen, "__name__", "(callable)")
    else:
      s = "(itemstate)"

    return f"Target({self.name}, [{deps}], name={self.name}, state={s})"


def _getStateGenerator(
  item: T, state: str | Callable[[T], str] | None = None
) -> StateProvider:
  match state:
    case "dir":
      if isinstance(item, Path):
        return StateProviderImpl(item, stateDirContent)
      else:
        raise BuildException("state function 'dir' must be used with a Path")
    case "file":
      if isinstance(item, Path):
        return StateProviderImpl(item, stateFileContent)
      else:
        raise BuildException("state function 'file' must be used with a Path")
    case "new":
      return StateProviderImpl(None, stateNew)
    case "fixed":
      return StateProviderImpl(None, stateFixed)
    case "value":
      return StateProviderImpl(item, stateValue)
    case None:
      if isinstance(item, Path) and item.is_dir():
        return StateProviderImpl(item, stateDirContent)
      if isinstance(item, Path) and item.is_file():
        return StateProviderImpl(item, stateFileContent)
      if hasattr(item, "provideState"):  # trivialized isinstance(StateProvider)
        return item
      else:
        raise BuildException(
          (
            "'%s' is neither a file nor a directory,"
            + " cannot determine state"
            + " generator, provide one with state="
          )
          % item
        )
    case _:
      if isinstance(state, str):
        raise BuildException(
          f"'{state}' is not a known state function shortcut"
        )
      ## Guaranteed to be the correct type if a type checker is used
      return StateProviderImpl(item, state)


@public
def stateNew(_t: Any = None) -> str:
  """Returns a state string which is never the same, independent of the
  input.

  This is subject to `time.time_ns()` changing more frequently than this
  function is called.

  :param _t: unused
  :return: an implementation dependent string, differing for each call
  """
  return str(time.time_ns())


@public
def stateFixed(_t: Any = None) -> str:
  """Always returns the same state string, independent of the input.

  :param _t: unused
  :return: always the same implementation dependent string
  """
  return "0"


@public
def stateValue(item: Any) -> str:
  """Computes a state string from `item`, to be used for for in-memory
  targets like a version string generated from the current date.

  :param item: to compute the state string from
  :return: an implementation dependent string is always the same for
    same `t.item` values and typically changes for changed `t.item` values
  """
  return repr(item)


@public
def stateDirContent(targetPath: Path) -> str:
  """Feeds all recursively contained files of a directory into
  `stateFileIteratorContent`.

  :param targetPath: of the directory to compute the state from
  :return: a hash
  """
  if targetPath.is_file():
    raise BuildException("'%s' is a file but expected a directory" % targetPath)
  return stateFileIteratorContent(targetPath.rglob("*"))


@public
def stateFileContent(targetPath: Path) -> str:
  """Feeds the path a single file name into `stateFileIteratorContent` and
  returns the result.

  :param targetPath: of the file to compute the state from
  :return: a hash

  """
  if targetPath.is_dir():
    raise BuildException("'%s' is a directory but expected a file" % targetPath)
  return stateFileIteratorContent([targetPath])


@public
def stateFileIteratorContent(iter: Iterable[Path]) -> str:
  """Creates a combined state over files.

  If a path from the iterable exists in the file system, its content is fed into
  the checksum, otherwise a `stateNew` is fed in. If the path string denotes a
  directory, it is ignored. This is a convenience to be able to use this with
  `Path.rglob()` without extra directory name filter.

  To make a difference between sets of non existing files, all file names are
  also hashed.

  **NOTE:** When using this as the `state` parameter of `target()`, the iterable
  wrapped in the target should typically be lazily computed, that is, only when
  this function is actually called. Using a constant list like

  ```python
  files: list[Path] = generateVoodooFileList()
  voodoo = target(files, state=stateFileIteratorContent)
  ```

  the list is created before the target is actually considered. This may
  miss files which are only created by processing the dependencies of the
  target. An additional minor quirk is that the list is even computed if the
  `voodoo` target is never needed in the build.

  Example:
  ```python
  stateFileIteratorContent(Path("src").rglob("*.py"))
  ```

  will run all python files recursively found in `src` through a hash function
  and return the result.

  ## Parameters
  - iter: an iterable (or iterator or generator) over path names of files which
    may or may not exist.

  ## Return
  A hash of all file names and file contents. If the iterator is empty or
  contains only empty directories, `stateNew()` is returned.

  """
  digest = hashlib.sha256()
  found = False
  for path in iter:
    if path.is_dir():
      continue
    found = True
    digest.update(str(path).encode())
    if path.exists():
      with open(path, "rb") as file:
        digest.update(file.read())
    else:
      digest.update(stateNew().encode())
  return digest.hexdigest() if found else stateNew()


# HINT: the UNITS param avoids having it as a global variable. Is there a better way?
def _formatNanoDelta(
  start: int,
  now: int,
  _UNITS: list[tuple[str, int, int]] = [
    ("ns", 10000, 1000),
    ("µs", 10000, 1000),
    ("ms", 10000, 1000),
    ("s", 120, 60),
  ],
) -> str:
  delta = now - start
  for i in range(0, len(_UNITS)):
    if delta < _UNITS[i][1]:
      return "%s%s" % (delta, _UNITS[i][0])
    delta = delta // _UNITS[i][2]
  return "%s%s" % (delta, "min")


def flatten(result: list[str], nested: Any) -> None:
  """Flattens a multiply nested Iterable into the given result. Any element not
  `Iterable` and not `str` is added to the result as `str(element)`, except
  `None`.

  ### Parameters
  - result: to which elements are appended
  - nested: either an `Iterable` to flatten or a string or other object to add
    to the result

  """
  if isinstance(nested, str):
    result.append(nested)
  elif isinstance(nested, Iterable):
    for elem in nested:
      flatten(result, elem)
  elif nested is None:
    return
  else:
    result.append(str(nested))


@public
def logcmd(cmd: Any) -> list[str]:
  """A standard way to log external commands.

  The `args` are passed to `flatten` to create a list of strings, which is
  logged and returned, so it can be used as in `subprocess.run(logcmd(...))`.

  This is the standard way to log the command list also used
  by `pbexec`.

  ### Parameters
  - cmd a list of items which can be flattened into a list of strings

  ### Return
  The flattened list of strings
  """
  result: list[str] = []
  flatten(result, cmd)
  LOG.log(20, "* %s", " ".join(result))

  return result


@public
def pbexec(*args: Any) -> None:
  """
  Shallow wrapper around
  `subprocess.run() <https://docs.python.org/3/search.html?q=subprocess.run>`_

  It

  - logs the command line at `INFO` level
  - runs `subprocess.run()` with the flattened input list
  - calls `check_returncode()` on the result

  If you need more, use `subprocess.run()` directly, possibly with `flatten`.

  :param args: a possibly multiply-nested list which will be flattened with
    `flatten` before passed to `subprocess.run()`.
  """
  subprocess.run(logcmd(args)).check_returncode()


def _escdq(s: str) -> str:
  return s.replace('"', '\\"')


# HINT: the map param avoids having it as a global variable. Is there a better way?
def _eschtml(
  s: str, _eschtmlMap: dict[str, str] = {"&": "&amp;", "<": "&lt;", ">": "&gt;"}
) -> str:
  return re.sub("[&<>]", lambda m: _eschtmlMap.get(m.group(0), m.group(0)), s)


def _targetToGraphviz(target: Target[T], isCli: bool) -> str:
  result = ""
  for dep in target.dependencies:
    result += f'  "{_escdq(dep.name)}" -> "{_escdq(target.name)}"\n'

  text = str(target.item)
  label = ""
  if target.name != text and not target._nameOnly:
    if len(text) > 33:
      abbrev = text[:30] + "..."
      tooltip = f' tooltip="{_escdq(text)}"'
    else:
      abbrev = text
      tooltip = ""

    label = (
      f"label=<{_eschtml(target.name)}"
      + f'<BR/><FONT POINT-SIZE="10">{_eschtml(abbrev)}</FONT>>'
      + f"{tooltip}"
    )
  color = ""
  if not isCli:
    color = "color=grey fontcolor=grey"

  if color != "" or label != "":
    result += f'  "{_escdq(target.name)}" [{label} {color}]\n'
  return result


## FIXME: this should really be in pbutil
@public
def toGraphviz(cliCallable: set[str] | None = None) -> str:
  """Creates a dependency graph of the defined tasks in
  [graphviz](https://graphviz.org/) format.

  This needs to run all `@task`s in some arbitrary order in a way such `t.outdated`
  is always false. If all tasks correctly test `t.outdated` and do not touch the
  target to build, this has no side effects. Otherwise, obviously, the build's
  overall state may get messed up.

  ### Return
  A string which can be passed through one of the the graphviz renderers to create
  a dependency graph.

  """
  if cliCallable is None:
    cliCallable = set(
      [k for k, f in DEFINED_TASKS.items() if not getattr(f, "internal", False)]
    )
  known: set[str] = set()
  result = "digraph {\n"
  targets = triggerAllTargets()
  for target in targets.values():
    if target.name not in known:
      known.add(target.name)
      result += _targetToGraphviz(target, target.name in cliCallable)

  result += "}\n"
  return result


## FIXME: reintroduce name so that it is not always called graph
@public
def registerDependencyGraphTask(
  graphFile: Path, buildscriptTask: Callable[[], Target[Path]] | None = None
) -> Callable[[], Target[Path]]:
  """Creates a task to create the dependency graph.

  If the given `buildscript` is a `Path` a `task` is created for it.

  The extension of the `graphFile` will be used as the image type requested
  from the `dot` program. If the `buildscript` is already a task it is
  used as the dependency.

  ### Parameters
  - graphFile: the dependency graph after converting the
    output of `toGraphviz`.
  - buildscriptTask: to depend on such that the graph is re-created if the
    script changes. If None, a task named `_pb` is created assuming the build
    script is the file `./pb`.

  ### Return
  An `@task` called `graph`.

  """

  if buildscriptTask is None:

    @internalTask
    def _pb() -> Target[Path]:
      return target(Path("pb"))
  else:
    _pb = buildscriptTask

  @task
  def graph() -> Target[Path]:
    t = target(graphFile, _pb(), state="file")
    if t.outdated:
      graphToDot(t.item)
    return t

  return graph


@public
def graphToDot(targetPath: Path) -> None:
  """Convenience function to create a dependency graph of all tasks.

  The function calls `toGraphviz()` and pipes the output through
  the `dot` program, writing the image file to the `targetPath`.

  ### Parameters
  - targetPath: to write the graph to. Its suffix is used as the image
    type requested from `dot`, like `svg` or `pdf`.
  """
  result = toGraphviz()
  filetype = targetPath.suffix[1:]
  cmd = ["dot", "-T" + filetype, "-Grankdir=LR"]
  logcmd(cmd)
  with open(targetPath, "w", encoding="utf-8") as out:
    subprocess.run(cmd, input=result, encoding="utf-8", stdout=out)


def ansiRed(text: str) -> str:
  """Wraps text into ansi sequences to render it red.

  :param text: to wrap
  :return: wrapped text
  """
  return "\x1b[1;91m%s\x1b[0m" % text


def ansiGreen(text: str) -> str:
  """Wraps text into ansi sequences to render it green.

  :param text: to wrap
  :return: wrapped text
  """
  return "\x1b[38;2;20;110;20m%s\x1b[0m" % text


########################################################################


class _StateStore:
  def __init__(self, stateFile: Path):
    self.stateFile = stateFile
    self.hashes: dict[str, tuple[str, str]]
    if not os.path.isfile(self.stateFile):
      LOG.debug("  no file '%s', starting with empty states" % self.stateFile)
      self.hashes = dict()
      return

    LOG.debug("  reading %s" % self.stateFile)

    with open(self.stateFile, "r", encoding="UTF-8") as statefile:
      self.hashes = json.load(statefile)

    ## prefer a tuple (pair) over a list for the two hashes per target
    for key, value in self.hashes.items():
      self.hashes[key] = (value[0], value[1])

  def __repr__(self) -> str:
    return "_StateStore[%s]" % self.hashes

  def setHashes(
    self, target: Target[Any], targetHash: str, depsHash: str
  ) -> None:
    self.hashes[target.name] = (targetHash, depsHash)

  def get(self, target: Target[Any]) -> tuple[str, str]:
    return self.hashes.get(target.name, ("", ""))

  def getOwnHash(self, target: Target[Any]) -> str:
    return self.hashes[target.name][0]

  def getDepsHash(self, target: Target[Any]) -> str:
    return self.hashes[target.name][1]

  def save(self) -> None:
    LOG.debug("  writing %s" % self.stateFile)
    os.makedirs(os.path.dirname(self.stateFile), exist_ok=True)

    with open(self.stateFile, "w", encoding="UTF-8") as statefile:
      json.dump(self.hashes, statefile, indent=2)


def renameFunction(f: Callable[P, T], name: str) -> Callable[P, T]:
  """For internal use on locally defined functions to be returned from an
  outer function under a user defined name."""
  return FunctionType(
    f.__code__.replace(co_name=name),
    f.__globals__,
    name=name,
    argdefs=f.__defaults__,
    closure=f.__closure__,
  )
