#!/usr/bin/env python3

import os
import re
import subprocess
import sys
from pathlib import Path

# from typing import reveal_type
from pythonbuilder import BuildException, Target, logcmd, pbexec
from pythonbuilder.tasks import internalTask, main, target, task, toGraphviz

OURNAME = "pythonbuilder"
BUILD = Path("build")


@internalTask
def testSources() -> Target[Path]:
  return target(Path("tests"))


@internalTask
def pySources() -> Target[Path]:
  return target(Path("pythonbuilder"))


@task
def test() -> Target[Path]:
  tests = testSources()
  t = target(BUILD / "coverage.data", tests, pySources(), state="file")
  if t.outdated:
    pbexec(
      "python3-coverage",
      "run",
      "--data-file=" + str(t.item),
      tests.item / "alltests.py",
    )
  return t


@task
def coverage() -> Target[Path]:
  tests = testSources()
  src = pySources()
  coverageData = test()
  t = target(BUILD / "coverage", coverageData, src, tests, state="dir")
  if t.outdated:
    pbexec(
      "python3-coverage",
      "html",
      "--data-file=" + str(coverageData.item),
      "-d",
      t.item,
      src.item.glob("*.py"),
      tests.item.glob("*.py"),
    )
  return t


@internalTask
def docTemplates() -> Target[Path]:
  return target(Path("doc-templates"))


@task
def apidoc() -> Target[Path]:
  outDir = os.getenv("DOCUMENTATION_OUT")
  docOut = Path(outDir, OURNAME) if outDir is not None else BUILD / "apidoc"
  templates = docTemplates()
  src = pySources()
  t = target(docOut, templates, src, state="dir")
  if t.outdated:
    pbexec("pdoc", "-o", docOut, "-d", "markdown", src.item)
  return t


@internalTask
def readmeMd() -> Target[Path]:
  return target(Path("README.md"))


@internalTask
def exampleCode() -> Target[Path]:
  return target(Path("example"))


@task
def readme() -> Target[Path]:
  fileIn = readmeMd()
  example = exampleCode()
  t = target(fileIn.item, fileIn, example)
  if not t.outdated:
    return t
  readme = fileIn.item.read_text(encoding="UTF-8")
  insert = example.item.read_text(encoding="UTF-8")
  tmpl = "<!-- inlined file: example, update with 'pb readme' -->\n```python\n%s```\n<!-- inlined file end -->"
  text = re.sub(
    "<!-- inlined file:.*inlined file end -->", (tmpl % ""), readme, flags=re.DOTALL
  )
  if text == readme:
    raise BuildException(
      f"cannot find pattern to insert file '{example}' into '{readmeMd}'"
    )
  text = re.sub(
    "<!-- inlined file:.*inlined file end -->", (tmpl % insert), readme, flags=re.DOTALL
  )
  t.item.write_text(text, encoding="UTF-8")
  logcmd(["updated", str(t.item)])
  return t


@internalTask
def buildscript() -> Target[Path]:
  return target(Path("pb"))


@task
def graph() -> Target[Path]:
  outName = "dependencies.svg"
  t = target(Path(outName), buildscript(), state="file")
  if not t.outdated:
    return t
  dot = toGraphviz()
  cmd = ["dot", "-Tsvg", "-Grankdir=LR", "-o" + outName]
  logcmd(cmd)
  subprocess.run(cmd, input=dot, encoding="utf8").check_returncode()
  return t


@task
def full() -> Target[None]:
  return target("full", graph(), coverage(), apidoc(), readme(), state="new")


if not main(sys.argv[1:]):
  sys.exit(1)
