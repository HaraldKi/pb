import sys
import os
import unittest

## The tests must be started from the project directory
sys.path += [os.path.join(os.getcwd(), "src")]
from pythonbuilder import LOG

from test_api import *
from test_core import *
from test_mavenrepo import *

if __name__ == '__main__':
  LOG.setLevel("ERROR")
  unittest.main(verbosity=0)
