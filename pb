#!/usr/bin/env python3

import os
import re
import sys
from pathlib import Path

import pythonbuilder.pbutil as pbutil

# from typing import reveal_type
from pythonbuilder import (
  BuildException,
  Target,
  inputTask,
  internalTask,
  logcmd,
  main,
  pbexec,
  registerDependencyGraphTask,
  target,
  task,
)
from pythonbuilder.pbpython import doMypy

OURNAME = "pythonbuilder"
BUILD = Path("build")


testSources = inputTask(Path("tests"))
pySources = inputTask(Path("pythonbuilder"))
pbFile = inputTask(Path("pb"))
exampleFile = inputTask(Path("example"))
mypyConfig = inputTask(Path("config", "mypy.ini"))
docTemplates = inputTask(Path("doc-templates"))
logo = inputTask(Path("config", "pythonbuilder-logo.png"), name="logo")


@task
def mypy() -> Target[Path]:
  config = mypyConfig()
  src = pySources()
  testSrc = testSources()
  pb = pbFile()
  example = exampleFile()

  t = target(BUILD / "mypy.done", config, src, testSrc, pb, example, state="file")
  if t.outdated:
    doMypy(t.item, config.item, src.item, testSrc.item, pb.item, example.item)
  return t


@task
def test() -> Target[Path]:
  tests = testSources()
  t = target(BUILD / "coverage.data", tests, pySources(), state="file")
  if t.outdated:
    pbexec(
      "python3-coverage",
      "run",
      "--branch",
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


def doApidoc(serve: bool) -> Target[Path]:
  tLogo = logo()
  templates = docTemplates()
  src = pySources()

  outDir = os.getenv("DOCUMENTATION_OUT")
  docOut = Path(outDir, OURNAME) if outDir is not None else BUILD / "apidoc"
  t = target(docOut, templates, src, tLogo, state="new" if serve else "dir")
  if t.outdated:
    pbutil.copyFile(docOut / tLogo.item.name, tLogo.item)
    outParam = ["--no-browser"] if serve else ["-o", docOut, "--logo", tLogo.item.name]
    try:
      pbexec(
        "pdoc",
        "--no-include-undocumented",
        *outParam,
        "--docformat",
        "markdown",
        src.item,
      )
    except KeyboardInterrupt:
      if serve:
        print("server stopped")
      else:
        raise
  return t


@task
def docshow() -> Target[Path]:
  return doApidoc(True)


@task
def apidoc() -> Target[Path]:
  return doApidoc(False)


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


graph = registerDependencyGraphTask(Path("dependencies.svg"), pbFile)


@task
def full() -> Target[str]:
  return target("full", graph(), coverage(), apidoc(), readme(), state="new")


sys.exit(main(sys.argv[1:]))
