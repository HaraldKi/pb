#!/usr/bin/env python3

from os import environ
import subprocess
import sys
import glob
from pathlib import Path

sys.path += ["src"]
from pythonbuilder import (
  Target, updateTargets, LOG, pbexec, toGraphviz, registerDependencyGraphTarget
)

#LOG.setLevel("DEBUG")
srcDir = Path("src")
buildDir = Path("build")

pythonbuilder = Target(srcDir / "pythonbuilder.py")
mavenrepo = Target(srcDir / "mavenrepo.py")
java = Target(srcDir / "java.py")
pb = Target(Path("pb"))
testSources = Target(Path("tests"))

############################################################
def doMypy(_target: str, testSrcDir: Path, *files: Path) -> None:
  allFiles = list(testSrcDir.glob("*.py")) + [*files]
  pbexec("mypy",
         "--cache-dir", str(buildDir / "mypy_cache"),
         "--python-version", "3.10",
         "--soft-error-limit", "5",
         "--disallow-untyped-defs",
         "--warn-unreachable",
         "--warn-return-any",
         allFiles)

mypy = Target[str]("mypy", testSources,pythonbuilder, mavenrepo, java, pb,
                   state="fixed", cmd=doMypy)

############################################################
coverageFile = buildDir / "coverage.data"
environ["COVERAGE_FILE"] = str(coverageFile)
environ["TEST_MAVENREPO"] = "TRUE"

def doRunCoverage(_coverageFile: Path, testSources: Path, *_unused: Path) -> None:
  pbexec("python3-coverage", "run", testSources / "alltests.py")

test = Target(coverageFile, testSources, pythonbuilder, mypy,
              name="test", state="file", cmd=doRunCoverage)


############################################################
def coverageReport(coverageOut: Path, _coverageFile: Path) -> None:
  pbexec("python3-coverage", "html", "-d", coverageOut)

coverage = Target(buildDir / "coverage",
                  test,
                  name="coverage", state="dir", cmd=coverageReport)

############################################################
def doApidoc(docPath: Path, _unused: Path, *pyfiles: Path) -> None:
  pbexec("pydoctor", "-q",
         "--docformat=restructuredtext",
         "--project-name=pythonbuilder",
         "--project-url=https://codeberg.org/harald/pythonbuilder",
         "--template-dir=doc-templates",
         "--html-output=" + str(docPath),
         pyfiles)

extraCss = Target(Path("doc-templates", "extra.css"), name="extraCss")  
apidoc = Target(Path("apidoc"),
                extraCss, pythonbuilder, mavenrepo, java,
                state="dir", name="apidoc", cmd=doApidoc)

############################################################
graph = registerDependencyGraphTarget(Path("dependencies.svg"), "graph", pb)

############################################################

# Run all targets which have no dependents to see if the
# full build works
Target("full", coverage, apidoc, graph,
       state="new")

############################################################

updateTargets(*(sys.argv[1:]))
