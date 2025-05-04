"""
Your primary entry points are the `Target` constructor to create your
targets and `updateTargets()` to bring some targets up to date.
"""
import sys
import os
import time
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

STARTTIME = time.time_ns()

logging.basicConfig(format='%(message)s (%(levelname)s)')
LOG = logging.getLogger()
LOG.setLevel("INFO")

## FIXME: get rid of global variables
## FIXME: remove mutable state from Target, keep it in a separate object,
##        but check if it worth it as inspection during the build is more
#         difficult

TARGETS = dict()
ALIAS: dict[str, str] = dict()

## FIXME: only here for tests, should be properly injectable
STATEFILE = os.path.join("build", "states")

class BuildException(Exception): #{
  """Raised for failures detected by pythonbuilder"""
  def __init__(self, message):
    self.message = message
#}


@dataclass(init=False, eq=False)
class Target: #{
  """
  Represents a target with its dependencies, how to compute its state
  (hashed content, fingerprint), how to (re-)create it and an optional alias.
  """

  def __init__(self, target: str, *dependencies, **options): #{
    """
    Creates a new Target.
    Args:
      target (str): a string representing the target, like a file or dir name
      dependencies (str|Target): the dependencies of this target
      options (str): keyword arguments as described below
 
    Returns:
      Target: the target

    The options allow the following keyword arguments

    - state (str|Callable): asdfasdf
    - alias (str): adfasdf
    - cmd (Callable): asdfasf
    """
    if target in TARGETS:
      raise BuildException("'%s' defined already" % target)

    #print("%s, <<%s>>, <<%s>>" % (target, dependencies, options))
    if len(dependencies) > 0 and not "cmd" in options:
      raise BuildException(("'%s' has dependencies but no command," +
                            " use cmd= to provide one") % target)
    stateGenerator: Callable[[Target],str]
    match options.get("state", None):
      case "dir":
        stateGenerator = stateDirContent
      case "file":
        stateGenerator = stateFileContent
      case "new":
        stateGenerator = stateNew
      case "fixed":
        stateGenerator = stateFixed
      case None:
        if os.path.isdir(target):
          stateGenerator = stateDirContent
        elif os.path.isfile(target):
          stateGenerator = stateFileContent
        else:
          raise BuildException(("'%s' does not exist, cannot determine state" +
                                " generator, provide one with state=") % target)
      case _:
        sg = options.get("state")
        if self._isStateGenerator(sg):
          stateGenerator = sg
        else:
          raise BuildException("'%s' is not a function of Target" % sg)

    self.name: str = target
    self.alias: str | None = options.get("alias", None)
    # FIXME: remove single quotes in python 3.14
    self.generateState: Callable[['Target'], str] = stateGenerator
    self.cmd: Callable[['Target'], None] = options.get("cmd", None)
    self.dependencies = []
    for dep in dependencies:
      d = findTarget(dep)
      if d is not None:
        self.dependencies.append(d)
      else:
        raise BuildException(("dependency '%s' is neither Target nor can be" +
                               " mapped to a target") % dep)
    self.started: bool = False
    self.updated: bool = False
    self.recreated: bool = False  

    if not self.alias is None:
      ALIAS[self.alias] = target
    TARGETS[target] = self

  def _isStateGenerator(self, g: Any) -> TypeGuard[Callable[['Target'], str]]:
    if not callable(g):
      return False
    ## FIXME: add better test to fail early
    return True
#}

def findTarget(target: str | Target) -> Target | None: #{
  """
  Either returns the given target immediately or looks up the given `str` which
  may be either a target name or target alias.

  Args:
    target (str|Target): to look up

  Returns:
    Target|None: either the target or `None`
  """
  if isinstance(target, Target):
    return target
  mapped: str = ALIAS.get(target, target)
  return TARGETS.get(mapped, None)
#}

def stateNew(_t: Any = None) -> str:
  return str(time.time_ns());

def stateFixed(_t: Target) -> str:
  return "0"

##
# Assumes the target's name is a function producing some text and this
# text is hashed as the state
def stateTextGen(target: Target) -> str:
  digest = hashlib.sha256()
  digest.update(target.name.encode())
  return digest.hexdigest()
               
def stateDirContent(target: Target) -> str:
  it = itertools.chain.from_iterable(
    map(lambda triple: map(lambda f: os.path.join(triple[0], f), triple[2]),
        os.walk(target.name))
  )
  return stateFileIteratorContent(it);

def stateFileContent(target: Target) -> str:
  return stateFileIteratorContent([target.name])

##
# Computes a state over all dependencies, ignoring the target itself.  Used for
# targets which merely combine a bunch of other targets and have no state on
# their own. They should trigger their dependents iff the dependencies change.
#
# FIXME: We need access to the StateStore here. Rather than hackily inject the
# the state store into every Target, try to move this function into a class
# which has the state store as a field.
# Problem: when a Target is created we are far from having
# a state store anywhere near.
def _stateDepsOnly( target: Target) -> str:
  pass

def stateFileIteratorContent(it: Iterable[str]) -> str:
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
  LOG.debug("  resetting traversal state")
  for target in TARGETS.values():
    target.started = False
    target.updated = False
    target.recreated = False

UNITS = [("ns", 10000, 1000),
         ("µs", 10000, 1000),
         ("ms", 10000, 1000),
         ("s", 120, 60),
         ]
def _formatNanoDelta(start: int, now: int) -> str:
  delta = now - start
  for i in range(0, len(UNITS)):
    if delta < UNITS[i][1]:
      return "%s%s" %(delta, UNITS[i][0])
    delta = delta // UNITS[i][2]
  return "%s%s" %(delta, "min")

def _flatten(result: list[str], l: Iterable) -> None:
  if isinstance(l, str):
    result.append(l)
    return
  if not isinstance(l, Iterable):
    raise TypeError("parameter must be Iterable but is %s" % l)
  for elem in l:
    _flatten(result, elem)

def pbexec(*args):
  """
  Shallow wrapper around `subprocess.run` which

  - logs the command line at `INFO` level
  - runs `subprocess.run()` with the flattened input list
  - calls check_returncode() on the result

  :param `args` a possibly multi-nested list of `str`
  """
  cmd = []
  _flatten(cmd, args)
  LOG.info("* %s", " ".join(cmd))
  subprocess.run(cmd).check_returncode()

def updateTargets(*targets: str | Target):
  """
  Updates all targets in turn without resetting the traversal state in between,
  so if target T1 depends on target T0, in th call `updateTargets(T1, T0)`, the
  T0 is redundant, because it will be updated already when doing T1.

  :param targets: a `str` provided is looked up with `findTarget`
  """
  buildStart = time.time_ns()
  LOG.info("  startup took %s", _formatNanoDelta(STARTTIME, buildStart))
  states = StateStore(STATEFILE)
  for t in targets:
    target = findTarget(t)
    if target is None:
      raise BuildException("target '%s' not defined" % t)
    _updateTarget(states, target, [])
  states.save()
  buildEnd = time.time_ns()
  LOG.info("  build took %s, total %s",
           _formatNanoDelta(buildStart, buildEnd),
           _formatNanoDelta(STARTTIME, buildEnd))

def _updateTarget(states: 'StateStore',
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

  cmdName = target.cmd.__name__ if target.cmd is not None else ""
  if len(triggeringDeps) == 0:
    LOG.info("+ %s(%s): outdated",cmdName, target.name)
  else:
    LOG.info("+ %s(%s): <- %s", cmdName, target.name, ", ".join(triggeringDeps))
  
  if target.cmd is not None:
    target.cmd(target)

  target.recreated = True
  targetStateAfter = target.generateState(target)
  states.setHashes(target, targetStateAfter, depsState)

def escdq(s: str) -> str:
  return s.replace('"', '\\"')
  
def _targetToGraphviz(target: Target) -> str:
  result = ""
  for dep in target.dependencies:
    result += f'  "{escdq(dep.name)}" -> "{escdq(target.name)}"'

  if target.alias is not None:
    result += (f'"{escdq(target.name)}"[label=<{escdq(target.alias)}' +
               f'<BR/><FONT POINT-SIZE="10">{escdq(target.name)}</FONT>>]')
  return result

def toGraphviz() -> str:
  result = "digraph {"

  for target in TARGETS.values():
    result += _targetToGraphviz(target)
    
  result += "}"
  return result

########################################################################

class StateStore:
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
    return "StateStore[%s]" % self.hashes

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
      json.dump(self.hashes, statefile)

