import unittest
import sys, os
import hashlib
import shutil

## The tests must be started from the project directory
sys.path += [os.path.join(os.getcwd(), "src")]

from pythonbuilder import (
  BuildException,
  STATEFILE,
  Target,
  findTarget,
  stateDirContent,
  stateFileContent,
  stateFileIteratorContent,
  stateFixed,
  stateNew,
  updateTargets,
  resetTraversalState,
  LOG,
  _TARGETS,
  _ALIAS,
)
TMPDIR=os.path.join("build", "testtmp")

class TestTargetCreation(unittest.TestCase):
  def setUp(self):
    _TARGETS.clear()
    _ALIAS.clear()

  def test_basic(self):
    t = Target("pb")
    self.assertEqual(stateFileContent, t.generateState)
    self.assertEqual(t, findTarget("pb"))

  def test_alias(self):
    ## we use an arbitrary existing file (FIXME: create test file)
    t = Target("pb", alias="base")
    self.assertEqual(t, findTarget("base"))

  def test_state(self):
    t = Target("b", state="dir")
    self.assertEqual(stateDirContent, t.generateState)

    t = Target("c", state="file")
    self.assertEqual(stateFileContent, t.generateState)

    t = Target("d", state="fixed")
    self.assertEqual(stateFixed, t.generateState)

    t = Target("e", state="new")
    self.assertEqual(stateNew, t.generateState)

  def test_cmd(self):
    cmd = lambda t: None
    t = Target("b", state="file", cmd=cmd)
    self.assertEqual(cmd, t.cmd)

  def test_deps(self):
    d0 = Target("d0", state="file")
    d1 = Target("d1", state="file")
    t = Target("b", d0, "d1", state="file", cmd=lambda: None)
    self.assertEqual(d0, t.dependencies[0])
    self.assertEqual(d1, t.dependencies[1])

  def test_failWrongState(self):
    self.assertRaisesRegex(BuildException,
                           "'foob' does not exist, cannot ",
                           lambda: Target("foob"))

  def test_buildFailsForUnknownDependency(self):
    with self.assertRaisesRegex(BuildException, "'no-dep' is neither"):
      Target("t", "no-dep", state="file")


def writeToFile(text, fname):
  with open(fname, "wb") as outfile:
    outfile.write(text.encode())

class TestStateComputation(unittest.TestCase):
  def test_iterator(self):
    file = os.path.join(TMPDIR, "thefile")
    writeToFile("hallo", file)
    hex = stateFileIteratorContent([file])
    digest = hashlib.sha256()
    digest.update(file.encode())
    digest.update("hallo".encode())
    self.assertEqual(digest.hexdigest(), hex)

  def test_dirContent(self):
    mydir = os.path.join(TMPDIR, "dircontenttest")
    if os.path.isdir(mydir):
      shutil.rmtree(mydir)

    dir = os.path.join(mydir, "dir0");
    os.makedirs(dir)
    t = Target(mydir)

    file1 = os.path.join(mydir, "file1")
    file2 = os.path.join(mydir, "file2")
    file3 = os.path.join(dir, "file3")
    writeToFile("file1", file1);
    writeToFile("file2", file2);
    writeToFile("file3", file3);
    hex = stateDirContent(t)

    digest = hashlib.sha256()
    for f in [file1, file2, file3]:
      digest.update(f.encode())
      digest.update(os.path.basename(f).encode())
    self.assertEqual(digest.hexdigest(), hex)


class TestUpdateTargets(unittest.TestCase):
  values: dict[str, str] = dict()
  def simpleState(self, target: Target) -> str:
    return self.values.get(target.name, stateNew(target))

  def setUp(self):
    self.values.clear()
    if os.path.isfile(STATEFILE):
      os.remove(STATEFILE)

  def test_singleTarget(self):
    self.values["blabla"] = "value of blabla"
    t = Target("blabla", state=self.simpleState)
    updateTargets("blabla")
    self.assertTrue(t.started);
    self.assertTrue(t.updated);
    self.assertTrue(t.recreated);

    resetTraversalState()
    updateTargets("blabla")
    self.assertTrue(t.started);
    self.assertTrue(t.updated);
    self.assertFalse(t.recreated)

  ##
  # A Target with a fixed state or, more generally, a Target the
  # state of which does not change on recomputation does not
  # trigger its dependents, even if recreated for the simple reason:
  # If, after recreation, the state is as before, there is no point
  # to trigger the dependents.
  def test_fixedStateStopsUpdate(self):
    source = Target("source", state=self.simpleState)
    fixed = Target("fixed", source, state="fixed")
    top = Target("top", fixed, state=self.simpleState)
    self.values[source.name] = "value of source"
    self.values[top.name] = "value of top"
    updateTargets(top)
    self.assertTrue(source.updated)
    self.assertTrue(source.recreated)
    self.assertTrue(fixed.updated)
    self.assertTrue(fixed.recreated)
    self.assertTrue(top.updated)
    self.assertTrue(top.recreated)

    resetTraversalState()
    updateTargets(top)
    self.assertTrue(source.updated)
    self.assertFalse(source.recreated)
    self.assertTrue(fixed.updated)
    self.assertFalse(fixed.recreated)
    self.assertTrue(top.updated)
    self.assertFalse(top.recreated)

    resetTraversalState()
    self.values[source.name] = "value of source changed"

    updateTargets(top)
    self.assertTrue(source.updated)
    self.assertTrue(source.recreated)
    self.assertTrue(fixed.updated)
    self.assertTrue(fixed.recreated)
    self.assertTrue(top.updated)
    self.assertFalse(top.recreated)

  def test_buildFailDoesNotUpdateStatefile(self):
    cmd = lambda t: 1/0 # just fail somehow
    first = Target("first", state=self.simpleState)
    second = Target("second", first, state="fixed", cmd=cmd)
    self.values[first.name] = "value of first"
    self.values[second.name] = "value of second"
    with self.assertRaises(ZeroDivisionError):
      updateTargets(second)
    self.assertTrue(first.updated)
    self.assertTrue(first.recreated)
    self.assertTrue(second.updated)
    self.assertFalse(second.recreated)

    ## Now run again and see that first is again recreated
    resetTraversalState()
    with self.assertRaises(ZeroDivisionError):
      updateTargets(second)
    self.assertTrue(first.recreated)


if __name__ == '__main__':
  LOG.setLevel("ERROR")
  #unittest.main(defaultTest='TestUpdateTargets.test_buildFAilDoesNotUpdateStatefile')
  unittest.main(verbosity=2)
