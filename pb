#!/usr/bin/env -S PYTHONPYCACHEPREFIX=build/pyc python3

import os
import subprocess
import sys
import glob

from pythonbuilder import Target, updateTargets, LOG, pbexec, toGraphviz

#LOG.setLevel("DEBUG")

pythonbuilder = Target("pythonbuilder.py")
mavenrepo = Target("mavenrepo.py")
pb = Target("pb")
testSources = Target("tests")

############################################################
def doMypy(target: Target) -> None:
  files = glob.glob("*.py") + glob.glob("tests/*.py") + ["pb"]
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
 # first = True
 #  for testpy in glob.glob(target.dependencies[0].name + "/test_*.py"):
 #    append = ["-a"]
 #    if first:
 #      append += []
 #    first = False
 #    pbexec("python3-coverage", "run", append, testpy)

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
  pbexec("pydoctor", "-q", "--docformat=restructuredtext",
         "--project-name=pythonbuilder",
         "--html-output=apidoc",
           map(lambda t: t.name, target.dependencies))
  # pbexec("pdoc3", "--html", "-f", "-o", target.name,
  #        map(lambda t: t.name, target.dependencies))

  # see https://github.com/pdoc3/pdoc/issues/101#issuecomment-1563008560
  # from pdoc import import_module, _render_template # type: ignore
  # import inspect

  # modules = map(lambda m: (m.__name__ + ".html", inspect.getdoc(m)),
  #               [import_module(m, reload=True)
  #                for m in map(lambda t: t.name, target.dependencies)])

  # indexHtml = os.path.join(target.name, "index.html")
  # with open(indexHtml, "w", encoding="utf-8") as index:
  #   index.write(_render_template("/html.mako",
  #                               modules=modules))

Target("./apidoc", pythonbuilder, mavenrepo,
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
