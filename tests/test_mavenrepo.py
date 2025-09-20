import os
import shutil
import sys
import unittest

## The tests must be started from the project directory
sys.path += [os.path.join(os.getcwd(), "src")]
import support

from pythonbuilder import resetTraversalState, updateTargets
from pythonbuilder.mavenrepo import MavenArtifact

TMPDIR = os.path.join("build", "testtmp")

# mypy: allow-untyped-defs


@unittest.skipUnless(
  os.environ.get("TEST_MAVENREPO", "") == "TRUE",
  "run test with file download only on demand",
)
class TestMavenArtifact(support.CommonFixture):
  def setUp(self):
    super().setUp()
    if os.path.isdir(TMPDIR):
      shutil.rmtree(TMPDIR)
    os.makedirs(TMPDIR)

  def testFullUsecase(self):
    lib = MavenArtifact.fromGradleShort("org.hamcrest:hamcrest:2.2", "jar")
    self.assertEqual("hamcrest-2.2.jar", lib.filename())
    self.assertEqual("org/hamcrest/hamcrest/2.2/hamcrest-2.2.jar", lib.repoUrl())

    ## first download from remote
    remoteTarget = lib.asTarget(TMPDIR, "https://repo1.maven.org/maven2/", name="lib")
    updateTargets("lib")
    self.assertTrue(remoteTarget.recreated)
    self.assertTrue(os.path.isfile(os.path.join(TMPDIR, lib.filename())))

    resetTraversalState()
    updateTargets("lib")
    self.assertTrue(remoteTarget.updated)
    self.assertFalse(remoteTarget.recreated)
