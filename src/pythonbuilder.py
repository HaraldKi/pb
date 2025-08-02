"""
Define build targets with `Target` and run the build with `updateTargets()`.
The functions starting with "state" can be used for the ``state`` parameter
of `Target()`, but most have a string shortcut. See there.
"""

## See https://stackoverflow.com/a/33533514/2954288
## for use of class as type annotations before class is fully defined
from __future__ import annotations

import hashlib
import inspect
import json
import logging
import os
import subprocess
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Concatenate, Generic, Hashable, TypeGuard, TypeVar, cast

logging.basicConfig(format='%(message)s (%(levelname)s)')
VERBOSE = logging.INFO - 5
"""Additional logging level providing more information than ``INFO``."""

logging.addLevelName(VERBOSE, "VERBOSE")

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

Set this before calling `updateTargets`.To force all targets to be rebuild,
delete this file. (FIXME: provide proper api).
"""

class BuildException(Exception): #{
  """Raised on failures detected by pythonbuilder."""
  def __init__(self, message: str) -> None:
    self.message = message
#}

## From Python 3.12, not needed anymore, see:
## https://mypy.readthedocs.io/en/stable/generics.html
T = TypeVar("T", bound=Hashable)
"""The data type wrapped by a `Target`."""

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
               *dependencies: Target[Any],
               state: str | Callable[[T], str] | None = None,
               name: str | None = None,
               cmd: Callable[Concatenate[T, ...], None] | None = None
               ): #{
    """Creates a new Target.

    An "input target", for example a source code directory, may be created with
    just an item, as it has no dependencies, the state generator is derived
    automatically, because it is an existing directory, and nothing needs to be
    done, so it has no command.

    :param item: represents the item to keep up-to-date, like a file or
      directory name
    :param dependencies: the dependencies of this target
    :param state: describes how to generate a state (checksum, fingerprint) for
      this target's item. The function must generate a small fingerprint.
      If not provided, the `item` must denote an **existing** file
      or directory. If given as a string, it must be "dir", "file", "new",
      "fixed" or "value" for `stateDirContent`, `stateFileContent`, `stateNew`,
      `stateFixed` or `stateValue` respectively.
    :param name: A nice name for the target to use, for example, on the command
      line. The default is name is ``str(item)``.
    :param cmd: the command to run to (re-)create the target. Its parameters will
      be the target's ``item`` as well as the items of all dependencies.
    """
    stateGenerator: Callable[[T], str]
    match state:
      case "dir":
        stateGenerator = cast(Callable[[T], str], stateDirContent)
      case "file":
        stateGenerator = cast(Callable[[T], str], stateFileContent)
      case "new":
        stateGenerator = stateNew
      case "fixed":
        stateGenerator = stateFixed
      case "value":
        stateGenerator = stateValue
      case None:
        if isinstance(item, Path) and item.is_dir():
          stateGenerator = cast(Callable[[T], str], stateDirContent)
        elif isinstance(item, Path) and item.is_file():
          stateGenerator = cast(Callable[[T], str], stateFileContent)
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
    """The target's name, defaulting to ``str(item)``.

    It can be used as parameter for `updateTargets`.
    """

    self.generateState: Callable[[T], str] = stateGenerator
    """Function to generate the state for the target."""

    self.cmd: Callable[Concatenate[T,...], None] | None = cmd
    """Function to (re-)create the target."""

    self.dependencies = dependencies
    """The target's dependencies."""

    self.started: bool = False
    """Set during `updateTargets` as soon as this target is considered for
    updating."""

    self.updated: bool = False
    """Set during `updateTargets` as soon as all dependencies are done.

    The target's command may or may not be run subsequently.
    """

    self.recreated: bool = False  
    """Set during `updateTargets` if this target was out-of-date and its
    command was run.

    This does not say whether the target was actually changed by running its
    ``cmd``.
    """
    
    if self.name in _TARGETS:
      raise BuildException("'%s' defined already" % item)

    _TARGETS[self.name] = self

  def __str__(self) -> str:
    """Readable short form for a ``Target``"""
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
  input

  This is subject to ``time.time_ns()`` changing more frequently than this
  function is called.

  :param _t: unused
  :return: a different implementation dependent string for each call
  """
  return str(time.time_ns())

def stateFixed(_t: Any = None) -> str:
  """Always returns the same state string, independent of the input.

  :param _t: unused
  :return: always the same implementation dependent string
  """
  return "0"

def stateValue(item: Any) -> str:
  """Computes a state string from ``item``, so it can be used for in-memory
  targets like, for example, a version string generated from the current date.

  :param item: to compute the state string from
  :return: an implementation dependent string is always the same for
    same ``t.item`` values and typically changes for changed ``t.item`` values
  """
  return repr(item)

def stateDirContent(targetPath: Path) -> str:
  """Feeds all recursively contained files of a directory into
  `stateFileIteratorContent`.

  :param targetPath: of the directory to compute the state from
  :return: a hash
  """
  if targetPath.is_file():
    raise BuildException("'%s' is a file but expected a directory"
                         % targetPath)
  return stateFileIteratorContent(lambda: targetPath.rglob("*"))

def stateFileContent(targetPath: Path) -> str:
  """Feeds the path a single file name into `stateFileIteratorContent` and
  returns the result.

  :param targetPath: of the file to compute the state from
  :return: a hash

  """
  if targetPath.is_dir():
    raise BuildException("'%s' is a directory but expected a file"
                         % targetPath)
  return stateFileIteratorContent(lambda: [targetPath])


def _isStateGenerator(g: Any) -> TypeGuard[Callable[[Any], str]]:
  if not callable(g):
    return False
  ## FIXME: add better test to fail early
  try:
    signature = inspect.signature(g)
  except Exception as _e:
    return False
  if signature.parameters is None or len(signature.parameters) != 1:
    return False
  return True

def stateFileIteratorContent(itGen: Callable[[], Iterable[Path]]) -> str:
  """Creates a combined state over files.

  If a path string from the iterator exists in the file system, its content is
  fed into the checksum, otherwise a `stateNew` is fed in. If the path string
  denotes a directory, it is ignored. This is a convenience to be able
  to use this with ``Path.rglob()`` without extra directory name filter.

  To make a difference between sets of non existing files, all file names are
  also hashed.

  Example: ``stateFileIteratorContent(lambda: Path("src").rglob("*.py"))`` will
  run all python files recursively found in ``src`` through a hash function
  and return the result
  
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

def resetTraversalState() -> None:
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

def flatten(result: list[str], nested: Any) -> None:
  """Flattens a multiply nested Iterable into the given result. Any element not
  ``Iterable`` and not ``str`` is added to the result as ``str(element)``

  :param result: to which elements are appended
  :param nested: either an ``Iterable`` to flatten or a string or other object to
    add to the result
  """
  if isinstance(nested, str):
    result.append(nested)
  elif  isinstance(nested, Iterable):
    for elem in nested:
      flatten(result, elem)
  else:
    result.append(str(nested))

def logcmd(cmd: list[str]) -> None:
  """A standard way to log external commands.

  These are often run with ``subprocess.run()`` which accepts a string list as
  the command line. This is the standard way to log the command list also used
  by `pbexec`.

  :param cmd: to log
  """
  LOG.info("* %s", " ".join(cmd))

def pbexec(*args: Any) -> None:
  """
  Shallow wrapper around
  `subprocess.run() <https://docs.python.org/3/search.html?q=subprocess.run>`_
  which

  - logs the command line at ``INFO`` level
  - runs ``subprocess.run()`` with the flattened input list
  - calls ``check_returncode()`` on the result

  If you need more, use ``subprocess.run()`` directly, possibly with `flatten`.

  :param args: a possibly multiply-nested list which will be flattened with
    `flatten` before passed to ``subprocess.run()``.
  """
  cmd: list[str] = []
  flatten(cmd, args)
  logcmd(cmd)
  subprocess.run(cmd).check_returncode()

def updateTargets(*targets: str | Target) -> None:
  """Wraps `rawUpdateTargets` to log times and trim any exception to
  just its message.
  """
  buildStart = time.time_ns()
  ## Somewhat off as it excludes sleep times, found no way to get those.
  ## Do not use psutil.create_time() it can be off by 999ms.
  ## BUT: according to docs, process_time_ns() has an undefined reference
  ## point, yet at least on Linux so far this seems to be close to 0 at
  ## process start. Hmm.
  startNanos = buildStart - time.process_time_ns()
  LOG.log(VERBOSE, "  startup took %s", _formatNanoDelta(startNanos, buildStart))

  resultState = ansiGreen("build ✔")
  try:
    rawUpdateTargets(*targets)
  except Exception as e:
    resultState = ansiRed("build ✘")
    if LOG.isEnabledFor(VERBOSE):
      logging.error(e, exc_info=True)
    else:
      logging.error(e)
  
  buildEnd = time.time_ns()
  LOG.info(resultState + ", took %s, total %s",
           _formatNanoDelta(buildStart, buildEnd),
           _formatNanoDelta(startNanos, buildEnd))

def rawUpdateTargets(*targets: str | Target) -> None:
  """Updates all targets in turn without resetting the traversal state in
  between, so if target T1 depends on target T0, in the call ``updateTargets(T1,
  T0)``, then T0 is redundant, because it will be updated already when doing T1.

  :param targets: the targets to update where any ``str`` argument is looked up
    with `findTarget`
  """
  states = _StateStore(STATEFILE)
  for t in targets:
    target = findTarget(t)
    if target is None:
      raise BuildException("target '%s' not defined" % t)
    _updateTarget(states, target, [])
  states.save()
  
def _updateTarget(states: '_StateStore',
                  target: Target[T],
                  onbehalf: list[Target]) -> None:
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

  targetStateBefore = target.generateState(target.item)
  depsState = depsDigest.hexdigest()

  strItem = str(target.item)
  logTag = target.name
  if logTag != strItem:
    logTag = logTag+":"+strItem

  old = states.get(target)
  fresh = (targetStateBefore, depsState)
  LOG.debug("  %s:\n  old %s\n  new %s", logTag, old, fresh)
  if old == fresh:
    LOG.log(VERBOSE, "- " + logTag)
    return

  cmdName: str = "no-op"
  startNanos = time.time_ns()
  if target.cmd is not None:
    cmdName = target.cmd.__name__
    target.cmd(target.item, *map(lambda d: d.item, target.dependencies))
  took = _formatNanoDelta(startNanos, time.time_ns())
  if len(triggeringDeps) == 0:
    LOG.log(VERBOSE, "+ %s(%s): outdated, %s", cmdName, logTag, took)
  else:
    LOG.log(VERBOSE, "+ %s(%s): <- %s, %s",
                cmdName, logTag, ", ".join(triggeringDeps), took)


  target.recreated = True
  targetStateAfter = target.generateState(target.item)
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
  """Creates a target to create the dependency graph.

  If the given ``buildscript`` is a ``Path`` a ``Target`` is created for it.

  The extension of the ``graphFile`` will be used as the image type requested
  from the ``dot`` program. If the ``buildscript`` is already a ``Target`` it is
  used as the dependency.

  :param graphFile: the dependency graph after converting the
    output of `toGraphviz`.
  :param name: of the ``Target`` for the graph file
  :param buildscript: to depend on such that the graph is re-created if the
    script changes
  :return: the ``Target`` for the dependency graph

  """
  dep = buildscript if isinstance(buildscript, Target) else Target(buildscript)
  return Target(graphFile, dep, name=name, state="file", cmd=graphToDot)

def graphToDot(targetPath: Path, _unused: Path) -> None:
  """Convenience function to create a dependency graph of all targets.

  The function calls `toGraphviz()` and pipes the output through
  the ``dot`` program, writing the image file to the ``targetPath``.

  :param targetPath: to write the graph to. Its suffix is used as the image
    type requested from ``dot``, like ``svg`` or ``pdf``.
  :param _unused: not used, facilitates used as a ``cmd`` parameter of ``Target``
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

  def __repr__(self) -> str:
    return "_StateStore[%s]" % self.hashes

  def setHashes(self,
                target: Target,
                targetHash: str,
                depsHash: str) -> None:
    self.hashes[target.name] = (targetHash, depsHash)

  def get(self, target: Target) -> tuple[str, str]:
    return self.hashes.get(target.name, ("", ""))

  def getOwnHash(self, target: Target) -> str:
    return self.hashes[target.name][0]

  def getDepsHash(self, target: Target) -> str:
    return self.hashes[target.name][1]

  def save(self) -> None:
    LOG.debug("  writing %s" % self.stateFile)
    os.makedirs(os.path.dirname(self.stateFile), exist_ok=True)

    with open(self.stateFile, "w", encoding="UTF-8") as statefile:
      json.dump(self.hashes, statefile, indent=2)
