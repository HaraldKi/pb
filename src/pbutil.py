"""
Provides a set of functions which I missed in more than one project build.  Most
functions are rather trivial to write but having to repeat them in each project
is a waste.

Using this module is completely optional, obviously.
"""

import datetime
import inspect
from pathlib import Path
from typing import Any

import pythonbuilder as pb


def touch(targetPath: Path, *deps: Any) -> None:
  """A function intended to be used as the ``cmd`` parameter of a `Target` to
  write the current iso datetime into the ``targetPath``.

  Use this function for

  * a shortcut/alias target, for example ``allLibs``, which
    has no command to execute itself, but merely combines a list of targets into
    one to be conveniently invoked by the alias.
  * a target with no natural output, like a linter which is only run for its
    error output.

  The ``targetPath`` is merely a bookkeeping file which is freshly written
  if and only if any of the dependencies was re-created (or the file itself
  does not exist, of course), so it should be a file in the build output, say
  ``BUILD / "allLibs.done"`` where ``BUILD`` is your build output directory.

  :param targetPath: to write the current iso date/time into
  :param deps: the dependencies are ignored
  """
  frame = inspect.currentframe()
  me = "touch" if frame is None else frame.f_code.co_name
  pb.logcmd([me, str(targetPath)])
  targetPath.write_text(datetime.datetime.now().isoformat() + "\n")

