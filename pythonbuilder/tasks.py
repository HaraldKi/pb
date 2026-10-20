#!/usr/bin/env python3
"""Decorate functions returning `Target` with @`task` to create a build task.

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
where the `@task` converts the function `stuff` into a build task. Lets go through
the details:

- `-> Target[...]` is the required return type of a function to be used as a @`task`.
- `dependency1()` and `dependency2()` must also be `@task` decorated functions returning
  a `Target[X]` for some type `X`. They are aptly named to show them as the dependencies
  of the target we are about to construct here.
- `t = target(...)` creates a new target, in this case supposed to create or update the
  file `build/file`. For `state=file` see `pythonbuilder.pythonbuilder.Target`. The
  `target` function does a whole lot of work, in particular is registers the target,
  computes checksums and checks whether, given the checksums of the dependencies and the
  current state of the target's item (`build/file`) the target needs to be
  (re-)created. If yes, `t.outdated` is set to `True`.
- `t.outdated`, if `True` tells us that the target's item is out of date and needs to be
  created (again).
- `pbexec(...)` If the target is outdated, any python code can be used to update it. The
  example uses `pythonbuilder.pythonbuilder.pbexec` to run an external command.
- Finally, the target must be returned.

During the build process, the decorated `stuff` may be called more than once, but the
`@task` decorator makes sure the plain one will be called at most once.
<hr>
"""

## See https://stackoverflow.com/a/33533514/2954288
## for use of class as type annotations before class is fully defined
from __future__ import annotations

import hashlib
import time
from functools import wraps
from typing import Any, Callable, Literal, ParamSpec

# REMINDER: an import copies a value, not a reference, so to access
# _TARGETS, we must use pb._TARGETS
import pythonbuilder.pythonbuilder as pb
from pythonbuilder.pbutil import _setLogLevel, parseArgv, printTargets
from pythonbuilder.pythonbuilder import (
  _LOG,
  _VERBOSE,
  BuildException,
  T,
  Target,
  _formatNanoDelta,
  _runBuild,
  _StateStore,
  findTarget,
  getStatefile,
)
from pythonbuilder.pythonbuilder import toGraphviz as pbToGraphviz

_CURRENTBUILD = None
_DEFINED_TASKS: dict[str, Callable[[], Target]] = dict()


class _TaskInfo:
  def __init__(self, name: str) -> None:
    self.name = name
    self.startNanos = -1
    self.stateCurrent: tuple[str, str] = ("", "")
    self.triggeringDeps: list[str] = []

  def setActive(
    self, startNanos: int, stateCurrent: tuple[str, str], triggeringDeps: list[str]
  ) -> None:
    self.startNanos = startNanos
    self.stateCurrent = stateCurrent
    self.triggeringDeps = triggeringDeps


class _Build:
  def __init__(self) -> None:
    self.states = _StateStore(getStatefile())
    self.doGraph = False
    self._forced: set[str] = set()
    self._taskStack: list[_TaskInfo] = []

  def currentTasks(self) -> list[str]:
    return [ti.name for ti in list(self._taskStack)]

  def enter(self, taskName: str) -> None:
    self._taskStack.append(_TaskInfo(taskName))

  def leave(self) -> None:
    self._taskStack.pop()

  def current(self) -> _TaskInfo:
    return self._taskStack[-1]

  def force(self, taskName: str) -> None:
    self._forced.add(taskName)

  def forced(self) -> bool:
    return self.current().name in self._forced


def _getBuild() -> _Build:
  global _CURRENTBUILD
  if _CURRENTBUILD is None:
    _CURRENTBUILD = _Build()
  return _CURRENTBUILD


def _runTasks(functions: list[Callable[[], Any]]) -> None:
  try:
    for f in functions:
      f()
  finally:
    _getBuild().states.save()


P = ParamSpec("P")
"""Generic parameter type for the functions we annotate with `task`."""


def task(updater: Callable[P, Target[T]]) -> Callable[P, Target[T]]:
  """A decorator which wraps a function into as a task.

  In particular the resulting task makes sure that the wrapped function is called at most
  once during a build, caching the target returned.

  ### Parameters

  - updater: task function, which must return a `Target`. The function may have
  parameters, but at least for functions to be called as a command line parameter, the
  parameters must be optional. If `toGraphviz` is used, *all* task functions' parameters
  must be unused outside the code guarded by the canonical `if target.outdated`.

  """
  return _task(updater, False)


def internalTask(updater: Callable[P, Target[T]]) -> Callable[P, Target[T]]:
  """Same as `task` except that the decorated function name will not be available when
  using `main` to process a command line."""
  return _task(updater, True)


def _task(updater: Callable[P, Target[T]], internal: bool) -> Callable[P, Target[T]]:
  taskName = updater.__name__

  @wraps(updater)
  def taskWrapper(*args: P.args, **kwargs: P.kwargs) -> Target:
    build = _getBuild()
    target = findTarget(taskName)
    if target is not None:
      return target

    build.enter(taskName)
    target = updater(*args, **kwargs)
    _finish(build, target, taskName)
    build.leave()
    return target

  if not internal:
    _DEFINED_TASKS[taskName] = taskWrapper
  return taskWrapper


def target[T](
  item: T,
  *dependencies: Target[Any],
  state: str | Callable[[T], str] | None = None,
) -> Target[T]:
  """Creates a target from within a `@task` decorated function.

  This is, in fact, required. And each `@task` may only call `target()` once and the
  task must return this same target. Some violations are captured, but beware.

  The `Target.name` of the returned target is the name of the calling `@task` function.
  ### Parameters
  - item: see `pythonbuilder.pythonbuilder.Target`
  - dependencies: see `pythonbuilder.pythonbuilder.Target`
  - state: see `pythonbuilder.pythonbuilder.Target`

  ### Return
  A pythonbuilder.pythonbuilder.Target with field `outdated` set to `True` if the
  target's item was determined to be out of date. The Target's `cmd` is not set, as
  the task based approach does not need it.
  """
  build = _getBuild()
  target = Target(item, *dependencies, state=state, name=build.current().name)
  if target.started:
    raise BuildException(
      "dependency loop detected for: '%s'<-'%s'"
      % (target.name, str(build.currentTasks))
    )
  target.started = True
  target.force = build.forced()
  startNanos = time.time_ns()
  fails = []
  triggering = []
  depsDigest = hashlib.sha256()
  for d in target.dependencies:
    if d.updated:
      depsDigest.update(build.states.getOwnHash(d).encode())
      if d.outdated:
        triggering.append(d.name)
    else:
      fails.append(d)
  if len(fails) > 0:
    raise BuildException(
      "dependencies where not updated, check their constructing functions: "
      + str(fails)
    )
  target.updated = True
  stateCurrent = (target.stateGenerator.provideState(), depsDigest.hexdigest())
  combinedOld = build.states.get(target)
  build.current().setActive(startNanos, stateCurrent, triggering)
  _LOG.debug(
    "  %s->%s:\n  old %s\n  new %s\n  force=%s",
    build.current().name,
    target.name,
    combinedOld,
    stateCurrent,
    target.force,
  )
  target.outdated = not build.doGraph and (combinedOld != stateCurrent or target.force)
  if not target.outdated and not build.doGraph:
    _LOG.log(_VERBOSE, "- " + build.current().name)
  return target


def _finish(build: _Build, target: Target, currentTask: str) -> None:
  info = build.current()
  took = _formatNanoDelta(info.startNanos, time.time_ns())
  stateAfter = target.stateGenerator.provideState()
  if _LOG.isEnabledFor(_VERBOSE) and target.outdated:
    trigger = ""
    if len(info.triggeringDeps) > 0:
      trigger = " <- " + ",".join(info.triggeringDeps)
    elif target.outdated and not target.force:
      trigger = " <- outdated"
    elif target.force:
      trigger = " <- forced"
    changed = "+" if info.stateCurrent[0] != stateAfter else "."
    _LOG.log(
      _VERBOSE, "%s %s(%s%s) (%s)", changed, currentTask, target.name, trigger, took
    )

  build.states.setHashes(target, stateAfter, info.stateCurrent[1])


def getTaskNames() -> list[str]:
  return list(_DEFINED_TASKS.keys())


def getTask(name: str) -> Callable[[], Target[Any]] | None:
  return _DEFINED_TASKS.get(name, None)


def toGraphviz() -> str:
  """Creates a dependency graph of the define targets in
  [graphviz](https://graphviz.org/) format.

  This needs to run all `@task`s in some arbitrary order in a way such `t.outdated`
  is always false. If all tasks correctly test `t.outdated` and do not touch the
  target to build, this has no side effects. Otherwise, obviously, the build's
  overall state may get messed up.

  ### Return
  A string which can be passed through one of the the graphviz renderers to create
  a dependency graph.
  """
  return _onTaskGraph(lambda: pbToGraphviz(set(_DEFINED_TASKS.keys())))


def _onTaskGraph(action: Callable[[], T]) -> T:
  global _CURRENTBUILD, _TARGETS
  keptBuild = _getBuild()
  keptTargets = pb._TARGETS
  _CURRENTBUILD = _Build()
  pb._TARGETS = dict()
  _getBuild().doGraph = True
  try:
    for f in _DEFINED_TASKS.values():
      f()
    return action()
  finally:
    pb._TARGETS = keptTargets
    _CURRENTBUILD = keptBuild


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
  build = _getBuild()
  (taskNames, forced, ll) = parseArgv(argv)
  if ll is not None:
    if not _setLogLevel(ll):
      return 1
  for t in forced:
    build.force(t)
  taskNames = forced + taskNames

  if not taskNames:
    ## FIXME: filter out or mark the internalTasks
    _onTaskGraph(lambda: printTargets(pb._TARGETS.values()))
    return 0

  functions = []
  for taskName in taskNames:
    updater = getTask(taskName)
    if updater is None:
      _LOG.error(f"{taskName}: no task with this name defined")
      return 1
    functions.append(updater)

  return _runBuild(_runTasks, functions)
