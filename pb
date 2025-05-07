#!/usr/bin/env python3

import os
import subprocess
import sys
import glob

sys.path += ["src"]
from pythonbuilder import Target, updateTargets, LOG, pbexec, toGraphviz

#LOG.setLevel("DEBUG")

pythonbuilder = Target("src/pythonbuilder.py")
mavenrepo = Target("src/mavenrepo.py")
pb = Target("pb")
testSources = Target("tests")

############################################################
def doMypy(target: Target) -> None:
  files = glob.glob("src/*.py") + glob.glob("tests/*.py") + ["pb"]
  pbexec("mypy",
         "--cache-dir", os.path.join("build", "mypy_cache"),
         files)

mypy = Target("mypy", pythonbuilder, mavenrepo, pb, testSources,
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
  pbexec("python3-coverage", "html", "-d", target.name)

coverage = Target(os.path.join("build", "coverage"), "coverageRun",
                  alias="coverage", state="dir", cmd=coverageReport)


############################################################
def doApidoc(target: Target):
  pythonbuilder = target.dependencies[0].name
  pbexec("pydoctor", "-q",
         "--docformat=restructuredtext",
         "--project-name=pythonbuilder",
         "--project-url=https://codeberg.org/harald/pythonbuilder",
         "--template-dir=doc-templates",
         "--html-output=apidoc",
           map(lambda t: t.name, target.dependencies))

Target("./apidoc", pythonbuilder, mavenrepo, Target("doc-templates/extra.css"),
       state="dir", alias="apidoc", cmd=doApidoc)

############################################################
def graph(target: Target):
  result = toGraphviz()
  with open(target.name, "w", encoding="utf-8") as out:
    subprocess.run(["dot", "-Tsvg", "-Grankdir=LR"],
                   input=result, encoding="utf-8",
                   stdout=out)

Target("dependencies.svg", pb,
       state="file", alias="graph", cmd=graph)

############################################################

updateTargets(*(sys.argv[1:]))
