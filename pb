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

## FIXME: use Path, not just str
pythonbuilder = Target(srcDir / "pythonbuilder.py")
mavenrepo = Target(srcDir / "mavenrepo.py")
pb = Target(Path("pb"))
testSources = Target(Path("tests"))

############################################################
def doMypy(target: Target[str]) -> None:
  files = glob.glob("src/*.py") + glob.glob("tests/*.py") + ["pb"]
  pbexec("mypy",
         "--cache-dir", str(buildDir / "mypy_cache"),
         "--python-version", "3.10",
         files)

mypy = Target[str]("mypy", pythonbuilder, mavenrepo, pb, testSources,
                   state="fixed", cmd=doMypy)

############################################################
coverageFile = buildDir / "coverage.data"
environ["COVERAGE_FILE"] = str(coverageFile)
environ["TEST_MAVENREPO"] = "TRUE"

def runCoverage(target: Target):
  pbexec("python3-coverage", "run", "tests/alltests.py")

Target(coverageFile, testSources, pythonbuilder, mypy,
       name="coverageRun", state="file", cmd=runCoverage)


############################################################
def coverageReport(target: Target[Path]):
  pbexec("python3-coverage", "html", "-d", str(target.item))

coverage = Target(buildDir / "coverage", "coverageRun",
                  name="coverage", state="dir", cmd=coverageReport)

############################################################
def doApidoc(target: Target):
  pythonbuilder = str(target.dependencies[0].item)
  pbexec("pydoctor", "-q",
         "--docformat=restructuredtext",
         "--project-name=pythonbuilder",
         "--project-url=https://codeberg.org/harald/pythonbuilder",
         "--template-dir=doc-templates",
         "--html-output=apidoc",
           map(lambda t: str(t.item), target.dependencies))

Target(Path("doc-templates", "extra.css"), name="extra.css"),  
Target(Path("apidoc"), pythonbuilder, mavenrepo, "extra.css",
       state="dir", name="apidoc", cmd=doApidoc)

############################################################
registerDependencyGraphTarget(Path("dependencies.svg"), "graph", pb)

############################################################

# Run all targets which have no dependents to see if the
# full build works
Target("full", "coverage", "apidoc", "graph",
       state="new")

############################################################

updateTargets(*(sys.argv[1:]))
