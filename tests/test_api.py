import shutil
from pathlib import Path

import support

from pythonbuilder import (
  Target,
  flatten,
  stateFileContent,
)

_TMPDIR = Path("build", "testtmp")


def writeToFile(text: str, fname: Path) -> None:
  with open(fname, "wb") as outfile:
    outfile.write(text.encode())


class TestPythonBuilderApi(support.CommonFixture):
  """Test various functions provided by python builder, mainly taken out of core
  to have smaller files.
  """

  def setUp(self) -> None:
    super().setUp()
    if _TMPDIR.is_dir():
      shutil.rmtree(_TMPDIR)
    _TMPDIR.mkdir(parents=True, exist_ok=True)

  def test_stateFileContent(self) -> None:
    f = _TMPDIR / "testout"
    t = Target(f, state="file")

    ## Don't fail for a non-existent file and provide a new hash each time.
    ## hello future when this fails due to same nanosecond, you have
    ## really fast computers
    hash1 = stateFileContent(t.item)
    hash2 = stateFileContent(t.item)
    self.assertNotEqual(hash1, hash2)

    writeToFile("hallo", f)
    hash1 = stateFileContent(t.item)
    hash2 = stateFileContent(t.item)
    self.assertEqual(hash1, hash2)

  def test_flatten(self) -> None:
    result: list[str] = []
    flatten(result, [[], []])
    self.assertEqual([], result)

    flatten(result, "bla")
    self.assertEqual(["bla"], result)
    result = []

    flatten(result, ["x", ["a", 1]])
    self.assertEqual(["x", "a", "1"], result)
    result = []
