"""Provides a class to work with maven (gradle) style artifacts.
"""

from pathlib import Path
from pythonbuilder import Target, LOG, BuildException
import os
import shutil
from urllib import request
from abc import abstractmethod

class MavenArtifact:
  """Encapsulates group, name, version and type (file extension) of an artifact
  as provided, for example, by a maven repository.

  Basically, the pieces are used to create URLs and file names to access a
  repository.
  """
  def __init__(self, group: str, name: str, version: str, type: str):
    """
    Creates the artifact.

    :param group: typically something like ``"org.json"``
    :param name: of the artifact, like ``"json"``
    :param version: of the artifact, like "1.2.3"
    :param type: ends up as the file extension, like ``"jar"``
    """
    self.group = group
    """group of the artifact"""

    self.name = name
    """name of the artifact"""
    
    self.version = version
    """artifact version"""

    self.type = type
    """artifact type, typically a file extension like "jar" """

  @staticmethod
  def fromGradleShort(triple: str, type: str) -> 'MavenArtifact':
    """
    Create an `MavenArtifact` from a Gradle short form like
    ``"org.json:json:20250107"``.
    """
    parts = triple.split(":")
    if len(parts) != 3:
      raise ValueError("parameter have the form str0:str1:str2 but has %s parts"
                       % len(parts))
    return MavenArtifact(parts[0], parts[1], parts[2], type)

  def filename(self) -> str:
    """Provides the filename of the artifact.

    :return: file name of the form "name-version.type".
    """
    return "%s-%s.%s" % (self.name, self.version, self.type)

  def repoUrl(self) -> str:
    """Creates the relative URL part, including `filename()`, which can be used
    to fetch the target if prefixed by a repository URL.

    :return: URL of the form "g1/g2/.../name/version/filename" where g1,... are
      the dot-separated parts of the group name
    """
    return "%s/%s/%s/%s" \
      % (self.group.replace(".", "/"), self.name, self.version, self.filename())

  def asTarget(self,
               dir: str,
               mavenRepoUrl: str | None = None,
               name: str | None =None) -> Target[Path]:
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
    fetcher = _MavenArtifactLocal(self) \
      if mavenRepoUrl is None \
      else _MavenArtifactRemote(self, mavenRepoUrl)
    if name is None:
      name = self.name
    return Target(Path(dir, self.filename()),
                  state="file", name=name,
                  cmd=fetcher.fetch)

class _Fetcher:
  @abstractmethod
  def fetch(sefl, target: Target):
    pass

class _MavenArtifactLocal(_Fetcher):
  def __init__(self, artifact: MavenArtifact):
    self.artifact = artifact;

  def fetch(self, target: Target[Path]):
    """Copy the artifact from the local maven repository at
    ``os.environ(HOME)/.m2`` to the target's name assumed to be a valid path.

    """
    path = Path.home() / '.m2' / 'repository' / self.artifact.repoUrl()
    target.item.parent.mkdir(parents=True, exist_ok=True)
    LOG.info("* fetch %s -> %s", path, target.item)
    shutil.copy(path, target.item)

class _MavenArtifactRemote(_Fetcher):
  def __init__(self, artifact: MavenArtifact, repoUrl: str):
    self.artifact = artifact
    self.repoUrl = repoUrl

  def fetch(self, target: Target[Path]):
    """
    Copy the artifact from the configured maven repository
    to the target's name assumed to be a valid path.
    """
    url = self.repoUrl + self.artifact.repoUrl()
    target.item.parent.mkdir(parents=True, exist_ok=True)
    LOG.info("* fetch %s -> %s", url, target.item)
    with request.urlopen(url) as response:
      data = response.read()
      with open(target.item, "wb") as f:
        f.write(data)
