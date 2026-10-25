"""Provides classes and functions to work with maven (gradle) style artifacts."""

import shutil
from abc import abstractmethod
from pathlib import Path
from typing import Callable
from urllib import request

from .pythonbuilder import (
  StateProvider,
  Target,
  getLogger,
  pbexec,
  renameFunction,
  stateDirContent,
  target,
  task,
)


class MavenArtifact:
  """Encapsulates group, name, version and type (file extension) of an artifact
  as provided, for example, by a maven repository.

  The pieces are used to create URLs and file names to access a
  repository.
  """

  def __init__(
    self, group: str, name: str, version: str, classifier: str | None, type: str
  ):
    """
    Creates the artifact.

    ### Parameters

    - group: typically something like `"org.json"`
    - name: of the artifact, like `"json"`
    - version: of the artifact, like "1.2.3"
    - classifier: of the artifact, like "runtime", may be `None`
    - type: ends up as the file extension, like `"jar"`
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

  def __repr__(self) -> str:
    cls = "" if self.classifier is None else self.classifier
    key = ":".join([self.group, self.name, self.version, cls, self.type])
    return f"Maven({key})"

  @staticmethod
  def fromGradleShort(
    groupNameVersionClassifier: str, type: str
  ) -> "MavenArtifact":
    """
    Create a `MavenArtifact` from a Gradle short form like
    `"org.json:json:20250107"`. A forth element, the classifier, may be given
    too.

    ### Parameters
    - str: a gradle short group:name:version(:classifier)? combo
    - type: file type, like "jar"
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

    ### Return
    File name of the form "name-version-classifier.type" where
      "-classifier" is only provided if defined in the constructor.
    """
    cls = "-" + self.classifier if self.classifier is not None else ""
    return "%s-%s%s.%s" % (self.name, self.version, cls, self.type)

  def repoUrl(self) -> str:
    """Creates the relative URL part, including `filename()`, which can be used
    to fetch the target if prefixed by a repository URL.

    ### Return
    URL of the form "g1/g2/.../name/version/filename" where g1,... are
      the dot-separated parts of the group name.
    """
    return "%s/%s/%s/%s" % (
      self.group.replace(".", "/"),
      self.name,
      self.version,
      self.filename(),
    )

  def asTask(
    self, dir: str, mavenRepoUrl: str | None = None, name: str | None = None
  ) -> Callable[[], Target[Path]]:
    """Provides a task function which can be used to fetch the artifact and
    place it into the file system.

    ### Parameters

    - dir: directory to copy the artifact to, also the name of the
      `Target` returned.
    -  mavenRepoUrl: The URL to fetch the artifact from. If this is not
      provided we assume we have a local repository in `~/.m2`. The string
      must end with '/' otherwise the resulting URL is likely wrong.
    - name: optional name for the target being created, defaults to the name
      of the artifact

    ### Return
    An `@task` suitable to be called to get a `Target` for `dir`.

    """
    fetcher = (
      _MavenArtifactLocal(self)
      if mavenRepoUrl is None
      else _MavenArtifactRemote(self, mavenRepoUrl)
    )
    if name is None:
      name = self.name

    def f() -> Target[Path]:
      t = target(Path(dir, self.filename()), state="file")
      if t.outdated:
        fetcher.fetch(t.item)
      return t

    return task(renameFunction(f, name))


class MavenRepoArtifact(StateProvider):
  """Combines a MavenArtifact with a (local) repository URL prefix to represent
  a (locally) installed artifact.

  NOTE: Maven calls stuff in its local repository (`~/.m2/repository`), "installed"
  as opposed to "locally published". But see `publishLocal`.

  """

  def __init__(self, artifact: MavenArtifact, repo: Path | None):
    """Creates the artifact/repository combo.

    ### Parameters
    - artifact: to be installed/published.
    - repo: maven repository path, defaults to `Path.home() / ".m2" / "repository"`
    """

    self.artifact: MavenArtifact = artifact
    """to be installed/published"""

    self.repo: Path = (
      Path.home() / ".m2" / "repository" if repo is None else repo
    )
    """maven repository path"""

  def fullPath(self) -> Path:
    """Returns the full path to the artifact where it ends up in the
    repository."""
    return self.repo / self.artifact.repoUrl()

  def provideState(self) -> str:
    """Provides state over the whole directory where the artifact ends up to
    include source files and pom and whatnot.

    """
    statePath = self.fullPath().parent
    return stateDirContent(statePath)


def publishLocal(
  repoArtifact: MavenRepoArtifact, file: Path, srcjar: Path | None = None
) -> None:
  """Publishes the dependency as the target artifact, to be used in a task
  function after the `t.outdated`, as in:
  ```python
  @task
  def publishMyLib() -> Target[MavenRepoArtifact]:
    jarTarget = jar() # task to create the jar
    t = target(MavenRepoArtifact(...), jarTarget)
    if t.outdated:
      publishLocal(t.item, jarTarget.item)
    return t
  ```
  A glorious description for copying the `file` into the local maven repository,
  optionally accompanied by the `srcjar`.

  - repoArtifact: to create or overwrite
  - file: the file representing the artifact
  - srcjar: a jar (or other archive) with the source code, optional

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
    `os.environ(HOME)/.m2` to the given path.
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
