"""
Helpers to compile Java and run unit tests with  coverage.
"""

import os
import re
import shutil
import sys
from pathlib import Path
from typing import Any
from .pythonbuilder import pbexec

_PATHSEP = ";" if sys.platform == "windows" else ":"
_JUNIT4_MAIN_CLASS = "org.junit.runner.JUnitCore"


def setJunitMainClass(className: str) -> None:
  """Set the fully qualified class name of the class to be invoked by
  jacocoRunJunit4, which defaults to `org.junit.runner.JUnitCore`.

  """
  global _JUNIT4_MAIN_CLASS
  _JUNIT4_MAIN_CLASS = className


def compileJava(
  targetPath: os.PathLike[Any], srcPath: os.PathLike[Any], *classpath: Path
) -> None:
  """A default java compilation command, kept simple.

  If you need a more elaborate setup, it is easy enough to write your own,
  rather than this function being extremely configurable and configure it.

  **NOTE**: This function recursively deletes `targetPath` first to make sure
  no cruft classes are left over after a source file was renamed or deleted.

  ### Parameters

  - targetPath: a `Path` where to drop the compiled files, will be remove first
  - srcPath: the source files directory
  - classpath: classpath members

  """
  if Path(targetPath).exists():
    shutil.rmtree(targetPath)
  files = map(str, Path(srcPath).rglob("*.java"))
  cp = os.pathsep.join(map(lambda d: os.fspath(d), classpath))
  pbexec(
    "javac",
    "-g",
    "-d",
    os.fspath(targetPath),
    "-Xmaxerrs",
    "5",
    "-Xmaxwarns",
    "5",
    "-cp",
    cp,
    files,
  )


def jacocoRunJunit4(
  targetPath: Path,
  testClassesPath: Path,
  testClassRe: str | re.Pattern[Any],
  jacocoJar: Path,
  *classpath: Path,
) -> None:
  """Runs junit4 tests with the default `JunitCore` class.

  ### Parameters

  - targetPath: the path of the coverage data to produce by running with jacoco

  - testClassesPath: a `Path` representing a classpath entry for test classes

  - testClassRe: a regular expression or compiled pattern which has to be
    matched by `*.class` files on the `testClassesPath` to be included as a test
    class. Classes with a `$` in the name are always excluded. If there are no
    helper classses on the classpath, just use `.`, otherwise, depending on your
    convention, `^Test.*` or `.*Test[.]class$` may be what you need. Only the
    file name, without any leading path name, will be searched with the pattern.

  - jacocoJar: the jar `org.jacoco.agent...jar`, not going on the class
    path

  - classpath: further classpath entries, i.e. classes, junit jar, etc.

  """

  if isinstance(testClassRe, str):
    testClassRe = re.compile(testClassRe)

  testclasses = map(
    lambda p: classForPath(testClassesPath, p),
    filter(
      lambda p: p.name.find("$") < 0 and testClassRe.search(p.name),
      testClassesPath.rglob("*.class"),
    ),
  )
  cp = _PATHSEP.join(map(lambda d: str(d), [testClassesPath] + list(classpath)))
  ("org.junit.runner.JUnitCore",)

  global _JUNIT4_MAIN_CLASS
  pbexec(
    "java",
    "-javaagent:%s=destfile=%s,append=false" % (jacocoJar, targetPath),
    "-cp",
    cp,
    _JUNIT4_MAIN_CLASS,
    *testclasses,
  )


def jacocoReport(
  targetPath: Path,
  jacocoCli: Path,
  jacocoData: Path,
  classFiles: Path,
  sourceFiles: Path,
) -> None:
  """
  Creates a coverage report from the output of `jacocoRunJunit4`.

  ### Parameters

  - targetPath: the directory where to place the coverage html files
  - jacocoCli: the jar `org.jacoco.cli...jar`.
  - jacocoData: the output of `jacocoRunJunit4`
  - classFiles: the compiled classes classpath
  - sourceFiles: directory with the source files
  """
  pbexec(
    "java",
    "-jar",
    jacocoCli,
    "report",
    jacocoData,
    "--classfiles",
    classFiles,
    "--sourcefiles",
    sourceFiles,
    "--html",
    targetPath,
  )


def classForPath(classpathEntry: Path, p: Path) -> str:
  """Converts a path relative to root directory to a class name.

  For example if `classpathEntry` is `build/test` and the
  `p` is `build/test/my/package/Dodo.class`, the result is
  `my.package.Dodo`.

  ### Parameters
  - classpathEntry: a directory containing compiled classes
  - p: a `*.class` file within `classpathEntry`
  """
  return ".".join(p.relative_to(classpathEntry).parts).replace(".class", "")
