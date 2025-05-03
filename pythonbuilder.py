import sys
import os
import time
import hashlib
from collections.abc import Iterable, Collection, Callable
import itertools
from dataclasses import dataclass
from configparser import ConfigParser
import logging
import inspect
import subprocess

logging.basicConfig(format='%(message)s (%(levelname)s)')
LOG = logging.getLogger()
LOG.setLevel("INFO")

## FIXME: get rid of global variables
## FIXME: remove mutable state from Target, keep it in a separate object,
##        but check if it worth it as inspection during the build is more
#         difficult

TARGETS = dict()
ALIAS = dict()

## FIXME: only here for tests, should be properly injectable
STATEFILE = os.path.join("build", "states")

class BuildException(Exception): #{
  """Raised for failures detected by pythonbuilder"""
  def __init__(self, message):
    self.message = message
#}


##
# @param options may contain
#  - state
#  - cmd: must be present if dependencies are provided
#  - alias
# @param dependencies must be a list contaning only Target objects
# @return the {@link Target} created
@dataclass(init=False, eq=False)
class Target: #{
  def __init__(self, target, *dependencies, **options): #{
    if target in TARGETS:
      raise BuildException("'%s' defined already" % target)

    #print("%s, <<%s>>, <<%s>>" % (target, dependencies, options))
    if len(dependencies) > 0 and not "cmd" in options:
      raise BuildException(("'%s' has dependencies but no command," +
                            " use cmd= to provide one") % target)
    stateGenerator = None
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
        stateGenerator = options.get("state")
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
#}

def findTarget(target: str | Target) -> Target | None: #{
  if isinstance(target, Target):
    return target
  target = ALIAS.get(target, target)
  return TARGETS.get(target, None)
#}

def stateNew(_t) -> str:
  return str(time.time_ns());

def stateFixed(_target) -> str:
  return "0"

##
# Assumes the target's name is a function producing some text and this
# text is hashed as the state
def stateTextGen(target: Target) -> str:
  digest = hashlib.sha256()
  digest.upate(target.name().encode())
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
      digest.update(stateNew("").encode())
  return digest.hexdigest()

def resetTraversalState():
  LOG.debug("  resetting traversal state")
  for target in TARGETS.values():
    target.started = False
    target.updated = False
    target.recreated = False

def updateTargets(*targets: str | Target):
  states = StateStore(STATEFILE)
  for t in targets:
    target = findTarget(t)
    if target is None:
      raise BuildException("target '%s' not defined" % t)
    _updateTarget(states, target, [])
  states.save()

def flatten(result: list[str], l: Iterable) -> None:
  if isinstance(l, str):
    result.append(l)
    return
  if not isinstance(l, Iterable):
    raise TypeError("parameter must be Iterable but is %s" % l)
  for elem in l:
    flatten(result, elem)

def pbexec(*args):
  """Shallow wrapper around subprocess.run which
    - logs the command line to info
    - runs subprocess.run() with the flattened input list
    - calls check_returncode() on the reslt
  """
  cmd = []
  flatten(cmd, args)
  LOG.info("* %s", " ".join(cmd))
  subprocess.run(cmd).check_returncode()

def _updateTarget(states: 'StateStore',
                  target: Target,
                  onbehalf: Collection[Target]):
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

  if len(triggeringDeps) == 0:
    LOG.info("+ %s (outdated)" % target.name)
  else:
    LOG.info("+ %s (%s)" % (target.name, ", ".join(triggeringDeps)))
  
  if target.cmd is not None:
    LOG.info("* %s", target.cmd.__name__)
    target.cmd(target)

  target.recreated = True
  targetStateAfter = target.generateState(target)
  states.setHashes(target, targetStateAfter, depsState)

########################################################################

class StateStore:
  def __init__(self, stateFile: str):
    self.stateFile = stateFile
    self.hashes: dict[str,any] = dict()
    if not os.path.isfile(self.stateFile):
      LOG.debug("  no file '%s', starting with empty states"
                % self.stateFile)
      return

    LOG.info("  reading %s" % self.stateFile)

    config = ConfigParser()
    with open(self.stateFile, "r", encoding="UTF-8") as statefile:
      config.read_file(statefile)

      for (key, ownHash) in config.items("own"):
        depsHash = config.get("deps", key)
        self.hashes[key] = (ownHash, depsHash)

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
    LOG.info("  writing %s" % self.stateFile)
    os.makedirs(os.path.dirname(self.stateFile), exist_ok=True)
    config = ConfigParser()

    config.add_section("own")
    config.add_section("deps")
    for name in self.hashes:
      config.set("own", name, self.hashes[name][0])
      config.set("deps", name, self.hashes[name][1])
      
    with open(self.stateFile, "w", encoding="UTF-8") as statefile:
      config.write(statefile)
