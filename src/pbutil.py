"""
Provides a set of functions which I missed in more than one project build.  Most
functions are rather trivial to write but having to repeat them in each project
is a waste.

Using this module is completely optional, obviously.
"""

import datetime
import inspect
from pathlib import Path
from typing import Any, Iterable, Iterator

import pythonbuilder as pb


class Paths(Iterable[Path]):
  """An iterable on files, much like ``Path().glob()`` but keeps the path from
  which the iteration starts.

  **NOTE**: Objects of this class can be conveniently used as the item of a `Target`
  when combined with `pythonbuilder.stateFileIteratorContent` as the ``state=``
  parameter.

  Many `Target`\s have a ``Path`` as their item and use ``state="dir"`` to obtain its
  state hash, which includes *all* contained files. If only a subset of files shall
  covered, use this class as a target's item.  You could use the iterator
  ``Path("src/python").rglob("*.py")`` directly as the item, but then you loose the
  information where the glob started, i.e. ``"src/python"``. This
  class also provides the directory from which the glob starts, as it will often be
  needed in the target's ``cmd``.

  **Hint:** to create a 1:1 file copy target look in particular at `mappedTo`.

  Objects of this class implement the ``Iterator[Path]`` protocol. The iterator
  basically replays the iterator provided to the constructor, except that it
  throws a `BuildException`, if an iterated path is not a sub-path of the root
  parameter.
  """

  @staticmethod
  def glob(path: Path | str, pattern: str) -> "Paths":
    """Creates a ``Paths`` object from a root path and an iterator derived straight from
    the ``glob`` pattern.
    """
    p = Path(path)
    return Paths(p, p.glob(pattern))

  @staticmethod
  def rglob(path: Path | str, pattern: str) -> "Paths":
    """Creates a ``Paths`` object from a root path and an iterator derived straight from
    the ``rglob`` pattern.
    """
    p = Path(path)
    return Paths(p, p.rglob(pattern))

  def __init__(self, root: Path | str, paths: Iterable[Path]):
    """Creates the ``Paths`` object with a root and an iterable which must
    deliver sub-paths of ``root``. Iterating over the ``Paths`` object will replay the
    iterable, but will fail if a path is not a sub-path of ``root``.

    :param root: a common ancestor of paths of the iterable
    :param paths: sub-paths of ``root``
    """
    self.root: Path = Path(root)  # note: Path(path) works just fine
    """A common ancestor of the paths returned by iterating this object.
    """
    self._paths = paths

  def __iter__(self) -> Iterator[Path]:
    """Replays the iterator provided to the constructor, failing if it returns a
    path which is not a sub-path of `root`."""
    for p in self._paths:
      if not p.is_relative_to(self.root):
        raise pb.BuildException(
          "botched iterable in Paths does not provide subdirectory of"
          + f" {self.root} but {p}"
        )
      yield p

  def mappedTo(self, otherRoot: Path) -> "Paths":
    """Maps this object to a different common ancestor. All paths returned when
    iterating the new object will have the `root` replaced by ``otherRoot``.

    :param otherRoot: the new common ancestor of all paths
    :return: a ``Paths`` object with ``otherRoot`` as the `root`.
    """
    return Paths(otherRoot, mappedPaths(otherRoot, self.root, self._paths))


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


def mappedPaths(
  target: Path, commonPrefix: Path, paths: Iterable[Path]
) -> Iterator[Path]:
  """Provides an iterable replacing a ``commonPrefix`` in the given ``paths`` by
  the ``target``. A `BuildException` is raised if a path does not have the common
  prefix.

  This functions can be used to create a `Target` which reflects exactly the files of
  a source directory structure in another directory, the simplest example being a
  file copy operation. Example:

  .. code-block:: python

    src = Target(Path("src").glob("*.py"), state=stateFileIteratorContent)
    out = Target(Path("build"),
                 state=lambda t: mappedPaths(t.item, Path("src"), t.dependencies[0].item))

  :param target: new prefix of all paths
  :param commonPrefix: to be replaced in the paths by `Target`
  :param paths: to be mapped

  :returns: a generator which yields one mapped path at a time

  **Note:** you may rather want to use `Paths.mappedTo` instead of calling this
  function directly.
  """
  for p in paths:
    try:
      tail = p.relative_to(commonPrefix)
    except ValueError as _e:
      raise pb.BuildException(
        "cannot map %s as it does not have prefix %s" % (p, commonPrefix)
      )
    yield target / tail
