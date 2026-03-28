"""Provides classes and functions to work with maven (gradle) style artifacts."""

import shutil
from abc import abstractmethod
from pathlib import Path
from urllib import request

from .pythonbuilder import StateProvider, Target, getLogger, pbexec, stateDirContent


class MavenArtifact:
  """Encapsulates group, name, version and type (file extension) of an artifact
  as provided, for example, by a maven repository.

  Basically, the pieces are used to create URLs and file names to access a
  repository.
  """

  def __init__(
    self, group: str, name: str, version: str, classifier: str | None, type: str
  ):
    """
    Creates the artifact.

    :param group: typically something like ``"org.json"``
    :param name: of the artifact, like ``"json"``
    :param version: of the artifact, like "1.2.3"
    :param classifier: of the artifact, like "runtime", may be ``None``
    :param type: ends up as the file extension, like ``"jar"``
    """
    self.group = group
    """group of the artifact"""

    self.name = name
    """name of the artifact"""

    self.version = version
    """artifact version"""

    self.classifier = classifier
    """artifact classifier"""

    self.type = type
    """artifact type, typically a file extension like "jar" """

  @staticmethod
  def fromGradleShort(groupNameVersionClassifier: str, type: str) -> "MavenArtifact":
    """
    Create an `MavenArtifact` from a Gradle short form like
    ``"org.json:json:20250107"`` A forth element, the classifier, may be given
    too.
    """
    parts = groupNameVersionClassifier.split(":")
    if len(parts) == 3:
      return MavenArtifact(parts[0], parts[1], parts[2], None, type)
    if len(parts) == 4:
      return MavenArtifact(parts[0], parts[1], parts[2], parts[3], type)
    raise ValueError(
      "parameter must be group:name:version:classifier"
      + " where :classifier is optional, but is: "
      + groupNameVersionClassifier
    )

  def filename(self) -> str:
    """Provides the filename of the artifact.

    :return: file name of the form "name-version-classifier.type" where
      -classifier only provided if defined in the constructor..
    """
    cls = "-" + self.classifier if self.classifier is not None else ""
    return "%s-%s%s.%s" % (self.name, self.version, cls, self.type)

  def repoUrl(self) -> str:
    """Creates the relative URL part, including `filename()`, which can be used
    to fetch the target if prefixed by a repository URL.

    :return: URL of the form "g1/g2/.../name/version/filename" where g1,... are
      the dot-separated parts of the group name
    """
    return "%s/%s/%s/%s" % (
      self.group.replace(".", "/"),
      self.name,
      self.version,
      self.filename(),
    )

  def asTarget(
    self, dir: str, mavenRepoUrl: str | None = None, name: str | None = None
  ) -> Target[Path]:
    """
    Provides a `Target` which can be used to fetch the artifact and place it into
    the file system.

    :param dir: directory to copy the artifact to, also the name of the
      `Target` returned.
    :param  mavenRepoUrl: The URL to fetch the artifact from. If this is not
      provided we assume we have a local repository in ``~/.m2``. The string
      must end with '/' otherwise the resulting URL is likely wrong.
    :param name: optional name for the target being created, defaults to the name
      of the artifact
    :return: the target
    """
    fetcher = (
      _MavenArtifactLocal(self)
      if mavenRepoUrl is None
      else _MavenArtifactRemote(self, mavenRepoUrl)
    )
    if name is None:
      name = self.name
    return Target(
      Path(dir, self.filename()), state="file", name=name, cmd=fetcher.fetch
    )


class MavenRepoArtifact(StateProvider):
  """Combines a MavenArtifact with a (local) repository URL prefix to represent a
  (locally) installed artifact.

  Maven calls stuff in its local repository, typically ``~/.m2/repository``, "installed"
  as opposed to "locally published". But see `publishLocal`.

  """

  artifact: MavenArtifact
  """to be installed/published"""

  repo: Path = Path.home() / ".m2" / "repository"
  """maven repository path"""

  def __init__(
    self, artifact: MavenArtifact, repo: Path = Path.home() / ".m2" / "repository"
  ):
    """Creates the artifact/repository combo.

    :param artifact: to be installed/published.
    :param repo: maven repository path.
    """
    self.artifact: MavenArtifact = artifact
    self.repo: Path = repo

  def fullPath(self) -> Path:
    """Returns the full path to the artifact where it ends up in the repository."""
    return self.repo / self.artifact.repoUrl()

  def provideState(self) -> str:
    """Provides state over the whole directory where the artifact ends up to include
    source files and pom and whatnot."""
    statePath = self.fullPath().parent
    return stateDirContent(statePath)


def publishLocal(
  repoArtifact: MavenRepoArtifact, file: Path, srcjar: Path | None = None
) -> None:
  """Publishes the dependency as the target artifact, to be used as the ``cmd``
  parameter of a `Target`.

  A glorious description for copying the ``file`` into the local maven repository,
  optionally accompanied by the ``srcjar``.

  :param repoArtifact: to create or overwrite
  :param file: the file representing the artifact
  :param srcjar: a jar (or other archive) with the source code, optional

  """
  src = None if srcjar is None else "-Dsources=" + str(srcjar)
  artifact = repoArtifact.artifact
  pbexec(
    "mvn",
    "install:install-file",
    "-DlocalRepositoryPath=" + str(repoArtifact.repo),
    "-Dfile=" + str(file),
    src,
    "-DgroupId=" + artifact.group,
    "-DartifactId=" + artifact.name,
    "-Dversion=" + artifact.version,
    "-Dpackaging=" + artifact.type,
    "-DgeneratePom=true",
  )


class _Fetcher:
  @abstractmethod
  def fetch(self, path: Path) -> None:
    pass


class _MavenArtifactLocal(_Fetcher):
  def __init__(self, artifact: MavenArtifact) -> None:
    self.artifact = artifact

  def fetch(self, targetPath: Path) -> None:
    """Copy the artifact from the local maven repository at
    ``os.environ(HOME)/.m2`` to the given path.
    """
    path = Path.home() / ".m2" / "repository" / self.artifact.repoUrl()
    targetPath.parent.mkdir(parents=True, exist_ok=True)
    getLogger().info("* fetch %s -> %s", path, targetPath)
    shutil.copy(path, targetPath)


class _MavenArtifactRemote(_Fetcher):
  def __init__(self, artifact: MavenArtifact, repoUrl: str) -> None:
    self.artifact = artifact
    self.repoUrl = repoUrl

  def fetch(self, targetPath: Path) -> None:
    """
    Copy the artifact from the configured maven repository
    to the given path.
    """
    url = self.repoUrl + self.artifact.repoUrl()
    targetPath.parent.mkdir(parents=True, exist_ok=True)
    getLogger().info("* fetch %s -> %s", url, targetPath)
    with request.urlopen(url) as response:
      data = response.read()
      with open(targetPath, "wb") as f:
        f.write(data)
