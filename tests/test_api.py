import unittest
import sys, os
import hashlib
import shutil

## The tests must be started from the project directory
sys.path += [os.getcwd()]

from pythonbuilder import (
  BuildException,
  STATEFILE,
  Target,
  findTarget,
  stateDirContent,
  stateFileContent,
  stateFileIteratorContent,
  stateFixed,
  stateNew,
  updateTargets,
  resetTraversalState,
  LOG,
  TARGETS,
  ALIAS,
)
TMPDIR=os.path.join("build", "testtmp")

def writeToFile(text, fname):
  with open(fname, "wb") as outfile:
    outfile.write(text.encode())

class TestTargetApi(unittest.TestCase):
  """Test various functions provided by python builder, mainly taken out of core
  to have smaller files.
  """

  def setUp(self):
    if os.path.isdir(TMPDIR):
      shutil.rmtree(TMPDIR)
    os.makedirs(TMPDIR, exist_ok=True)

  def test_stateFileContent(self):
    f = os.path.join(TMPDIR, "testout")
    t = Target(f, state="file")

    ## Don't fail for a non-existent file and provide a new hash each time.
    ## hello future when this fails due to same nanosecond, you have
    ## really fast computers
    hash1 = stateFileContent(t)
    hash2 = stateFileContent(t)
    self.assertNotEqual(hash1, hash2)

    writeToFile("hallo", f)
    hash1 = stateFileContent(t)
    hash2 = stateFileContent(t)
    self.assertEqual(hash1, hash2)
    
if __name__ == '__main__':
  #unittest.main(defaultTest='TestUpdateTargets.test_buildFAilDoesNotUpdateStatefile')
  unittest.main()
    
