import os
import shutil
import unittest

import support

from pythonbuilder import resetTraversalState, updateTargets
from pythonbuilder.mavenrepo import MavenArtifact

TMPDIR = os.path.join("build", "testtmp")


@unittest.skipIf(
  os.environ.get("TEST_MAVENREPO", "") != "TRUE",
  "run test with file download only on demand",
)
class TestMavenArtifact(support.CommonFixture):
  def setUp(self) -> None:
    super().setUp()
    if os.path.isdir(TMPDIR):
      shutil.rmtree(TMPDIR)
    os.makedirs(TMPDIR)

  def testFullUsecase(self) -> None:
    lib = MavenArtifact.fromGradleShort("org.hamcrest:hamcrest:2.2", "jar")
    self.assertEqual("hamcrest-2.2.jar", lib.filename())
    self.assertEqual("org/hamcrest/hamcrest/2.2/hamcrest-2.2.jar", lib.repoUrl())

    ## first download from remote
    remoteTarget = lib.asTarget(TMPDIR, "https://repo1.maven.org/maven2/", name="lib")
    updateTargets("lib")
    self.assertTrue(remoteTarget.outdated)
    self.assertTrue(os.path.isfile(os.path.join(TMPDIR, lib.filename())))

    resetTraversalState()
    updateTargets("lib")
    self.assertTrue(remoteTarget.updated)
    self.assertFalse(remoteTarget.outdated)
