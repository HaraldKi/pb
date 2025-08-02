#!/usr/bin/env python3
"""Helpers to build python projects with.

The functions provided typically use external programs from the python ecosystem. If
they are not installed, there will be errors like

  ``[Errno 2] No such file or directory: 'foo' (ERROR)``

for functions using external program ``foo``.
"""

from pathlib import Path

from pbutil import touch
from pythonbuilder import pbexec


def doRuffCheck(target: Path, tomlFile: Path, *filesAndDirs: Path) -> None:
  """Runs `ruff check <https://github.com/astral-sh/ruff?tab=readme-ov-file#ruff>`_

  The function is intended to be used as the ``cmd`` parameter of a `Target`. The
  first dependency of the target must be a ``ruff`` configuration file, all other
  dependencies must be directory or file path to be checked by ``ruff``.

  The ``target`` itselfs should be a ``Path`` which is used to record a that the
  target was created. See `pbutil.touch`. for why this is useful.

  :param target: stamp file recording the fact when this function was actually invoked
  :param tomlFile: ``ruff`` configuration file
  :param filesAndDirs: to be checked by ``ruff``
  """
  pbexec("ruff", "--config", tomlFile, "check", filesAndDirs)
  touch(target)


def doRuffFormat(target: Path, tomlFile: Path, *filesAndDirs: Path) -> None:
  """Runs `ruff format <https://github.com/astral-sh/ruff?tab=readme-ov-file#ruff>`_

  The function is intended to be used as the ``cmd`` parameter of a `Target`. The
  first dependency of the target must be a ``ruff`` configuration file, all other
  dependencies must be directory or file path to be checked by ``ruff``.

  The ``target`` itselfs should be a ``Path`` which is used to record a that the
  target was created. See `pbutil.touch`. for why this is useful.

    **NOTE:** Use with care, typically only after a commit of your source code to be
    sure any weirdness arising from the formatting can be easily undone.
  
  :param target: stamp file recording the fact when this function was actually invoked
  :param tomlFile: ``ruff`` configuration file
  :param filesAndDirs: to be formatted by ``ruff``

  """
  pbexec("ruff", "--config", tomlFile, "format", filesAndDirs)
  touch(target)


def doMypy(target: Path, mypyIni: Path, *filesAndDirs: Path) -> None:
  """Runs `mypy <https://www.mypy-lang.org/>`_

  The function is intended to be used as the ``cmd`` parameter of a `Target`. The first
  dependency of the target must be a `mypy configuration file
  <https://mypy.readthedocs.io/en/stable/config_file.html>`_, all other dependencies
  must be directory or file path to be checked.

  The ``target`` itselfs should be a ``Path`` which is used to record a that the
  target was created. See `pbutil.touch`. for why this is useful.

  :param target: stamp file recording the fact when this function was actually invoked
  :param mypyIni: ``ruff`` configuration file
  :param filesAndDirs: to be checked by ``ruff``

  """
  pbexec("mypy", "--config-file", mypyIni, filesAndDirs)
  touch(target)
