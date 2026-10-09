#!/usr/bin/env python3
## See https://stackoverflow.com/a/33533514/2954288
## for use of class as type annotations before class is fully defined
from __future__ import annotations

import hashlib
import time
from functools import wraps
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

class _TaskInfo:
  def __init__(self, startNanos: int, stateCurrent: tuple[str, str],
               triggeringDeps: list[str]):
    self.startNanos = startNanos
    self.stateCurrent = stateCurrent
    self.triggeringDeps = triggeringDeps

class _Build:
  def __init__(self) -> None:
    self.states = _StateStore(getStatefile())
    self._forced: set[str] = set()
    self._hasTarget: set[str] = set()
    self._taskStack: list[str] = []
    self._taskInfo: dict[str, _TaskInfo] = dict()

  def currentTasks(self) -> list[str]:
    return list(self._taskStack)

  def setInfo(self, info: _TaskInfo) -> None:
    self._taskInfo[self.current()] = info

  def getInfo(self) -> _TaskInfo:
    return self._taskInfo[self.current()]

  def hasObtainedTarget(self) -> bool:
    return self.current() in self._hasTarget

  def targetObtained(self) -> None:
    task = self.current()
    if task in self._hasTarget:
      raise BuildException(f"target() called twice in a task {task}")
    self._hasTarget.add(task)

  def current(self) -> str:
    return self._taskStack[-1]

  def enter(self, taskName: str) -> None:
    self._taskStack.append(taskName)

  def leave(self) -> None:
    self._taskStack.pop()

  def force(self, tname: str) -> None:
    self._forced.add(tname)

  def forced(self) -> bool:
    return self._taskStack[-1] in self._forced


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
    # print("x main: get", task, "->", updater)
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


def task(updater: Callable[[], Target]) -> Any:
  taskName = updater.__name__

  @wraps(updater)
  def taskWrapper() -> Target:
    # print("taskWrapper called for", updater)
    build = _getBuild()
    build.enter(taskName)
    target = findTarget(taskName)
    if target is None:
      # print("running", updater)
      target = updater()
      if not build.hasObtainedTarget():
        raise BuildException(f"{taskName}: task failed to call target()")
      _finish(build, target, taskName)
      _TARGETS[taskName] = target
    build.leave()
    return target

  _DEFINED_TASKS[taskName] = taskWrapper
  return taskWrapper

def target(
  item: T,
  *dependencies: Target,
  state: str | Callable[[T], str] | None = None,
  name: str | None = None,
) -> Target:
  target = Target(item, *dependencies, state=state, name=name)
  build = _getBuild()
  build.targetObtained()
  if target.updated:
    return target
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
  build.setInfo(_TaskInfo(startNanos, stateCurrent, triggering))

  _LOG.debug(
    "  %s:%s:\n  old %s\n  new %s\n  force=%s",
    target.name,
    combinedOld,
    stateCurrent,
    target.force,
  )
  target.outdated = combinedOld != stateCurrent or target.force
  if not target.outdated:
    _LOG.log(_VERBOSE, "- " + build.current())
  return target

def _finish(build: _Build, target: Target, currentTask: str) -> None:
  info = build.getInfo()
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
    _LOG.log(_VERBOSE, "%s %s(%s%s) (%s)", changed, currentTask, target.name, trigger, took)
    
  build.states.setHashes(target, stateAfter, info.stateCurrent[1])
