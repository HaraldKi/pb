import unittest
from pathlib import Path

import pythonbuilder


class CommonFixture(unittest.TestCase):
  def setUp(self) -> None:
    self.statefile = pythonbuilder.STATEFILE
    pythonbuilder.STATEFILE = Path(
      "build", "testtmp", self.__class__.__name__.lower() + ".state"
    )
    pythonbuilder.STATEFILE.unlink(missing_ok=True)
    pythonbuilder._TARGETS.clear()
    pythonbuilder.LOG.setLevel("WARNING")

  def tearDown(self) -> None:
    pythonbuilder.STATEFILE = self.statefile
