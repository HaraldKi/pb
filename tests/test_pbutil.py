import io
import logging
import re
import shutil
import sys
from os import PathLike
from pathlib import Path

import support

from pbutil import (
  Paths,
  RootPathMapper,
  _loglevels,
  copyFiles,
  filterPath,
  filterPathRe,
  main,
  touch,
)
from pythonbuilder import (
  LOG,
  BuildException,
  Target,
  rawUpdateTargets,
  resetTraversalState,
  stateFileIteratorContent,
)

TESTTMP = Path("build", "testtmp")


class TestRootPathMapper(support.CommonFixture):
  def test_empty(self) -> None:
    rpm = RootPathMapper(Path("b"), lambda p: [])(Path("a"))
    result = next(rpm, None)
    self.assertEqual(None, result)

  def test_mapping(self) -> None:
    paths = [Path(p) for p in ["x", "r/sss", "a/Lor/Mor", "b/Z"]]
    oldP = Path("a")
    oldPaths = [oldP / p for p in paths]
    newP = Path("b")
    newPaths = [newP / p for p in paths]
    mapped = [p for p in RootPathMapper(oldP, lambda p: oldPaths)(newP)]
    self.assertEqual(newPaths, mapped)

  def test_mappingFail(self) -> None:
    self.assertRaisesRegex(
      BuildException,
      "cannot map \\w+ as it does not have",
      next,
      RootPathMapper(Path("b"), lambda p: [Path("a")])(Path("a")),
    )


class TestPaths(support.CommonFixture):
  def testFixed(self) -> None:
    pg = Paths(Path("a"), lambda root: [root / p for p in [Path("x"), Path("t/z")]])
    self.assertEqual([Path("a/x"), Path("a/t/z")], [*pg])

  def testFixedMapped(self) -> None:
    pg = Paths(Path("a"), lambda root: [root / p for p in [Path("x"), Path("t/z")]])
    mapped = pg.mappedTo(Path("XX"))
    self.assertEqual([Path("XX/x"), Path("XX/t/z")], [*mapped])

  def testGlob(self) -> None:
    # Assumes we are running in the project's root directory with subdir ./src
    pg = Paths(Path("src"), lambda root: root.glob("*.py"))
    self.assertEqual([*Path("src").glob("*.py")], [*pg])

    ## This needs an adaption whenever we add more source code
    pg = Paths.rglob("src", "pb*").mappedTo(Path("."))
    self.assertEqual(sorted([Path("pbpython.py"), Path("pbutil.py")]), sorted([*pg]))

  def testPathFromStr(self) -> None:
    pg = Paths("dodo", lambda p: [p / "x", p / "y"])
    self.assertEqual([Path("dodo/x"), Path("dodo/y")], [*pg])

  def testPathLikeness(self) -> None:
    pg = Paths("blabla", lambda p: [])
    self.assertTrue(isinstance(pg, PathLike))
    other = Path(pg)
    self.assertEqual(Path("blabla"), other)

  def testBotchedIterator(self) -> None:
    self.assertRaisesRegex(
      BuildException,
      "botched iterable in Paths",
      list,
      Paths(Path("src"), lambda p: [p / "bla", Path("not-src/bla")]),
    )

  def testGlobCanRestart(self) -> None:
    pg = Paths.glob("src", "*.py")
    l1 = [*pg]
    l2 = [*pg]
    self.assertTrue(len(l1) > 0)
    self.assertTrue(len(l2) > 0)
    self.assertEqual(l1, l2)

  def testWithTarget(self) -> None:
    # assume we're running in the projects root directory
    pg = Target(Paths.glob("src", "*.py"), state=stateFileIteratorContent)
    pgState = pg._computeState()
    expected = stateFileIteratorContent(Path("src").glob("*.py"))
    self.assertEqual(expected, pgState)

  def testWithFilter(self) -> None:
    pg = Paths("root", lambda r: [r / p for p in ["bla", "di.png", "do.html"]], "files")
    filtered = pg.withFilter(lambda rp: None if rp.suffix == ".html" else rp, "nohtml")
    self.assertEqual([Path("root", "bla"), Path("root", "di.png")], [*filtered])
    ## Verify that we have restartable iterables
    self.assertEqual([Path("root", "bla"), Path("root", "di.png")], [*filtered])

  def testWithFilterBotches(self) -> None:
    pg = Paths("root", lambda r: [r / p for p in ["a", "b"]])
    filtered = pg.withFilter(lambda rp: Path("/bla"), "botched")
    with self.assertRaisesRegex(BuildException, "botched filter maps"):
      [*filtered]


class TestMain(support.CommonFixture):
  logfails: int = 0

  def filter(self, record: logging.LogRecord) -> bool:
    if record.levelno >= logging.WARNING:
      self.logfails += 1
    return False

  def setUp(self) -> None:
    super().setUp()
    self.logfails = 0
    LOG.addFilter(self.filter)

  def tearDown(self) -> None:
    LOG.removeFilter(self.filter)
    self.assertEqual(0, self.logfails)
    super().tearDown()

  def assertLogFails(self, count: int) -> None:
    lf = self.logfails
    self.logfails = 0
    self.assertEqual(count, lf)

  def testForceTarget(self) -> None:
    bottom = Target("bottom", state="value")
    mid = Target("mid", bottom, state="value")
    top = Target("top", mid, state="value")

    rawUpdateTargets(top)
    self.assertTrue(bottom.recreated)
    self.assertTrue(mid.recreated)
    self.assertTrue(top.recreated)

    resetTraversalState()
    self.assertTrue(main("top"))
    self.assertFalse(bottom.recreated)
    self.assertFalse(mid.recreated)
    self.assertFalse(top.recreated)

    resetTraversalState()
    self.assertTrue(main("force=mid"))
    self.assertFalse(bottom.recreated)
    self.assertTrue(mid.recreated)
    # top is false again, because though mid was recreated, its value, so it state
    # are unchanged
    self.assertFalse(top.recreated)

    resetTraversalState()
    self.assertTrue(main("force=top,bottom"))
    self.assertTrue(bottom.recreated)
    self.assertFalse(mid.recreated)
    self.assertTrue(top.recreated)

  def testSetLoglevel(self) -> None:
    ## Without any target on the command line, main() prints the list of targets plus an
    ## explainer line. To avoid this we provide minimal food.
    Target("dummy", state="fixed", name="dummy")
    keptLevel = LOG.level
    for level in _loglevels:
      ch = level[0]
      main("ll=" + ch, "dummy")
      self.assertEqual(level.upper(), logging.getLevelName(LOG.level))
    LOG.setLevel(keptLevel)

  def testFailWrongLevel(self) -> None:
    self.assertFalse(main("ll=x"))
    self.assertLogFails(1)

  def testForceTargetThenFailLevel(self) -> None:
    # we set force for a target immediately, even if pbmain then fails on ll
    t0 = Target("some-target", name="some-target", state="value")
    self.assertFalse(main("force=some-target", "ll=x"))
    self.assertTrue(t0.force)
    self.assertLogFails(1)

  def testFailWrongTarget(self) -> None:
    self.assertFalse(main("force=xxyy"))
    self.assertLogFails(1)

  def testForceTargetThenFailUnknownTarget(self) -> None:
    t = Target("other-target", name="other-target", state="value")
    self.assertFalse(main("force=other-target,ddxx"))
    self.assertTrue(t.force)
    self.assertLogFails(1)

  def testTargetNameWithEqual(self) -> None:
    # yes we somehow support this a long as the target does not start with
    # ll= or force= (so far)
    t = Target("x=y", name="x=y", state="value")
    self.assertTrue(main("x=y"))
    self.assertTrue(t.recreated)

  def testPrintTargets(self) -> None:
    one = Target("one", state="fixed")
    two = Target("two", one, state="fixed")
    Target("three", two, state="fixed")
    stdout = sys.stdout
    buffered = io.StringIO()
    sys.stdout = buffered
    try:
      self.assertTrue(main())
    except Exception as e:
      raise e
    finally:
      sys.stdout = stdout

    matches = re.findall("one|two|three", buffered.getvalue())
    self.assertEqual("one", matches[0])
    self.assertEqual("two", matches[1])
    self.assertEqual("three", matches[2])


class TestCopyfiles(support.CommonFixture):
  COPYFILESDIR = TESTTMP / "copyfiles"

  def setUp(self) -> None:
    super().setUp()
    if self.COPYFILESDIR.exists():
      shutil.rmtree(self.COPYFILESDIR)

  def testCopySingleFile(self) -> None:
    p = Paths.glob("src", "pbutil.py")
    self.assertFalse(Path(self.COPYFILESDIR / "pbutil.py").exists())
    copyFiles(self.COPYFILESDIR, p)
    self.assertTrue((self.COPYFILESDIR / "pbutil.py").exists())

  def testCopyFilesInDir(self) -> None:
    p = Paths.glob(".", "src/pb*.py")
    self.assertFalse(Path(self.COPYFILESDIR / "src", "pbutil.py").exists())
    self.assertFalse(Path(self.COPYFILESDIR / "src", "pbpython.py").exists())
    copyFiles(self.COPYFILESDIR, p)
    self.assertTrue(Path(self.COPYFILESDIR / "src", "pbutil.py").exists())
    self.assertTrue(Path(self.COPYFILESDIR / "src", "pbpython.py").exists())


class TestFilterPath(support.CommonFixture):
  D = TESTTMP / "filterpath"

  def setUp(self) -> None:
    super().setUp()
    if self.D.exists():
      shutil.rmtree(self.D)

  def testFileOK(self) -> None:
    p1 = self.D / "xx"
    touch(p1)
    result = list(filterPath(self.D))
    self.assertEqual(1, len(result))
    self.assertEqual(p1, result[0])

    p2 = self.D / "yy"
    touch(p2)
    result = list(filterPath(self.D, lambda p: p.name == "yy"))
    self.assertEqual(1, len(result))
    self.assertEqual(p2, result[0])

    result = list(filterPath(self.D, lambda p: p.name != "xx"))
    self.assertEqual(1, len(result))
    self.assertEqual(p2, result[0])

  def testDirOK(self) -> None:
    p1 = self.D / "d1" / "x"
    p2 = self.D / "d2" / "x"

    touch(p1)
    touch(p2)
    result = list(filterPath(self.D, dirOK=lambda d: d.name == "d1"))
    self.assertEqual(1, len(result))
    self.assertEqual(p1, result[0])

    result = list(filterPath(self.D, dirOK=lambda d: d.name != "d1"))
    self.assertEqual(1, len(result))
    self.assertEqual(p2, result[0])


class TestFilterPathRe(support.CommonFixture):
  D = TESTTMP / "filterpathre"

  def setUp(self) -> None:
    super().setUp()
    if self.D.exists():
      shutil.rmtree(self.D)
    touch(self.D / "a")
    touch(self.D / "ab")
    touch(self.D / "abc")
    touch(self.D / "dir1" / "x")
    touch(self.D / "dir2" / "x")
    touch(self.D / "dir3" / "a")

  def testGetAll(self) -> None:
    result = [*filterPathRe(self.D)]
    self.assertEqual(6, len(result))

    result = [*filterPathRe(self.D, dirs=True)]
    self.assertEqual(9, len(result))

  def testIncDir(self) -> None:
    result = list(filterPathRe(self.D, "/", dirI="1"))
    self.assertEqual(1, len(result))
    self.assertEqual(self.D / "dir1" / "x", result[0])

  def testExcDir(self) -> None:
    result = list(
      map(lambda p: "/".join(p.parts[-2:]), list(filterPathRe(self.D, "/", dirX="1")))
    )
    result = sorted(result)
    self.assertEqual(2, len(result))
    self.assertEqual("dir2/x", result[0])
    self.assertEqual("dir3/a", result[1])

  def testIncFile(self) -> None:
    result = list(filterPathRe(self.D, "(^|/)a"))
    self.assertEqual(4, len(result))

  def testExcFile(self) -> None:
    result = list(filterPathRe(self.D, fileX="x|ab$"))
    self.assertEqual(3, len(result))


class TestPathFiltered(support.CommonFixture):
  """The filterPath and filterPathRe functions are tested quite well. Just make sure
  we don't have something funky going on. (Smoke test.)"""

  D = TESTTMP / "pathfiltered"

  def setUp(self) -> None:
    super().setUp()
    if self.D.exists():
      shutil.rmtree(self.D)

  def testBasics(self) -> None:
    p1 = self.D / "blabla"
    p2 = self.D / "dir" / "blabla"
    touch(p1)
    touch(p2)
    result = sorted(list(Paths.filtered(self.D)))
    self.assertEqual([p1, p2], result)

    ## verify restartable iterable
    result = sorted(list(Paths.filtered(self.D)))
    self.assertEqual([p1, p2], result)

    result = list(Paths.filtered(self.D, dirs=True))
    self.assertEqual(3, len(result))

    result = list(Paths.filtered(self.D, dirOK=lambda p: False))
    self.assertEqual(1, len(result))

    result = list(Paths.filtered(self.D, fileOK=lambda p: False))
    self.assertEqual(0, len(result))

    result = list(
      Paths.filtered(self.D, fileOK=lambda p: False, dirOK=lambda p: True, dirs=True)
    )
    self.assertEqual(1, len(result))
