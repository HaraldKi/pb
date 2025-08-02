#!/usr/bin/env python3

import sys
from os import environ
from pathlib import Path

sys.path += ["src"]
from pbpython import doMypy, doRuffCheck, doRuffFormat
from pythonbuilder import (
  LOG,
  Target,
  pbexec,
  registerDependencyGraphTarget,
  updateTargets,
)

LOG.setLevel("INFO")
srcDir = Path("src")
buildDir = Path("build")

# pythonbuilder = Target(srcDir / "pythonbuilder.py")
# mavenrepo = Target(srcDir / "mavenrepo.py")
# java = Target(srcDir / "java.py")
# pbutil = Target(srcDir / "pbutil.py")

pb = Target(Path("pb"))
pySources = Target(Path("src"))
testSources = Target(Path("tests"))

############################################################

mypy = Target(
  buildDir / "mypy.stamp",
  Target(Path("config", "mypy.ini")),
  pb,
  pySources,
  testSources,
  name="mypy",
  state="file",
  cmd=doMypy,
)

############################################################
ruffConfig = Target(Path("config", "ruff.toml"))

ruff = Target(
  buildDir / "ruff.stamp",
  ruffConfig,
  pb,
  pySources,
  testSources,
  name="ruff",
  state="file",
  cmd=doRuffCheck,
)

############################################################
pyformat = Target(
  buildDir / "ruffFormat.stamp",
  ruffConfig,
  pb,
  pySources,
  testSources,
  name="pyformat",
  state="file",
  cmd=doRuffFormat,
)

############################################################
coverageFile = buildDir / "coverage.data"
environ["COVERAGE_FILE"] = str(coverageFile)
environ["TEST_MAVENREPO"] = "TRUE"


def doRunCoverage(_coverageFile: Path, testSources: Path, *_unused: Path) -> None:
  pbexec("python3-coverage", "run", testSources / "alltests.py")


test = Target(
  coverageFile,
  testSources,
  pySources,
  ruff,
  mypy,
  name="test",
  state="file",
  cmd=doRunCoverage,
)


############################################################
def coverageReport(coverageOut: Path, _coverageFile: Path) -> None:
  pbexec("python3-coverage", "html", "-d", coverageOut)


coverage = Target(
  buildDir / "coverage", test, name="coverage", state="dir", cmd=coverageReport
)


############################################################
def doApidoc(docPath: Path, docTemplates: Path, pypath: Path) -> None:
  pbexec(
    "pydoctor",
    "-q",
    "--docformat=restructuredtext",
    "--project-name=pythonbuilder",
    "--project-url=https://codeberg.org/harald/pythonbuilder",
    "--template-dir=" + str(docTemplates),
    "--html-output=" + str(docPath),
    pypath.glob("*.py"),
  )


docTemplates = Target(Path("doc-templates"), name="docTemplates")
apidoc = Target(
  Path("apidoc"), docTemplates, pySources, state="dir", name="apidoc", cmd=doApidoc
)

############################################################
graph = registerDependencyGraphTarget(Path("dependencies.svg"), "graph", pb)

############################################################

# Run all targets which have no dependents to see if the
# full build works
Target("full", coverage, apidoc, graph, state="new")

############################################################

updateTargets(*(sys.argv[1:]))
