"""
Provides some helper functions to deal with maven repositories and gradle
short package descriptions
"""

from pathlib import Path
from pythonbuilder import Target, LOG, BuildException
import os
import shutil
from urllib import request
from abc import abstractmethod

class MavenArtifact:
  """
  The triple of group, name, version and type (file extension) to manage an
  artifact provided, for example, by a maven repository. Basically the three
  pieces can be used to create URLs and file names to access a repository.

  Args:
    group (str): typically something like "org.json"
    name (str): name of the artifact, e.g. "json"
    version (str): version string, like "1.2.3"
    type (str): ends up as the file extension, e.g. "jar"
  """
  def __init__(self, group: str, name: str, version: str, type: str):
    self.group = group
    self.name = name
    self.version = version
    self.type = type

  @staticmethod
  def fromGradleShort(triple: str, type: str) -> 'MavenArtifact':
    """
    Create an `MavenArtifact` from a Gradle short form like
    `"org.json:json:20250107"`.
    """
    parts = triple.split(":")
    if len(parts) != 3:
      raise ValueError("parameter have the form str0:str1:str2 but has %s parts"
                       % len(parts))
    return MavenArtifact(parts[0], parts[1], parts[2], type)

  def filename(self) -> str:
    return "%s-%s.%s" % (self.name, self.version, self.type)

  def repoUrl(self) -> str:
    return "%s/%s/%s/%s" \
      % (self.group.replace(".", "/"), self.name, self.version, self.filename())

  def asTarget(self,
               dir: str,
               mavenRepoUrl: str | None = None,
               alias: str | None =None) -> Target:
    """
    Args:
      mavenRepoUrl: must end with '/' otherwise the resulting URL is likely wrong
    """
    fetcher = _MavenArtifactLocal(self) \
      if mavenRepoUrl is None \
      else _MavenArtifactRemote(self, mavenRepoUrl)

    return Target(os.path.join(dir, self.filename()),
                  state="file", alias=alias,
                  cmd=fetcher.fetch)

class _Fetcher:
  @abstractmethod
  def fetch(sefl, target: Target):
    pass

class _MavenArtifactLocal(_Fetcher):
  def __init__(self, artifact: MavenArtifact):
    self.artifact = artifact;

  def fetch(self, target: Target):
    """
    Copy the artifact from the local maven repository at `os.environ(HOME)/.m2`
    to the target's name assumed to be a valid path.
    """
    path = Path.home() / '.m2' / 'repository' / self.artifact.repoUrl()
    os.makedirs(os.path.dirname(target.name), exist_ok=True)
    LOG.info("* fetch %s -> %s", path, target.name)
    shutil.copy(path, target.name)

class _MavenArtifactRemote(_Fetcher):
  def __init__(self, artifact: MavenArtifact, repoUrl: str):
    self.artifact = artifact
    self.repoUrl = repoUrl

  def fetch(self, target: Target):
    """
    Copy the artifact from the configured maven repository
    to the target's name assumed to be a valid path.
    """
    url = self.repoUrl + self.artifact.repoUrl()
    os.makedirs(os.path.dirname(target.name), exist_ok=True)
    LOG.info("* fetch %s -> %s", url, target.name)
    with request.urlopen(url) as response:
      data = response.read()
      with open(target.name, "wb") as f:
        f.write(data)
