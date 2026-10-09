#!/usr/bin/env python3

import re
import sys
from os import environ, getenv
from pathlib import Path

from pythonbuilder import (
  BuildException,
  Target,
  pbexec,
  pbutil,
  registerDependencyGraphTarget,
)
from pythonbuilder.pbpython import doMypy, doRuffCheck, doRuffFormat

OURNAME = "pythonbuilder"

srcDir = Path("pythonbuilder")
testsDir = Path("tests")
buildDir = Path("build")

pb = Target(Path("pb"))
pySources = Target(srcDir)
testSources = Target(testsDir)
example = Target(Path("example"))

############################################################

mypy = Target(
  buildDir / "mypy.stamp",
  Target(Path("config", "mypy.ini")),
  pb,
  pySources,
  testSources,
  example,
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
  example,
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
  example,
  name="pyformat",
  state="file",
  cmd=doRuffFormat,
)

############################################################
coverageFile = buildDir / "coverage.data"
environ["COVERAGE_FILE"] = str(coverageFile)


def doRunCoverage(_coverageFile: Path, testSources: Path, *_unused: Path) -> None:
  pbexec("python3-coverage", "run", testSources / "alltests.py")


test = Target(
  coverageFile,
  testSources,
  pySources,
  mypy,
  ruff,
  name="test",
  state="file",
  cmd=doRunCoverage,
)


############################################################
def coverageReport(coverageOut: Path, _coverageFile: Path) -> None:
  pbexec(
    "python3-coverage",
    "html",
    "-d",
    coverageOut,
    srcDir.glob("*.py"),
    testsDir.glob("*.py"),
  )


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
    pypath.name,
  )


docTemplates = Target(Path("doc-templates"), name="docTemplates")
docout = getenv("DOCUMENTATION_OUT")
APIDOC_OUT = Path(docout, OURNAME) if docout is not None else Path("apidoc")

apidoc = Target(
  APIDOC_OUT, docTemplates, pySources, state="dir", name="apidoc", cmd=doApidoc
)

############################################################
def doReadme(readmeMd: Path, example: Path) -> None:
  readme = readmeMd.read_text(encoding="UTF-8")
  insert = example.read_text(encoding="UTF-8")
  tmpl = "<!-- inlined file: example, update with 'pb readme' -->\n```python\n%s```\n<!-- inlined file end -->"
  text = re.sub("<!-- inlined file:.*inlined file end -->", (tmpl % ""), readme, flags=re.DOTALL)
  if text == readme:
    raise BuildException(f"cannot find pattern to insert file '{example}' into '{readmeMd}'")
  text = re.sub("<!-- inlined file:.*inlined file end -->", (tmpl % insert), readme, flags=re.DOTALL)
  readmeMd.write_text(text, encoding="UTF-8")

readmemd = Target(Path("README.md"), example, name="readme", cmd=doReadme)

############################################################
graph = registerDependencyGraphTarget(Path("dependencies.svg"), "graph", pb)

############################################################

# Run all targets which have no dependents to see if the
# full build works
Target("full", coverage, apidoc, graph, readmemd, state="new")

############################################################

if __name__ == "__main__":
  if not pbutil.main(*sys.argv[1:]):
    sys.exit(1)
