import os
import sys
import unittest

## The tests must be started from the project directory
sys.path += [os.path.join(os.getcwd(), "src")]
from pythonbuilder import LOG

if __name__ == "__main__":
  LOG.setLevel("ERROR")
  unittest.main(verbosity=0)
