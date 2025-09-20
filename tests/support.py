import unittest
from pathlib import Path

import pythonbuilder


class CommonFixture(unittest.TestCase):
  def setUp(self) -> None:
    self.statefile = pythonbuilder.getStatefile()
    testStatefile = Path("build", "testtmp", self.__class__.__name__.lower() + ".state")
    pythonbuilder.setStatefile(testStatefile)
    testStatefile.unlink(missing_ok=True)
    pythonbuilder.getTargets().clear()
    pythonbuilder.LOG.setLevel("WARNING")

  def tearDown(self) -> None:
    pythonbuilder.setStatefile(self.statefile)
