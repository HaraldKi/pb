#!/usr/bin/env python3
import os
import subprocess
import sys
import glob

from pythonbuilder import Target, updateTargets, LOG, pbexec, toGraphviz

#LOG.setLevel("DEBUG")

pythonbuilder = Target("pythonbuilder.py")
pb = Target("pb")
testSources = Target("tests")

############################################################
def doMypy(target: Target) -> None:
  pbexec("mypy", map(lambda d: d.name, target.dependencies))

Target("mypy", pythonbuilder, pb,
       state="fixed", cmd=doMypy)

############################################################
coverageFile = os.path.join("build", "coverage.data")
os.environ["COVERAGE_FILE"] = coverageFile
def runCoverage(target: Target):
  first = True
  for testpy in glob.glob(target.dependencies[0].name + "/test_*.py"):
    append = ["-a"]
    if first:
      append += []
    first = False
    pbexec("python3-coverage", "run", append, testpy)

Target(coverageFile, testSources, pythonbuilder, "mypy",
       alias="coverageRun", state="file", cmd=runCoverage)


############################################################
def coverageReport(target: Target):
  pbexec("python3-coverage", "html", "-d", target.name)

coverage = Target(os.path.join("build", "coverage"), "coverageRun",
                  alias="coverage", state="dir", cmd=coverageReport)


############################################################
def doApidoc(target: Target):
  pythonbuilder = target.dependencies[0].name
  pbexec("pdoc3", "--html", "-f", "-o", target.name, pythonbuilder)

Target("./apidoc", pythonbuilder,
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
updateTargets(sys.argv[1])
