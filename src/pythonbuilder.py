"""
Define build targets with `Target` and run the build with `updateTargets()`.
The functions starting with "state" can be used for the ``state`` parameter
of `Target()`, but most have a string shortcut. See there.
"""

import time
_STARTTIME = time.time_ns()

import sys
import os
import hashlib
from typing import Any, TypeGuard
from collections.abc import Iterable, Collection, Callable
import itertools
from dataclasses import dataclass
from configparser import ConfigParser
import logging
import inspect
import subprocess
import json


logging.basicConfig(format='%(message)s (%(levelname)s)')
LOG = logging.getLogger()
"""The logger we use, initialized to level "INFO".

For consistent logging, the build process can import this and use it too rather
than creating its own.

"""
LOG.setLevel("INFO")

## FIXME: get rid of global variables and encapsulate in a Builder class
## or so.
## FIXME: remove mutable state from Target, keep it in a separate object,
##        but check if it worth it as inspection during the build is more
#         difficult
_TARGETS = dict()
_ALIAS: dict[str, str] = dict()

## FIXME: only here for tests, should be properly injectable
STATEFILE = os.path.join("build", "states")
"""Path of the file in which to persist the target states.

To force all targets to be rebuild, delete this file. (FIXME: provide proper
api).

"""

class BuildException(Exception): #{
  """Raised on failures detected by pythonbuilder."""
  def __init__(self, message):
    self.message = message
#}

## FIXME: We should make Target generic in the first parameter and
## - call this parameter data
## - rename alias to name
## - require a name if the data is not of type str
## This would allow to store arbitrary data in a Target which may
## help to run commands on it.
## Alternatively add an optional (generic) field data for this feature.
## Example: a Target bringing along a MavenArtifact
## (Not that the latter can be done by users anyway in python.)
##
## FIXME: we should have a stateForward as a middle ground between fixed and
## new. This state should change independent of the target itself iff the
## dependency state changed.
@dataclass(init=False, eq=False)
class Target: #{
  """
  Represents a target with its dependencies, how to compute its state
  (hashed content, fingerprint), how to (re-)create it and an optional alias.
  """

  def __init__(self, name: str,
               *dependencies, #: 'Target' | str,
               state: str | Callable[['Target'], str] | None = None,
               alias: str = None,
               cmd: Callable[['Target'],None] | None = None,
               ): #{
    """
    Creates a new Target.

    An "input target", for example a source code directory, may 
    may be created with just a name, as it has no dependencies, the state
    generator is derived automatically, because it is an existing directory,
    and nothing needs to be done, so it has no command.

    :param name: represents the target, like a file or directory name
    :param dependencies: the dependencies of this target
    :param state: describes how to generate a state (checksum, fingerprint)
      for this target. The function must generate a small fingerprint for the
      `Target`. If not provided, the `name` must denote an **existing** file
      or directory. If given as a string, it must be "dir", "file", "new" or
      "fixed" for `stateDirContent`, `stateFileContent`, `stateNew` or
      `stateFixed` respectively.
    :param alias: An alterantive name for the target which is easier to use,
      say, on the command line. If the target name is like "build/stuff/bla.html"
      then the alias could be just "bla", for example.
    :param cmd: Defines which command to run to (re-)create the target.
    """
    if name in _TARGETS:
      raise BuildException("'%s' defined already" % name)

    stateGenerator: Callable[[Target],str]
    match state:
      case "dir":
        stateGenerator = stateDirContent
      case "file":
        stateGenerator = stateFileContent
      case "new":
        stateGenerator = stateNew
      case "fixed":
        stateGenerator = stateFixed
      case None:
        if os.path.isdir(name):
          stateGenerator = stateDirContent
        elif os.path.isfile(name):
          stateGenerator = stateFileContent
        else:
          raise BuildException(("'%s' does not exist, cannot determine state" +
                                " generator, provide one with state=") % name)
      case _:
        if self._isStateGenerator(state):
          stateGenerator = state
        else:
          raise BuildException("'%s' is not a function of Target" % state)

    self.name: str = name
    """The name of the target, often a file or directory path."""

    self.alias: str | None = alias
    """Alternative name more suitable to use on the command line"""

    # FIXME: remove single quotes in python 3.14
    self.generateState: Callable[['Target'], str] = stateGenerator
    """Function to generate the state for the target"""

    self.cmd: Callable[['Target'], None] | None = cmd
    """Function to (re-)create the target."""

    self.dependencies = []
    """The target's dependencies."""

    for dep in dependencies:
      d = findTarget(dep)
      if d is not None:
        self.dependencies.append(d)
      else:
        raise BuildException(("dependency '%s' is neither Target nor can be" +
                               " mapped to a target") % dep)
    self.started: bool = False
    """Set during `updateTargets` when this target is considered for updating."""
    self.updated: bool = False
    """Set during `updateTargets` as soon as all dependencies are done."""

    self.recreated: bool = False  
    """Set during `updateTargets` if this target was out-of-date and its
    command was run. This does not say whether the target actually changed."""
    
    if not self.alias is None:
      _ALIAS[self.alias] = name
    _TARGETS[name] = self

  def _isStateGenerator(self, g: Any) -> TypeGuard[Callable[['Target'], str]]:
    if not callable(g):
      return False
    ## FIXME: add better test to fail early
    return True
#}

def findTarget(target: str | Target) -> Target | None: #{
  """
  Looks up a target by its name or its alias. For convenience, if the
  parameter is already a `Target`, it is returned as is.
 
  :param target: to look up
  :return: either the target or ``None``
  """
  if isinstance(target, Target):
    return target
  mapped: str = _ALIAS.get(target, target)
  return _TARGETS.get(mapped, None)
#}

def stateNew(_t: Any = None) -> str:
  """Returns a state string which is never the same, independent of the
  input.
  """
  return str(time.time_ns());

def stateFixed(_t: Target) -> str:
  """Always returns the same state string, independent of the input."""
  return "0"

def stateDirContent(target: Target) -> str:
  """Feeds all recursively contained files of a directory into
  `stateFileIteratorContent`.

  :param target: the name of which is used as the directory to traverse.
  :return: a hash
  """
  it = itertools.chain.from_iterable(
    map(lambda triple: map(lambda f: os.path.join(triple[0], f), triple[2]),
        os.walk(target.name))
  )
  return stateFileIteratorContent(it);

def stateFileContent(target: Target) -> str:
  """
  Feeds the name of the target is a single file nam into `stateFileIteratorContent`
  and returns the result.

  :param target: the name of which is used as a file name
  :return: a hash
  """
  return stateFileIteratorContent([target.name])

##
# Computes a state over all dependencies, ignoring the target itself.  Used for
# targets which merely combine a bunch of other targets and have no state on
# their own. They should trigger their dependents iff the dependencies change.
#
# FIXME: We need access to the _StateStore here. Rather than hackily inject the
# the state store into every Target, try to move this function into a class
# which has the state store as a field.
# Problem: when a Target is created we are far from having
# a state store anywhere near.
def _stateDepsOnly( target: Target) -> str:
  pass

def stateFileIteratorContent(it: Iterable[str]) -> str:
  """Creates a combined state over files provided by the iterator.

  If a path string from the iterator exists in the file system, its content is
  fed into the checksum, otherwise a `stateNew` is fed in. If the path string
  denotes a directory, this function fails.

  To make a difference between sets non existing files, all file names are
  also hashed.

  :param it: an iterator over path names of files, which may or may not exist.
  :return: a hash of all file names and file contents.
  """
  digest = hashlib.sha256()
  for fname in it:
    digest.update(fname.encode())
    if os.path.exists(fname):
      with open(fname, "rb") as file:
        digest.update(file.read())
    else:
      digest.update(stateNew().encode())
  return digest.hexdigest()

def resetTraversalState():
  """Resets the traversal state in all targets.

  If `updateTargets` is run again afterwards, it considers all targets in
  turn again. NOTE: this does not reset the persited target state, so without
  changing any data, a subsequent run of `updateTargets` should do nothing,
  except the build process is not set up optimally.
  """
  LOG.debug("  resetting traversal state")
  for target in _TARGETS.values():
    target.started = False
    target.updated = False
    target.recreated = False

_UNITS = [("ns", 10000, 1000),
         ("µs", 10000, 1000),
         ("ms", 10000, 1000),
         ("s", 120, 60),
         ]
def _formatNanoDelta(start: int, now: int) -> str:
  delta = now - start
  for i in range(0, len(_UNITS)):
    if delta < _UNITS[i][1]:
      return "%s%s" %(delta, _UNITS[i][0])
    delta = delta // _UNITS[i][2]
  return "%s%s" %(delta, "min")

def flatten(result: list[str], l: Iterable) -> None:
  """Flattens a multiply nested Iterable into the given result.

  :param result: to which elements are appended
  :param l: either a string or an Iterable containing only str or
    Iterable satisfying the same constraint.
  """
  if isinstance(l, str):
    result.append(l)
    return
  if not isinstance(l, Iterable):
    raise TypeError("parameter must be Iterable but is %s" % l)
  for elem in l:
    flatten(result, elem)

def logcmd(cmd: list[str]):
  """A standard way to log external commands. These are often run with
  ``subprocess.run()`` which accepts a string list as the command line. This is
  the standard way to log the command list also used by `pbexec`.
  """
  LOG.info("* %s", " ".join(cmd))

def pbexec(*args):
  """
  Shallow wrapper around
  `subprocess.run() <https://docs.python.org/3/search.html?q=subprocess.run>`_.

  It
  - logs the command line at ``INFO`` level
  - runs ``subprocess.run()`` with the flattened input list
  - calls ``check_returncode()`` on the result

  If you need more, use ``subprocess.run()`` directly, possibly with `flatten`.

  :param args: a possibly multiply-nested list of ``str``
  """
  cmd = []
  flatten(cmd, args)
  logcmd(cmd)
  subprocess.run(cmd).check_returncode()

def updateTargets(*targets: str | Target):
  """Updates all targets in turn without resetting the traversal state in
  between, so if target T1 depends on target T0, in th call ``updateTargets(T1,
  T0)``, the T0 is redundant, because it will be updated already when doing T1.

  :param targets: a ``str`` provided is looked up with `findTarget`

  """
  buildStart = time.time_ns()
  LOG.info("  startup took %s", _formatNanoDelta(_STARTTIME, buildStart))
  states = _StateStore(STATEFILE)
  for t in targets:
    target = findTarget(t)
    if target is None:
      raise BuildException("target '%s' not defined" % t)
    _updateTarget(states, target, [])
  states.save()
  buildEnd = time.time_ns()
  LOG.info("✓ build took %s, total %s",
           _formatNanoDelta(buildStart, buildEnd),
           _formatNanoDelta(_STARTTIME, buildEnd))

def _updateTarget(states: '_StateStore',
                  target: Target,
                  onbehalf: list[Target]):
  logTag = target.name \
    if target.alias is None \
       else "%s(%s)" % (target.alias, target.name)
  LOG.debug(". " + logTag)

  if target.started:
    raise BuildException("dependency loop detected: '%s'<-'%s'"
                         % (target, onbehalf))
  target.started = True

  triggeringDeps = []
  depsDigest = hashlib.sha256()
  for dep in target.dependencies:
    if not dep.updated:
      _updateTarget(states, dep, [target] + onbehalf)
    depsDigest.update(states.getOwnHash(dep).encode())
    if dep.recreated:
      triggeringDeps.append(dep.name)

  target.updated = True

  targetStateBefore = target.generateState(target)
  depsState = depsDigest.hexdigest()

  old = states.get(target)
  fresh = (targetStateBefore, depsState)
  #LOG.debug("  old %s\n  new %s", old, fresh)
  if old == fresh:
    LOG.info("- " + logTag)
    return

  cmdName: str = ""
  startNanos = time.time_ns()
  if target.cmd is not None:
    cmdName = target.cmd.__name__
    target.cmd(target)
  took = _formatNanoDelta(startNanos, time.time_ns())
  if len(triggeringDeps) == 0:
    LOG.info("+ %s(%s): outdated, %s", cmdName, target.name, took)
  else:
    LOG.info("+ %s(%s): <- %s, %s",
             cmdName, target.name, ", ".join(triggeringDeps), took)


  target.recreated = True
  targetStateAfter = target.generateState(target)
  states.setHashes(target, targetStateAfter, depsState)

def _escdq(s: str) -> str:
  return s.replace('"', '\\"')

def _targetToGraphviz(target: Target) -> str:
  result = ""
  for dep in target.dependencies:
    result += f'  "{_escdq(dep.name)}" -> "{_escdq(target.name)}"'

  if target.alias is not None:
    result += (f'"{_escdq(target.name)}"[label=<{_escdq(target.alias)}' +
               f'<BR/><FONT POINT-SIZE="10">{_escdq(target.name)}</FONT>>]')
  return result

def toGraphviz() -> str:
  """Creates the dependency graph of all targets in `dot <https://graphviz.org>`_
  format.

  Can be used to pipe through the 'dot' program to create an SVG or PDF. The
  suggested use is to define a target and let it depend on the build script.

  :return: graph in dot format

  """
  result = "digraph {"

  for target in _TARGETS.values():
    result += _targetToGraphviz(target)

  result += "}"
  return result

########################################################################

class _StateStore:
  def __init__(self, stateFile: str):
    self.stateFile = stateFile
    self.hashes: dict[str, tuple[str,str]]
    if not os.path.isfile(self.stateFile):
      LOG.debug("  no file '%s', starting with empty states"
                % self.stateFile)
      self.hashes = dict()
      return

    LOG.debug("  reading %s" % self.stateFile)

    with open(self.stateFile, "r", encoding="UTF-8") as statefile:
      self.hashes = json.load(statefile)

    ## prefer a tuple (pair) over a list for the two hashes per target
    for (key, value) in self.hashes.items():
      self.hashes[key] = (value[0], value[1])

  def __repr__(self):
    return "_StateStore[%s]" % self.hashes

  def setHashes(self,
                target: Target,
                targetHash: str,
                depsHash: str):
    self.hashes[target.name] = (targetHash, depsHash)

  def get(self, target: Target) -> tuple[str, str]:
    return self.hashes.get(target.name, ("", ""))

  def getOwnHash(self, target: Target) -> str:
    return self.hashes[target.name][0]

  def getDepsHash(self, target: Target) -> str:
    return self.hashes[target.name][1]

  def save(self):
    LOG.debug("  writing %s" % self.stateFile)
    os.makedirs(os.path.dirname(self.stateFile), exist_ok=True)

    with open(self.stateFile, "w", encoding="UTF-8") as statefile:
      json.dump(self.hashes, statefile, indent=2)
