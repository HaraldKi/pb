#!/usr/bin/env python3
## See https://stackoverflow.com/a/33533514/2954288
## for use of class as type annotations before class is fully defined
from __future__ import annotations

import hashlib
import time
from functools import wraps
from typing import Any, Callable, Concatenate, cast

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
_DEFINED_TASKS: dict[str, Callable[[], Target2]] = dict()


class _Build:
  def __init__(self) -> None:
    self.states = _StateStore(getStatefile())
    self._forced: set[str] = set()
    self._hasTarget: set[str] = set()
    self._taskStack: list[str] = []

  def currentTasks(self) -> list[str]:
    return list(self._taskStack)

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


def getBuild() -> _Build:
  global _CURRENTBUILD
  if _CURRENTBUILD is None:
    _CURRENTBUILD = _Build()
  return _CURRENTBUILD


def main(argv: list[str]) -> bool:
  build = getBuild()
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
    getBuild().states.save()


def target(
  item: T,
  *dependencies: Target2,
  state: str | Callable[[T], str] | None = None,
  name: str | None = None,
  cmd: Callable[Concatenate[T, ...], None] | None = None,
) -> Target2:
  t = Target2(item, *dependencies, state=state, name=name, cmd=cmd)
  build = getBuild()
  build.targetObtained()
  t.prepare(build)
  return t


def task(updater: Callable[[], Target2]) -> Any:
  taskName = updater.__name__

  @wraps(updater)
  def taskWrapper() -> Target2:
    # print("taskWrapper called for", updater)
    build = getBuild()
    build.enter(taskName)
    target = findTarget(taskName)
    if target is None:
      # print("running", updater)
      target = updater()
      target.finish(taskName)
      _TARGETS[taskName] = target
    else:
      target = cast(Target2, target)
      # print("skipping already done", updater)
      pass
    build.leave()
    return target

  _DEFINED_TASKS[taskName] = taskWrapper
  return taskWrapper


class Target2(Target):
  def __init__(
    self,
    item: T,
    *dependencies: Target[Any],
    state: str | Callable[[T], str] | None = None,
    name: str | None = None,
    cmd: Callable[Concatenate[T, ...], None] | None = None,
  ) -> None:
    super().__init__(item, *dependencies, state=state, name=name, cmd=cmd)
    self.entered = False
    self.outdated = True
    self._startNanos = 0

  def prepare(self, build: _Build) -> Target2:
    if self.updated:
      return self
    if self.started:
      raise BuildException(
        "dependency loop detected for: '%s'<-'%s'"
        % (self.name, str(build.currentTasks))
      )
    self.started = True
    self._startNanos = time.time_ns()

    fails = []
    triggering = []
    depsDigest = hashlib.sha256()
    for d in self.dependencies:
      if d.updated:
        depsDigest.update(build.states.getOwnHash(d).encode())
        if d.recreated:
          triggering.append(d)
      else:
        fails.append(d)
    if len(fails) > 0:
      raise BuildException(
        "dependencies where not updated, check their constructing functions: "
        + str(fails)
      )

    self._stateCurrent = (self.stateGenerator.provideState(), depsDigest.hexdigest())
    combinedOld = build.states.get(self)
    forced = build.forced()
    _LOG.debug(
      "  %s:%s:\n  old %s\n  new %s\n  force=%s",
      self.name,
      combinedOld,
      self._stateCurrent,
      forced,
    )
    self.outdated = combinedOld != self._stateCurrent or forced
    if not self.outdated:
      _LOG.log(_VERBOSE, "- " + build.current())
    return self

  def finish(self, currentTask: str) -> None:
    if self.updated:
      return
    self.updated = True
    took = _formatNanoDelta(self._startNanos, time.time_ns())
    stateAfter = self.stateGenerator.provideState()
    if self._stateCurrent[0] != stateAfter:
      # only half true, as the command, may have re-created the same state
      self.recreated = True
      _LOG.log(_VERBOSE, "+ %s(%s)", currentTask, took)
    elif self.outdated:
      _LOG.log(_VERBOSE, ". %s(%s)", currentTask, took)
    getBuild().states.setHashes(self, stateAfter, self._stateCurrent[1])
