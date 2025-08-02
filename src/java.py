"""
Helpers to compile Java and run unit tests with  coverage.
"""
import os
import sys
from pathlib import Path

from pythonbuilder import pbexec

_PATHSEP = ";" if sys.platform == "windows" else ":"

def compileJava(targetPath: Path, srcPath: Path, *classpath: Path) -> None:
  """A default java compilation command. Kept simple. If you need a more
  elaborate setup, it is easy enough to write your own, rather than this
  function being extremely configurable and configure it.

  :param targetPath: a ``Path`` where to drop the compiled files
  :param srcPath: the source files directory
  :param classpath: classpath members
  """
  files = map(str, srcPath.rglob("*.java"))
  cp = os.pathsep.join(map(lambda d: str(d), classpath))
  pbexec("javac", "-g",
         "-d", str(targetPath),
         "-Xmaxerrs", "5",
         "-Xmaxwarns", "5",
         "-cp", cp,
         files)

  
def jacocoRunJunit4(targetPath: Path,
                    jacocoJar: Path,
                    testClassesPath: Path,
                    *classpath: Path) -> None:
  """Runs junit4 tests with the default ``JunitCore`` class.

  :param targetPath: the path of the coverage data to produce by running with
    jacoco
  :param jacocoJar: the jar ``org.jacoco.agent...jar``, not going on the class
    path
  :param testClassesPath: a ``Path`` representing a classpath entry for test
     classes, all files matching ``Test*.class`` are used as test classes.
  :param classpath: further classpath entries, i.e. classes, junit jar, etc.
  """

  testclasses = \
    map(lambda p: classForPath(testClassesPath, p),
        filter(lambda p: p.name.find("$")<0,
               testClassesPath.rglob("Test*.class")))
  cp = _PATHSEP.join(map(lambda d: str(d), [testClassesPath] + list(classpath)))
  pbexec("java",
         "-javaagent:%s=destfile=%s,append=false" % (jacocoJar, targetPath),
         "-cp", cp,
         "org.junit.runner.JUnitCore",
         *testclasses)

def jacocoReport(targetPath: Path,
                 jacocoCli: Path,
                 jacocoData: Path,
                 classFiles: Path,
                 sourceFiles: Path) -> None:
  """
  Creates a coverage report from the output of `jacocoRunJunit4`.


  :param targetPath: the directory where to place the coverage html files
  :param jacocoCli: the jar ``org.jacoco.cli...jar``.
  :param jacocoData: the output of ``jacocoRunJunit4``
  :param classFiles: the compiled classes classpath
  :param sourceFiles: directory with the source files
  """
  pbexec("java",
         "-jar", jacocoCli,
         "report", jacocoData,
         "--classfiles", classFiles,
         "--sourcefiles", sourceFiles,
         "--html", targetPath
         )
         
def classForPath(classpathEntry: Path, p: Path) -> str:
  """Converts a path relative to root directory to a class name.

  For example if ``classpathEntry`` is ``build/test`` and the
  ``p`` is ``build/test/my/package/Dodo.class``, the result is
  ``my.package.Dodo``.

  :param classpathEntry: a directory containing compiled classes
  :param p: a ``*.class`` file within ``classpathEntry``
  """
  return ".".join(p.relative_to(classpathEntry).parts).replace(".class", "")
