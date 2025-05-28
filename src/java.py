"""
Provide helpers to compile Java and run unit tests with  coverage.
"""
import sys

from pathlib import Path
from pythonbuilder import Target, LOG, BuildException, pbexec

_PATHSEP = ";" if sys.platform == "windows" else ":"

def compileJava(target: Target[Path]):
  """A default java compilation command. Kept simple. If you need a more
  elaborate setup, it is easy enough to write your own, rather than this
  function being extremely configurable and configure it.

  * target.dependencies[0] must be the source files
  * all other dependencies go on the class path

  :param target: a `Path` target where to drop the compiled files
  """
  files = map(str, target.dependencies[0].item.rglob("*.java"))
  cp = _PATHSEP.join(map(lambda d: str(d.item), target.dependencies[1:]))
  pbexec("javac", "-g",
         "-d", str(target.item),
         "-Xmaxerrs", "5",
         "-Xmaxwarns", "5",
         "-cp", cp,
         files)

  
def jacocoRunJunit4(target: Target[Path]):
  """Runs junit4 tests with the default `JunitCore` class.
  The dependencies of the target must have the following order:

  1. the jar `org.jacoco.agent...jar`, not going on the class path
  2. a `Path` representing a classpath entry for test classes, all files
     matching Test*.class are used as test classes.
  3. ... further class path parameters, i.e. classes, junit jar, etc

  :param target: the path of the coverage data to produce by running with jacoco
  """
  jacocoJar = str(target.dependencies[0].item)
  testClassesPath = target.dependencies[1].item;
  testclasses = \
    map(lambda p: classForPath(testClassesPath, p),
        filter(lambda p: p.name.find("$")<0,
               testClassesPath.rglob("Test*.class")))
  cp = _PATHSEP.join(map(lambda d: str(d.item), target.dependencies[1:]))
  pbexec("java",
         "-javaagent:%s=destfile=%s,append=false" % (jacocoJar, str(target.item)),
         "-cp", cp,
         "org.junit.runner.JUnitCore",
         *testclasses)

def jacocoReport(target: Target[Path]):
  """
  Creates a coverage report from the output of `jacocoRunJunit4`. The
  dependencies must have the following order:

  1. the jar ``org.jacoco.cli...jar``.
  2. the output ``Path`` of `jacocoRunJunit4`
  3. the compiled classes classpath as a Path
  4. the source file directory as a Path

  :param target: the directory where to place the coverage html files
  """
  pbexec("java",
         "-jar", str(target.dependencies[0].item),
         "report", str(target.dependencies[1].item),
         "--classfiles", str(target.dependencies[2].item),
         "--sourcefiles", str(target.dependencies[3].item),
         "--html", str(target.item)
         )
         
def classForPath(classpathEntry: Path, p: Path):
  """
  Convert the path ``p`` to a class name assuming it is some decendent of
  ``classpathEntry``. For example if the former is ``build/test`` and the
  latter is ``build/test/my/package/Dodo.class``, the result is
  ``my.package.Dodo``.
  """
  return ".".join(p.relative_to(classpathEntry).parts).replace(".class", "")
