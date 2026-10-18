#!/usr/bin/env python3
"""An alternative and simpler approach to define targets, dependencies and how to build
them.

The canonical use to define a task which creates a target looks like:
```python
@task
def stuff() -> None:
  dep1 = dependency1()
  dep2 = dependency2()
  f = Path("build/file")
  if isDone(file, dep1, dep2, state="file"):
    return
  pbexec("compile", f, dep1.item, dep2.item)
```
where the `@task` converts the function `stuff` into a build task, which
"""

## See https://stackoverflow.com/a/33533514/2954288
## for use of class as type annotations before class is fully defined
from __future__ import annotations

import hashlib
import time
from functools import partial, wraps
from typing import Any, Callable

from pythonbuilder.pbutil import _setLogLevel, parseArgv
from pythonbuilder.pythonbuilder import (
  _LOG,
  _TARGETS,
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

_CURRENTBUILD = None
_DEFINED_TASKS: dict[str, Callable[[], Target]] = dict()


class _TaskInfo[I]:
  def __init__(self, name: str, item: I) -> None:
    self.name = name
    self.item = item
    self.startNanos = -1
    self.stateCurrent: tuple[str, str] = ("", "")
    self.triggeringDeps: list[str] = []
    self.target: None | Target = None

  def setActive(
    self, startNanos: int, stateCurrent: tuple[str, str], triggeringDeps: list[str]
  ) -> None:
    self.startNanos = startNanos
    self.stateCurrent = stateCurrent
    self.triggeringDeps = triggeringDeps


class _Build:
  def __init__(self) -> None:
    self.states = _StateStore(getStatefile())
    self._forced: set[str] = set()
    self._taskStack: list[_TaskInfo] = []

  def currentTasks(self) -> list[str]:
    return [ti.name for ti in list(self._taskStack)]

  def enter[I](self, taskName: str, item: I) -> None:
    self._taskStack.append(_TaskInfo(taskName, item))

  def leave(self) -> None:
    self._taskStack.pop()

  def current(self) -> _TaskInfo:
    return self._taskStack[-1]

  def setTarget(self, target: Target) -> None:
    taskInfo = self.current()
    if taskInfo.target is not None:
      raise BuildException(f"target() called twice in a task {taskInfo.name}")
    taskInfo.target = target

  def force(self, taskName: str) -> None:
    self._forced.add(taskName)

  def forced(self) -> bool:
    return self.current().name in self._forced


def _getBuild() -> _Build:
  global _CURRENTBUILD
  if _CURRENTBUILD is None:
    _CURRENTBUILD = _Build()
  return _CURRENTBUILD


def main(argv: list[str]) -> bool:
  build = _getBuild()
  (tasks, forced, ll) = parseArgv(argv)
  if ll is not None:
    if not _setLogLevel(ll):
      return False
  for t in forced:
    build.force(t)
  tasks = forced + tasks

  functions = []
  for task in tasks:
    updater = _DEFINED_TASKS.get(task, None)
    if updater is None:
      _LOG.error(f"{task}: no task with this name defined")
      return False
    functions.append(updater)

  return _runBuild(_runTasks, functions)


def _runTasks(functions: list[Callable[[], Any]]) -> None:
  try:
    for f in functions:
      f()
  finally:
    _getBuild().states.save()


def task[I](item: I) -> Callable[[Callable[[I], None]], Callable[[], Target[I]]]:
  return partial(_task, item)


def _task[I](item: I, updater: Callable[[I], None]) -> Callable[[], Target[I]]:
  taskName = updater.__name__

  @wraps(updater)
  def taskWrapper() -> Target:
    build = _getBuild()
    target = findTarget(taskName)
    if target is not None:
      return target

    build.enter(taskName, item)
    updater(item)
    target = build.current().target
    if target is None:
      raise BuildException(f"{taskName}: task failed to call target()")
    _finish(build, target, taskName)
    _TARGETS[taskName] = target
    build.leave()
    return target

  _DEFINED_TASKS[taskName] = taskWrapper
  return taskWrapper


# We could write isDone=target, but pydoctor simply skips the doc then, so here we go
def isDone(
  *dependencies: Target,
  state: str | Callable[[T], str] | None = None,
) -> bool:
  """An alias for `target()` for more intuitive understanding of the return value.

  Consider the canonical code structure of a `task`.
  ```python
    @task
    def stuff() -> None:
      # ...
      if isDone(Path("stuff"), ...):
        return
      # do stuff
  ```
  Using ``isDone``, the meaning of the boolean return value is clearer than using
  ```python
  if target(...):
    return
  ```
  """
  return target(*dependencies, state=state)


def isOld(
  *dependencies: Target,
  state: str | Callable[[T], str] | None = None,
) -> bool:
  return not target(*dependencies, state=state)


def target(
  *dependencies: Target,
  state: str | Callable[[T], str] | None = None,
) -> bool:
  build = _getBuild()
  target = Target(build.current().item, *dependencies, state=state)
  build.setTarget(target)
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
  target.outdated = combinedOld != stateCurrent or target.force
  if not target.outdated:
    _LOG.log(_VERBOSE, "- " + build.current().name)
  return not target.outdated


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
