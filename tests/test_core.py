import hashlib
import shutil
from pathlib import Path
from typing import Any

import support

from pythonbuilder import (
  BuildException,
  Target,
  findTarget,
  getTargets,
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


def noop(t: Any) -> None:
  return None


class TestTargetCreation(support.CommonFixture):
  def test_basic(self) -> None:
    t = Target(Path("pb"))
    self.assertEqual(stateFileContent, t.generateState)
    self.assertEqual(t, findTarget("pb"))

  def test_explictName(self) -> None:
    ## we use an arbitrary existing file (FIXME: create test file)
    t = Target(Path("pb"), name="base")
    self.assertEqual(t, findTarget("base"))

  def test_state(self) -> None:
    t = Target(Path("b"), state="dir")
    self.assertEqual(stateDirContent, t.generateState)

    t = Target(Path("c"), state="file")
    self.assertEqual(stateFileContent, t.generateState)

    t3 = Target("d", state="fixed")
    self.assertEqual(stateFixed, t3.generateState)

    t4 = Target("e", state="new")
    self.assertEqual(stateNew, t4.generateState)

  def test_statePathFail(self) -> None:
    t = Target(Path("pb"), state="dir")
    with self.assertRaisesRegex(BuildException, "'pb'.*file.*directory"):
      rawUpdateTargets(t.name)

    t = Target(Path("pythonbuilder"), state="file")
    with self.assertRaisesRegex(BuildException, "'pythonbuilder'.*directory.*file"):
      rawUpdateTargets(t.name)

  def test_cmd(self) -> None:
    t = Target("b", state="value", cmd=noop)
    self.assertEqual(noop, t.cmd)

  def test_deps(self) -> None:
    d0 = Target("d0", state="value")
    d1 = Target("d1", state="value")
    t = Target("b", d0, d1, state="value", cmd=None)
    self.assertEqual(d0, t.dependencies[0])
    self.assertEqual(d1, t.dependencies[1])

  def test_failWrongState(self) -> None:
    self.assertRaisesRegex(
      BuildException,
      "'foob' is neither a file nor a directory, cannot",
      lambda: Target("foob"),
    )

  def testFailDoublyDeclared(self) -> None:
    Target(Path("x", "z"), state="file")
    with self.assertRaisesRegex(BuildException, "defined already"):
      Target(Path("x") / "z", state="file")

  def testFailWrongStateFun(self) -> None:
    with self.assertRaisesRegex(BuildException, "'file' must.*Path"):
      Target("yada2", state="file")
    with self.assertRaisesRegex(BuildException, "'dir' must.*Path"):
      Target("yada2", state="dir")
    with self.assertRaisesRegex(BuildException, "'stuff'.*function shortcut"):
      Target("yada2", state="stuff")


def writeToFile(text: str, fname: Path) -> None:
  with open(fname, "wb") as outfile:
    outfile.write(text.encode())


class TestStateComputation(support.CommonFixture):
  def test_iterator(self) -> None:
    file = _TMPDIR / "thefile"
    writeToFile("hallo", file)
    hex = stateFileIteratorContent([file])
    digest = hashlib.sha256()
    digest.update(str(file).encode())
    digest.update("hallo".encode())
    self.assertEqual(digest.hexdigest(), hex)

  def test_dirContent(self) -> None:
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



class TestUpdateTargets(support.CommonFixture):
  values: dict[str, str] = dict()

  def simpleState(self, value: str) -> str:
    return self.values.get(value, stateNew(value))

  def setSimpleValue(self, key: str, value: Any) -> None:
    self.values[key] = str(value)

  def setUp(self) -> None:
    super().setUp()
    self.values.clear()

  def test_singleTarget(self) -> None:
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
  def test_fixedStateStopsUpdate(self) -> None:
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

  def failWithZDE(self, t: str, u: str) -> None:
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

  def test_inMemTarget(self) -> None:
    t0 = Target(117, name="t0", state="value")
    other = Target("other", t0, state="value", cmd=self.setSimpleValue)

    rawUpdateTargets(other)
    self.assertTrue(other.recreated)
    self.assertEqual("117", self.values["other"])

    getTargets().clear()
    t0 = Target(117, name="t0", state="value")
    other = Target("other", t0, state="value", cmd=self.setSimpleValue)
    rawUpdateTargets(other)
    self.assertFalse(other.recreated)

    getTargets().clear()
    resetTraversalState()
    t0 = Target(116, name="t0", state="value")
    other = Target("other", t0, state="value", cmd=self.setSimpleValue)

    rawUpdateTargets(other)
    self.assertTrue(other.recreated)
    self.assertEqual("116", self.values["other"])

  def test_updatingAnUpdatedIsNoop(self) -> None:
    Target("somevalue", name="t0", state="value")
    # This failed in some version, because rawUpdateTargets was called twice for t0,
    # because preventing a call for an already updated target was only done in the
    # loop over the dependencies in _updateTarget, not in updateTargets()
    self.assertTrue(updateTargets("t0", "t0"))
