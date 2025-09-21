import os
import sys
import unittest

## The tests must be started from the project directory
sys.path += [os.getcwd()]

from test_api import *  # noqa: F403
from test_core import *  # noqa: F403
from test_mavenrepo import *  # noqa: F403
from test_pbutil import *  # noqa: F403

from pythonbuilder import getLogger

if __name__ == "__main__":
  getLogger().setLevel("ERROR")
  unittest.main(verbosity=0)
