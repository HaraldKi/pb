import unittest
import sys
import os
import shutil

## The tests must be started from the project directory
sys.path += [os.getcwd()]
from pythonbuilder import updateTargets, resetTraversalState, LOG
from mavenrepo import MavenArtifact

TMPDIR=os.path.join("build", "testtmp")

@unittest.skipUnless(os.environ.get("TEST_MAVENREPO", "") == "TRUE",
                     "run test with file download only on demand")
class TestMavenArtifact(unittest.TestCase):
  def setUp(self):
    if os.path.isdir(TMPDIR):
      shutil.rmtree(TMPDIR)
    os.makedirs(TMPDIR)

  def testFullUsecase(self):
    lib = MavenArtifact.fromGradleShort("org.hamcrest:hamcrest:2.2", "jar")
    self.assertEqual("hamcrest-2.2.jar", lib.filename())
    self.assertEqual("org/hamcrest/hamcrest/2.2/hamcrest-2.2.jar", lib.repoUrl())

    ## first download from remote
    remoteTarget = lib.asTarget(TMPDIR, "https://repo1.maven.org/maven2/",
                                alias="lib")
    updateTargets("lib")
    self.assertTrue(remoteTarget.recreated)
    self.assertTrue(os.path.isfile(os.path.join(TMPDIR, lib.filename())))

    resetTraversalState()
    updateTargets("lib")
    self.assertTrue(remoteTarget.updated)
    self.assertFalse(remoteTarget.recreated)

if __name__ == '__main__':
  LOG.setLevel("ERROR")
  #unittest.main(defaultTest='TestUpdateTargets.test_buildFAilDoesNotUpdateStatefile')
  unittest.main(verbosity=2)
