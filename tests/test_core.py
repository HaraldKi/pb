import hashlib
import shutil
from pathlib import Path
from typing import Any, Callable, cast

import support

from pythonbuilder.pbutil import Value
from pythonbuilder.pythonbuilder import (
  BuildException,
  StateProvider,
  StateProviderImpl,
  Target,
  currentBuild,
  inputTask,
  newBuild,
  runTasks,
  stateDirContent,
  stateFileContent,
  stateFileIteratorContent,
  stateFixed,
  stateNew,
  target,
  task,
)

_TMPDIR = Path("build", "testtmp")


def noop(t: Any) -> None:
  return None


class DummySelfState(StateProvider):
  def __init__(self, v: str):
    self.v = v

  def provideState(self) -> str:
    return "X" + self.v


class TestTaskCreation(support.CommonFixture):
  def getGenerator(self, t: Target[Any]) -> Callable[[Any], str]:
    return cast(StateProviderImpl, t._stateGenerator).generator

  def test_basic(self) -> None:
    t = inputTask(Path("pb"))()
    self.assertEqual(stateFileContent, self.getGenerator(t))
    self.assertEqual(t, currentBuild().getTarget("pb"))

  def test_explictName(self) -> None:
    ## we use an arbitrary existing file (FIXME: create test file)
    t = inputTask(Path("pb"), name="base")()
    self.assertEqual(t, currentBuild().getTarget("base"))

  def test_state(self) -> None:
    t = inputTask(Path("b"), state="dir")()
    self.assertEqual(stateDirContent, self.getGenerator(t))

    t = inputTask(Path("c"), state="file")()
    self.assertEqual(stateFileContent, self.getGenerator(t))

    t3 = inputTask("d", state="fixed")()
    self.assertEqual(stateFixed, self.getGenerator(t3))

    t4 = inputTask("e", state="new")()
    self.assertEqual(stateNew, self.getGenerator(t4))

    v = DummySelfState("ulu")
    t5 = inputTask(v)()
    self.assertEqual(v, t5._stateGenerator)
    self.assertEqual("Xulu", t5._stateGenerator.provideState())

    t6 = inputTask("text", state=lambda s: f"({s})")()
    self.assertEqual("(text)", t6._stateGenerator.provideState())

  def test_deps(self) -> None:
    d0 = inputTask("d0", state="value")
    d1 = inputTask("d1", state="value")

    @task
    def top() -> Target[str]:
      return target("b", d0(), d1(), state="value")

    t = top()
    self.assertEqual(d0(), t.dependencies[0])
    self.assertEqual(d1(), t.dependencies[1])

  def test_failWrongState(self) -> None:
    self.assertRaisesRegex(
      BuildException,
      "'foob' is neither a file nor a directory, cannot",
      lambda: inputTask("foob")(),
    )

  def testFailDoublyDeclared(self) -> None:
    @task
    def t0() -> Target[str]:
      return target("t0", state="value")  # pragma: no cover

    with self.assertRaisesRegex(BuildException, "already defined"):
      inputTask("t0", state="value")

  def testFailWrongStateFun(self) -> None:
    with self.assertRaisesRegex(BuildException, "'file' must.*Path"):
      inputTask("yada1", state="file")()
    with self.assertRaisesRegex(BuildException, "'dir' must.*Path"):
      inputTask("yada2", state="dir")()
    with self.assertRaisesRegex(BuildException, "'stuff'.*function shortcut"):
      inputTask("yada3", state="stuff")()

  def testStrOfTarget(self) -> None:
    t0 = inputTask("zero", state="value")()

    @task
    def t1() -> Target[Any]:
      return target(DummySelfState("xx"), t0)

    self.assertEqual("Target(zero, [], name=zero, state=stateValue)", str(t0))
    self.assertEqual(
      "Target(t1, [zero], name=t1, state=(itemstate))", str(t1())
    )


class TestStateComputation(support.CommonFixture):
  def test_iterator(self) -> None:
    file = _TMPDIR / "thefile"
    file.write_text("hallo")
    hex = stateFileIteratorContent([file])
    digest = hashlib.sha256()
    digest.update(str(file).encode())
    digest.update("hallo".encode())
    self.assertEqual(digest.hexdigest(), hex)

  def test_dirContent(self) -> None:
    mydir = _TMPDIR / "dircontenttest"
    if mydir.is_dir():
      shutil.rmtree(mydir)  # pragma: no cover

    dir = mydir / "dir0"
    dir.mkdir(parents=True, exist_ok=True)
    t = inputTask(mydir)()

    file1 = mydir / "file1"
    file2 = mydir / "file2"
    file3 = dir / "file3"
    file1.write_text("file1")
    file2.write_text("file2")
    file3.write_text("file3")
    hex = stateDirContent(t.item)

    digest = hashlib.sha256()
    for f in [file1, file2, file3]:
      digest.update(str(f).encode())
      digest.update(str(f.name).encode())
    self.assertEqual(digest.hexdigest(), hex)


class TestUpdateTargets(support.CommonFixture):
  def setUp(self) -> None:
    super().setUp()

  def test_singleTarget(self) -> None:
    v = Value("blabla", "value of blabla")
    blabla = inputTask(v)
    t = blabla()
    self.assertTrue(t.outdated)

    newBuild()
    t = blabla()
    self.assertFalse(t.outdated)

    newBuild()
    v.value = "othervalue"
    t = blabla()
    self.assertTrue(t.outdated)

  def test_statePathFail(self) -> None:
    t = inputTask(Path("pb"), state="dir")
    with self.assertRaisesRegex(BuildException, "'pb'.*file.*directory"):
      t()

    t = inputTask(Path("pythonbuilder"), state="file")
    with self.assertRaisesRegex(
      BuildException, "'pythonbuilder'.*directory.*file"
    ):
      t()

  def testTargetCalledNotFromTask(self) -> None:
    # first from the top level
    def broken() -> Target[str]:
      return target("broken", state="value")

    with self.assertRaisesRegex(BuildException, "no current task.*@task"):
      broken()

    # next from another target as dependency
    newBuild()

    @task
    def caller() -> Target[str]:
      return target("caller", broken(), state="value")

    with self.assertRaisesRegex(BuildException, "'caller'.*already.*@task"):
      caller()

  ##
  # A Target with a fixed state or, more generally, a Target the
  # state of which does not change on recomputation does not
  # trigger its dependents, even if recreated.
  def test_fixedStateStopsUpdate(self) -> None:
    vSource = Value("source", "vsource")
    source = inputTask(vSource)
    vTop = Value("top", "vtop")

    @task
    def fixed() -> Target[Value[str]]:
      return target(Value("fixed", "vfixed"), source())

    @task
    def top() -> Target[Value[str]]:
      return target(vTop, fixed())

    topTarget = top()
    self.assertTrue(source().outdated)
    self.assertTrue(fixed().outdated)
    self.assertTrue(topTarget.outdated)

    newBuild()
    topTarget = top()
    self.assertFalse(source().outdated)
    self.assertFalse(fixed().outdated)
    self.assertFalse(topTarget.outdated)

    newBuild()
    vSource.value = "newvalue"
    topTarget = top()
    self.assertTrue(source().outdated)
    self.assertTrue(fixed().outdated)
    self.assertFalse(topTarget.outdated)

  def failWithZDE(self, t: str) -> None:
    print(len(t) / 0)

  def test_buildFailUpdateStatefile(self) -> None:
    first = inputTask(Value("first", "vfirst"))

    @task
    def second() -> Target[Value[str]]:
      t = target(Value("second", "vsecond"), first(), state="fixed")
      if t.outdated:
        self.failWithZDE("a")
      return t

    with self.assertRaises(ZeroDivisionError):
      second()
    tSecond = currentBuild().getTarget("second")
    self.assertTrue(first().outdated)
    self.assertIsNotNone(tSecond)
    self.assertTrue(tSecond is not None and tSecond.outdated)

    ## Now run again and see that first is not again recreated

    newBuild()
    with self.assertRaises(ZeroDivisionError):
      second()
    self.assertFalse(first().outdated)

  def test_inMemTarget(self) -> None:
    v0 = Value("t0", 117)
    t0 = inputTask(v0)

    vOther = Value("other", 0)

    @task
    def other() -> Target[Value[int]]:
      dep = t0()
      t = target(vOther, dep, state="value")
      if t.outdated:
        t.item.value = dep.item.value
      return t

    tOther = other()
    self.assertTrue(tOther.outdated)
    self.assertEqual(117, tOther.item.value)

    newBuild()
    tOther = other()
    self.assertFalse(tOther.outdated)

    newBuild()
    v0.value = 116
    tOther = other()

    self.assertTrue(tOther.outdated)
    self.assertEqual(116, tOther.item.value)

  def test_updatingAnUpdatedIsNoop(self) -> None:
    @task
    def t0() -> Target[str]:
      return target("somevalue", state="value")

    # This failed in some version, when the target was done twice in a build
    self.assertEqual(0, runTasks(["t0", "t0"]))

  def test_DependencyLoopDetection(self) -> None:
    @task
    def ding() -> Target[str]:
      return target("ding", dong(), state="value")

    @task
    def dong() -> Target[str]:
      return target("dong", ding(), state="value")

    with self.assertRaisesRegex(BuildException, "dependency loop.*ding.*dong"):
      dong()
