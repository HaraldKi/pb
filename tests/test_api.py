import shutil
from pathlib import Path

import support

from pythonbuilder.pythonbuilder import (
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

    ## Don't fail for a non-existent file and provide a new hash each time.
    ## Hello future when this fails due to same nanosecond, you have
    ## really fast computers
    hash1 = stateFileContent(f)
    hash2 = stateFileContent(f)
    self.assertNotEqual(hash1, hash2)

    writeToFile("hallo", f)
    hash1 = stateFileContent(f)
    hash2 = stateFileContent(f)
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

    # verify that None is dropped
    flatten(result, [[1, 2], None, "x"])
    self.assertEqual(["1", "2", "x"], result)
    result = []
