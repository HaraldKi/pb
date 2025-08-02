import hashlib
import shutil
import sys
import unittest
from pathlib import Path
from typing import Any

## The tests must be started from the project directory
sys.path += [str(Path.cwd() / "src")]

from pythonbuilder import (
  _TARGETS,
  LOG,
  STATEFILE,
  BuildException,
  Target,
  findTarget,
  rawUpdateTargets,
  resetTraversalState,
  stateDirContent,
  stateFileContent,
  stateFileIteratorContent,
  stateFixed,
  stateNew,
  updateTargets,
)

_TMPDIR = Path("build", "testtmp")

# mypy: allow-untyped-defs


def noop(t: Any) -> None:
  return None


class TestTargetCreation(unittest.TestCase):
  def setUp(self):
    _TARGETS.clear()

  def test_basic(self):
    t = Target(Path("pb"))
    self.assertEqual(stateFileContent, t.generateState)
    self.assertEqual(t, findTarget("pb"))

  def test_explictName(self):
    ## we use an arbitrary existing file (FIXME: create test file)
    t = Target(Path("pb"), name="base")
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
    t = Target("b", state="file", cmd=noop)
    self.assertEqual(noop, t.cmd)

  def test_deps(self):
    d0 = Target("d0", state="file")
    d1 = Target("d1", state="file")
    t = Target("b", d0, d1, state="file", cmd=lambda: None)
    self.assertEqual(d0, t.dependencies[0])
    self.assertEqual(d1, t.dependencies[1])

  def test_failWrongState(self):
    self.assertRaisesRegex(
      BuildException,
      "'foob' is neither a file nor a directory, cannot",
      lambda: Target("foob"),
    )

  def testFailDoublyDeclared(self):
    Target(Path("x", "z"), state="file")
    with self.assertRaisesRegex(BuildException, "defined already"):
      Target(Path("x") / "z", state="file")

  def testFailWrongStateFun(self):
    with self.assertRaisesRegex(BuildException, "'1' is not"):
      Target("yada1", state=1)

    with self.assertRaisesRegex(BuildException, "dir>' is not"):
      Target("yada1", state=dir)

    with self.assertRaisesRegex(BuildException, "str'>' is not"):
      Target("yada2", state=str)

    with self.assertRaisesRegex(BuildException, "<lambda>.* is not"):
      Target("yada3", state=lambda: "a")

    with self.assertRaisesRegex(BuildException, "<lambda>.* is not"):
      Target("yada4", state=lambda a, b: "a")


def writeToFile(text, fname):
  with open(fname, "wb") as outfile:
    outfile.write(text.encode())


class TestStateComputation(unittest.TestCase):
  def test_iterator(self):
    file = _TMPDIR / "thefile"
    writeToFile("hallo", file)
    hex = stateFileIteratorContent(lambda: [file])
    digest = hashlib.sha256()
    digest.update(str(file).encode())
    digest.update("hallo".encode())
    self.assertEqual(digest.hexdigest(), hex)

  def test_dirContent(self):
    mydir = _TMPDIR / "dircontenttest"
    if mydir.is_dir():
      shutil.rmtree(mydir)

    dir = mydir / "dir0"
    dir.mkdir(parents=True, exist_ok=True)
    t = Target(mydir)

    file1 = mydir / "file1"
    file2 = mydir / "file2"
    file3 = dir / "file3"
    writeToFile("file1", file1)
    writeToFile("file2", file2)
    writeToFile("file3", file3)
    hex = stateDirContent(t.item)

    digest = hashlib.sha256()
    for f in [file1, file2, file3]:
      digest.update(str(f).encode())
      digest.update(str(f.name).encode())
    self.assertEqual(digest.hexdigest(), hex)


class TestUpdateTargets(unittest.TestCase):
  values: dict[str, str] = dict()

  def simpleState(self, value: str) -> str:
    return self.values.get(value, stateNew(value))

  def setSimpleValue(self, key: str, value: Any) -> None:
    self.values[key] = str(value)

  def setUp(self):
    self.values.clear()
    if STATEFILE.is_file():
      STATEFILE.unlink()

  def test_singleTarget(self):
    self.values["blabla"] = "value of blabla"
    t = Target("blabla", state=self.simpleState)
    updateTargets("blabla")
    self.assertTrue(t.started)
    self.assertTrue(t.updated)
    self.assertTrue(t.recreated)

    resetTraversalState()
    updateTargets("blabla")
    self.assertTrue(t.started)
    self.assertTrue(t.updated)
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
    self.values[source.item] = "value of source"
    self.values[top.item] = "value of top"
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
    self.values[source.item] = "value of source changed"

    updateTargets(top)
    self.assertTrue(source.updated)
    self.assertTrue(source.recreated)
    self.assertTrue(fixed.updated)
    self.assertTrue(fixed.recreated)
    self.assertTrue(top.updated)
    self.assertFalse(top.recreated)

  def failWithZDE(self, t: str, u: str):
    print(len(t) / 0)

  def test_buildFailDoesNotUpdateStatefile(self) -> None:
    first: Target[str] = Target("first", state=self.simpleState)
    second: Target[str] = Target("second", first, state="fixed", cmd=self.failWithZDE)
    self.values[first.item] = "value of first"
    self.values[second.item] = "value of second"
    with self.assertRaises(ZeroDivisionError):
      rawUpdateTargets(second)
    self.assertTrue(first.updated)
    self.assertTrue(first.recreated)
    self.assertTrue(second.updated)
    self.assertFalse(second.recreated)

    ## Now run again and see that first is again recreated
    resetTraversalState()
    with self.assertRaises(ZeroDivisionError):
      rawUpdateTargets(second)
    self.assertTrue(first.recreated)

  def test_inMemTarget(self):
    t0 = Target(117, state="value")
    other = Target("other", t0, state="value", cmd=self.setSimpleValue)

    rawUpdateTargets(other)
    self.assertTrue(other.recreated)
    self.assertEqual("117", self.values["other"])

    resetTraversalState()
    rawUpdateTargets(other)
    self.assertFalse(other.recreated)

    resetTraversalState()
    t0.item = 116
    rawUpdateTargets(other)
    self.assertTrue(other.recreated)
    self.assertEqual("116", self.values["other"])


if __name__ == "__main__":
  LOG.setLevel("ERROR")
  # unittest.main(defaultTest='TestUpdateTargets.test_buildFailDoesNotUpdateStatefile')
  unittest.main(verbosity=2)
