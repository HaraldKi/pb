#!/usr/bin/env python3
import os
import subprocess
import sys
import glob
from pythonbuilder import Target, updateTargets, LOG, pbexec

#LOG.setLevel("DEBUG")

pb = Target("pythonbuilder.py")
testSources = Target("tests")

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

Target(coverageFile, testSources, pb,
       alias="coverageRun", state="file", cmd=runCoverage)


def coverageReport(target: Target):
  pbexec("python3-coverage", "html", "-d", target.name)

coverage = Target(os.path.join("build", "coverage"), "coverageRun",
                  alias="coverage", state="dir", cmd=coverageReport)


updateTargets(sys.argv[1])
