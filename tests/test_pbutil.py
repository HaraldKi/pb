import logging
import unittest
from os import PathLike
from pathlib import Path

from pbutil import Paths, RootPathMapper, _loglevels, main
from pythonbuilder import (
  LOG,
  BuildException,
  Target,
  rawUpdateTargets,
  resetTraversalState,
  stateFileIteratorContent,
)


class TestRootPathMapper(unittest.TestCase):
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


class TestPaths(unittest.TestCase):
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

    ## This will fail in the future if pydoctor changes what it generates
    ## Just check and adapt a bit.
    pg = Paths.rglob("apidoc", "*.svg").mappedTo(Path("."))
    self.assertEqual(
      sorted([Path("fonts/info.svg"), Path("fonts/x-circle.svg")]), sorted([*pg])
    )

    pg = Paths.glob("apidoc", "*.json").mappedTo(Path("."))
    self.assertEqual(
      sorted([Path("searchindex.json"), Path("fullsearchindex.json")]), sorted([*pg])
    )

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


class TestMain(unittest.TestCase):

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
    keptLevel = LOG.level
    for level in _loglevels:
      ch = level[0]
      main("ll="+ch)
      self.assertEqual(level.upper(), logging.getLevelName(LOG.level))
    LOG.setLevel(keptLevel)

  def testFailWrongLevel(self) -> None:
    self.assertFalse(main("ll=x"))

  def testForceTargetThenFailLevel(self) -> None:
    # we set force for a target immediately, even if pbmain then fails on ll
    t0 = Target("some-target", name="some-target", state="value")
    self.assertFalse(main("force=some-target", "ll=x"))
    self.assertTrue(t0.force)

  def testFailWrongTarget(self) -> None:
    self.assertFalse(main("force=xxyy"))

  def testForceTargetThenFailUnknownTarget(self) -> None:
    t = Target("other-target", name="other-target", state="value")
    self.assertFalse(main("force=other-target,ddxx"))
    self.assertTrue(t.force)

  def testTargetNameWithEqual(self) -> None:
    # yes we somehow support this a long as the target does not start with
    # ll= or force= (so far)
    t = Target("x=y", name="x=y", state="value")
    self.assertTrue(main("x=y"))
    self.assertTrue(t.recreated)
