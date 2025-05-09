"""
Define build targets with `Target` and run the build with `updateTargets()`.
The functions starting with "state" can be used for the ``state`` parameter
of `Target()`, but most have a string shortcut. See there.
"""

## See https://stackoverflow.com/a/33533514/2954288
## for use of class as type annotations before class is fully defined
from __future__ import annotations

import time
import sys
import os
import hashlib
from typing import TypeVar, Generic, Hashable, Any, TypeGuard
from collections.abc import Iterable, Collection, Callable
import itertools
from dataclasses import dataclass
from configparser import ConfigParser
import logging
import inspect
import subprocess
import json
from pathlib import Path

logging.basicConfig(format='%(message)s (%(levelname)s)')
logging.addLevelName(logging.INFO - 5, "VERBOSE")
logging.Logger.verbose = lambda instance, msg, *args, **kwargs: \
  instance.log(logging.INFO - 5, msg, *args, **kwargs)

LOG = logging.getLogger()
"""The logger we use.

For consistent logging, the build script can import and use it too, rather than
creating its own. This logger is used by ``pythonbuilder`` throughout. It has
the additional level VERBOSE. If the environment variable PBLOGLEVEL is set, it
is used as the default, otherwise it is ``"INFO"``. The levels are used as
follows:

- INFO: Show only output from `logcmd` which, in particular, is used by
  `pbexec`, but is also recommended to be used for target generating commands
  which don't call external programs.

- VERBOSE: also show targets considered and whether they are determined
  up-to-date or not

"""

LOG.setLevel(
  "INFO" if "" == os.environ.get("PBLOGLEVEL", "") else os.environ["PBLOGLEVEL"]
)


## FIXME: only here for tests, should be properly injectable
STATEFILE = Path("build", "pbstates")
"""Path of the file in which to persist the target states.

To force all targets to be rebuild, delete this file. (FIXME: provide proper
api).
"""

class BuildException(Exception): #{
  """Raised on failures detected by pythonbuilder."""
  def __init__(self, message):
    self.message = message
#}

## From Python 3.12, not needed anymore, see:
## https://mypy.readthedocs.io/en/stable/generics.html
T = TypeVar('T', bound=Hashable)
"""The data type wrapped by a `Target`"""

## FIXME: we should have a stateForward as a middle ground between fixed and
## new. This state should change independent of the target itself iff the
## dependency state changed.
@dataclass(init=False, eq=False)
class Target(Generic[T]): #{
  """Represents a target with an item to create, its dependencies, how to
  compute its state (hashed content, fingerprint), how to (re-)create it and an
  optional nice name.
  """

  def __init__(self, item: T,
               *dependencies, #: 'Target' | str,
               state: str | Callable[[Target[T]], str] | None = None,
               name: str = None,
               cmd: Callable[[Target[T]], None] | None = None,
               ): #{
    """
    Creates a new Target.

    An "input target", for example a source code directory, may 
    may be created with just an item, as it has no dependencies, the state
    generator is derived automatically, because it is an existing directory,
    and nothing needs to be done, so it has no command.

    :param item: represents the target, like a file or directory name
    :param dependencies: the dependencies of this target
    :param state: describes how to generate a state (checksum, fingerprint)
      for this target. The function must generate a small fingerprint for the
      `Target`. If not provided, the `item` must denote an **existing** file
      or directory. If given as a string, it must be "dir", "file", "new" or
      "fixed" for `stateDirContent`, `stateFileContent`, `stateNew` or
      `stateFixed` respectively.
    :param name: A nice name for the target to use, for example, on the command
      line. The default is ``str(item), so if it is like
      ``Path("build", "stuff", "woo.html")``
      then the name could be just "woo", for example.
    :param cmd: Defines which command to run to (re-)create the target.
    """
    stateGenerator: Callable[[Target], str]
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
        if isinstance(item, Path) and item.is_dir():
          stateGenerator = stateDirContent
        elif isinstance(item, Path) and item.is_file():
          stateGenerator = stateFileContent
        else:
          raise BuildException(("'%s' is neither a file nor a directory," +
                                " cannot determine state" +
                                " generator, provide one with state=") % item)
      case _:
        if _isStateGenerator(state):
          stateGenerator = state
        else:
          raise BuildException("'%s' is not a function of Target" % state)

    self.item: T = item
    """The item of the target, often a file or directory path."""

    self.name: str = str(item) if name is None else name
    """Alternative name more suitable to use on the command line"""

    self.generateState: Callable[[Target], str] = stateGenerator
    """Function to generate the state for the target"""

    self.cmd: Callable[[Target[T]], None] | None = cmd
    """Function to (re-)create the target."""

    self.dependencies = []
    """The target's dependencies."""

    for dep in dependencies:
      d = findTarget(dep)
      if d is not None:
        self.dependencies.append(d)
      else:
        raise BuildException(("dependency '%s' of '%s' is neither Target nor" +
                              " can be mapped to a target") % (dep, self.name))
    self.started: bool = False
    """Set during `updateTargets` when this target is considered for updating."""
    self.updated: bool = False
    """Set during `updateTargets` as soon as all dependencies are done."""

    self.recreated: bool = False  
    """Set during `updateTargets` if this target was out-of-date and its
    command was run. This does not say whether the target actually changed."""
    
    if self.name in _TARGETS:
      raise BuildException("'%s' defined already" % item)

    _TARGETS[self.name] = self

  def __repr__(self):
    deps = ", ".join([d.name for d in self.dependencies])
    if len(deps) == 0:
      deps = "-"
    s = self.generateState.__name__
    c = ", cmd=" + self.cmd.__name__ if self.cmd is not None else ""
    return f"Target({self.name}, {deps}, name={self.name}," + \
      f" state={s}{c})"
#}

## FIXME: get rid of global variables and encapsulate in a Builder class
## or so.
## FIXME: remove mutable state from Target, keep it in a separate object,
##        but check if it worth it, as inspection during the build is more
#         difficult
_TARGETS: dict[str, Target] = dict()

def findTarget(target: str | Target) -> Target | None: #{
  """Looks up a target by its name. For convenience, if the parameter is
  already a `Target`, it is returned as is.
 
  :param target: to look up
  :return: either the target or ``None``
  """
  if isinstance(target, Target):
    return target
  return _TARGETS.get(target, None)
#}

def stateNew(_t: Any = None) -> str:
  """Returns a state string which is never the same, independent of the
  input.
  """
  return str(time.time_ns());

def stateFixed(_t: Target) -> str:
  """Always returns the same state string, independent of the input."""
  return "0"

def stateDirContent(target: Target[Path]) -> str:
  """Feeds all recursively contained files of a directory into
  `stateFileIteratorContent`.

  :param target: the item of which is used as the directory to traverse.
  :return: a hash
  """
  if target.item.is_file():
    raise BuildException("'%s' is a file but expected a directory"
                         % target.item)
  return stateFileIteratorContent(lambda: target.item.rglob("*"))

def stateFileContent(target: Target[Path]) -> str:
  """
  Feeds the item of the target as a single file name into `stateFileIteratorContent`
  and returns the result.

  :param target: the item of which is used as a file name
  :return: a hash
  """
  if target.item.is_dir():
    raise BuildException("'%s' is a directory but expected a file"
                         % target.item)
  return stateFileIteratorContent(lambda: [target.item])


def _isStateGenerator(g: Any) -> TypeGuard[Callable[[Target[T]], str]]:
  if not callable(g):
    return False
  ## FIXME: add better test to fail early
  try:
    signature = inspect.signature(g)
  except:
    return False
  if signature.parameters is None or len(signature.parameters) != 1:
    return False
  return True

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

def stateFileIteratorContent(itGen: Callable[[], Iterable[Path]]) -> str:
  """Creates a combined state over files provided by the iterable.

  If a path string from the iterator exists in the file system, its content is
  fed into the checksum, otherwise a `stateNew` is fed in. If the path string
  denotes a directory, it is ignored. This is a convenience to be able
  to use this with ``Path.rglob()`` without extra directory name filter.

  To make a difference between sets of non existing files, all file names are
  also hashed.

  :param itGen: a supplier providing an iterator over path names of files
    which may or may not exist.
  :return: a hash of all file names and file contents. If the iterator is empty,
    or contains only empty directories, `stateNew()` is returned.
  """
  digest = hashlib.sha256()
  found = False
  for path in itGen():
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

def resetTraversalState():
  """Resets the traversal state in all targets.

  If `updateTargets` is run again afterwards, it considers all targets in
  turn again.

  NOTE: this does not reset the persited target state, so without
  changing any data, a subsequent run of `updateTargets` should do nothing.
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
  `subprocess.run() <https://docs.python.org/3/search.html?q=subprocess.run>`_
  which

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
  ## Somewhat off as it excludes sleep times, found no way to get those.
  ## Do not use psutil.create_time() it can be off by 999ms.
  startNanos = buildStart - time.process_time_ns()
  LOG.verbose("  startup took %s", _formatNanoDelta(startNanos, buildStart))

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
           _formatNanoDelta(startNanos, buildEnd))

def _updateTarget(states: '_StateStore',
                  target: Target[T],
                  onbehalf: list[Target]):
  if target.started:
    raise BuildException("dependency loop detected: '%s'<-'%s'"
                         % (target, onbehalf))
  target.started = True
  logTag = target.name

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

  strItem = str(target.item)
  logTag = target.name
  if logTag != strItem:
    logTag = logTag+":"+strItem

  old = states.get(target)
  fresh = (targetStateBefore, depsState)
  LOG.debug("  %s:\n  old %s\n  new %s", logTag, old, fresh)
  if old == fresh:
    LOG.verbose("- " + logTag)
    return

  cmdName: str = "no-op"
  startNanos = time.time_ns()
  if target.cmd is not None:
    cmdName = target.cmd.__name__
    target.cmd(target)
  took = _formatNanoDelta(startNanos, time.time_ns())
  if len(triggeringDeps) == 0:
    LOG.verbose("+ %s(%s): outdated, %s", cmdName, logTag, took)
  else:
    LOG.verbose("+ %s(%s): <- %s, %s",
                cmdName, logTag, ", ".join(triggeringDeps), took)


  target.recreated = True
  targetStateAfter = target.generateState(target)
  states.setHashes(target, targetStateAfter, depsState)

def _escdq(s: str) -> str:
  return s.replace('"', '\\"')

def _targetToGraphviz(target: Target) -> str:
  result = ""
  for dep in target.dependencies:
    result += f'  "{_escdq(dep.name)}" -> "{_escdq(target.name)}"'

  if target.name != str(target.item):
    result += (f'"{_escdq(target.name)}"[label=<{_escdq(target.name)}' +
               f'<BR/><FONT POINT-SIZE="10">{_escdq(str(target.item))}</FONT>>]')
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

def registerDependencyGraphTarget(
    graphFile: Path,
    name: str,
    buildscript: Target[Path] | Path = Path("pb")) -> Target[Path]:
  
  """Creates two targets, one for the build script, if provided and one for
  the dependencies graph. The extension of the ``graphFile`` will be used
  as the image type requested from the ``dot`` program. If the ``buildscript``
  is already a ``Target`` it is used as the dependency.

  :param graphFile: to create with the dependency graph after converting the
    output of `toGraphviz`.
  :param name: of the ``Target`` for the graph file
  :param buildscript: to depend on such that the graph is re-created if the
    script changes
  :return: the ``Target`` for the dependency graph
  """
  dep = buildscript if isinstance(buildscript, Target) else Target(buildscript)
  return Target(graphFile, dep, name=name, state="file", cmd=graphToDot)

def graphToDot(target: Target[Path]):
  """Convenience function to call `toGraphviz()` and pass the output through
  the ``dot`` program, writing the image file to the ``target.item``.
  """
  result = toGraphviz()
  filetype = target.item.suffix[1:]
  cmd = ["dot", "-T" + filetype, "-Grankdir=LR"]
  logcmd(cmd)
  with open(target.item, "w", encoding="utf-8") as out:
    subprocess.run(cmd, input=result, encoding="utf-8", stdout=out)

########################################################################

class _StateStore:
  def __init__(self, stateFile: Path):
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
