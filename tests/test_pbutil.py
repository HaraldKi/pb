import unittest
from pathlib import Path

from pbutil import Paths, mappedPaths
from pythonbuilder import BuildException, Target, stateFileIteratorContent


class TestMappedPaths(unittest.TestCase):
  def test_empty(self) -> None:
    it = mappedPaths(Path("a"), Path("b"), [])
    result = next(it, None)
    self.assertEqual(None, result)

  def test_mapping(self) -> None:
    paths = [Path(p) for p in ["x", "r/sss", "a/Lor/Mor", "b/Z"]]
    oldP = Path("a")
    oldPaths = [oldP / p for p in paths]
    newP = Path("b")
    newPaths = [newP / p for p in paths]
    mapped = [p for p in mappedPaths(newP, oldP, oldPaths)]
    self.assertEqual(newPaths, mapped)

  def test_mappingFail(self) -> None:
    self.assertRaisesRegex(
      BuildException,
      "cannot map \\w+ as it does not have",
      next,
      mappedPaths(Path("a"), Path("b"), [Path("a")]),
    )


class TestPaths(unittest.TestCase):
  def testFixed(self) -> None:
    pg = Paths(Path("a"), [Path("a") / p for p in [Path("x"), Path("t/z")]])
    self.assertEqual([Path("a/x"), Path("a/t/z")], [*pg])

  def testFixedMapped(self) -> None:
    pg = Paths(Path("a"), [Path("a") / p for p in [Path("x"), Path("t/z")]])
    mapped = pg.mappedTo(Path("XX"))
    self.assertEqual([Path("XX/x"), Path("XX/t/z")], [*mapped])

  def testGlob(self) -> None:
    # Assumes we are running in the project's root directory with subdir ./src
    pg = Paths(Path("src"), Path("src").glob("*.py"))
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
    pg = Paths("dodo", [Path("dodo/x"), Path("dodo/y")])
    self.assertEqual([Path("dodo/x"), Path("dodo/y")], [*pg])

  def testBotchedIterator(self) -> None:
    self.assertRaisesRegex(
      BuildException,
      "botched iterable in Paths",
      list,
      Paths(Path("src"), [Path("src/bla"), Path("not-src/bla")]),
    )

  def testWithTarget(self) -> None:
    # assume we're running in the projects root directory
    pg = Target(Paths.glob("src", "*.py"), state=stateFileIteratorContent)
    pgState = pg._computeState()
    expected = stateFileIteratorContent(Path("src").glob("*.py"))
    self.assertEqual(expected, pgState)
