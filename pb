#!/usr/bin/env python3

import os
import subprocess
import sys
import glob

sys.path += ["src"]
from pythonbuilder import Target, updateTargets, LOG, pbexec, toGraphviz

#LOG.setLevel("DEBUG")

## FIXME: use Path, not just str
pythonbuilder = Target[str]("src/pythonbuilder.py")
mavenrepo = Target[str]("src/mavenrepo.py")
pb = Target[str]("pb")
testSources = Target[str]("tests")

############################################################
def doMypy(target: Target[str]) -> None:
  files = glob.glob("src/*.py") + glob.glob("tests/*.py") + ["pb"]
  pbexec("mypy",
         "--cache-dir", os.path.join("build", "mypy_cache"),
         "--python-version", "3.10",
         files)

mypy = Target[str]("mypy", pythonbuilder, mavenrepo, pb, testSources,
                   state="fixed", cmd=doMypy)

############################################################
coverageFile = os.path.join("build", "coverage.data")
os.environ["COVERAGE_FILE"] = coverageFile
os.environ["TEST_MAVENREPO"] = "TRUE"

def runCoverage(target: Target):
  pbexec("python3-coverage", "run", "tests/alltests.py")

Target(coverageFile, testSources, pythonbuilder, mypy,
       alias="coverageRun", state="file", cmd=runCoverage)


############################################################
def coverageReport(target: Target):
  pbexec("python3-coverage", "html", "-d", str(target.item))

coverage = Target[str](os.path.join("build", "coverage"), "coverageRun",
                       alias="coverage", state="dir", cmd=coverageReport)


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

Target("./apidoc", pythonbuilder, mavenrepo, Target("doc-templates/extra.css"),
       state="dir", alias="apidoc", cmd=doApidoc)

############################################################
def graph(target: Target):
  result = toGraphviz()
  with open(str(target.item), "w", encoding="utf-8") as out:
    subprocess.run(["dot", "-Tsvg", "-Grankdir=LR"],
                   input=result, encoding="utf-8",
                   stdout=out)

Target("dependencies.svg", pb,
       state="file", alias="graph", cmd=graph)

############################################################

updateTargets(*(sys.argv[1:]))
