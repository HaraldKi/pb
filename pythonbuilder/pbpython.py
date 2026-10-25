#!/usr/bin/env python3
"""Helpers to build python projects.

The functions provided typically use external programs from the python
ecosystem. If they are not installed, there will be errors like

  `[Errno 2] No such file or directory: 'foo' (ERROR)`

for functions using external program `foo`.

"""

from pathlib import Path

from .pbutil import touch
from .pythonbuilder import pbexec


## FIXME: allow command line arguments, as at least --quiet has no config setting
def doRuffCheck(target: Path, tomlFile: Path, *filesAndDirs: Path) -> None:
  """Runs `ruff check <https://docs.astral.sh/ruff/configuration/#full-command-line-interface>`_

  The function is intended to be used as the `cmd` parameter of a `Target`. The first
  dependency of the target must be a `ruff` configuration file. All other dependencies
  must be directory or file paths to be checked.

  The `target` itself should be a `Path` which is used to record that the
  target was created. See `pbutil.touch` for why this is useful.


  :param target: stamp file recording the fact when this function was actually invoked
  :param tomlFile: `ruff` configuration file
  :param filesAndDirs: to be checked by `ruff`

  """

  pbexec("ruff", "--config", tomlFile, "check", filesAndDirs)
  touch(target)


def doRuffFormat(target: Path, tomlFile: Path, *filesAndDirs: Path) -> None:
  """Runs `ruff format <https://docs.astral.sh/ruff/configuration/#full-command-line-interface>`_

  The function is intended to be used as the `cmd` parameter of a `Target`. The
  first dependency of the target must be a `ruff` configuration file. All other
  dependencies must be directory or file paths to be formatted.

  The `target` itself should be a `Path` which is used to record that the
  target was created. See `pbutil.touch` for why this is useful.

    **NOTE:** Use with care. If auto-formatting your code for the first time, be sure
    to commit any pending functional changes first to not mix them with mere
    formatting changes in one commit.

  :param target: stamp file recording the fact when this function was actually invoked
  :param tomlFile: `ruff` configuration file
  :param filesAndDirs: to be formatted by `ruff`

  """
  pbexec("ruff", "--config", tomlFile, "format", filesAndDirs)
  touch(target)


def doMypy(target: Path, mypyIni: Path, *filesAndDirs: Path) -> None:
  """Runs `mypy <https://www.mypy-lang.org/>`_

  The function is intended to be used as the `cmd` parameter of a `Target`. The first
  dependency of the target must be a `mypy` configuration file. All other dependencies
  must be directory or file paths to be checked.

  The `target` itself should be a `Path` which is used to record that the
  target was created. See `pbutil.touch` for why this is useful.

  :param target: stamp file recording the fact when this function was actually invoked
  :param mypyIni: `ruff` configuration file
  :param filesAndDirs: to be checked by `ruff`

  """
  pbexec("mypy", "--config-file", mypyIni, filesAndDirs)
  touch(target)
