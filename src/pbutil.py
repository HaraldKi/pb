"""
Provides a set of functions which I missed in more than one project build.  Most
functions are rather trivial to write but having to repeat them in each project
is a waste.

Using this module is completely optional, obviously.
"""

import datetime
import inspect
import shutil
from os import PathLike, fspath
from pathlib import Path
from typing import Any, Callable, Iterable, Iterator

import pythonbuilder as pb


class Paths(Iterable[Path], PathLike):
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
  parameter. Further, this is a restartable iterator, i.e. it is possibly to
  iterate more than once over the same instance.

  When used as a ``PathLike``, the `root` is returned.
  """

  @staticmethod
  def glob(path: Path | str, pattern: str) -> "Paths":
    """Creates a ``Paths`` object from a root path and an iterator derived straight from
    the ``glob`` pattern.
    """
    path = Path(path)
    return Paths(path, lambda p: p.glob(pattern), pattern)

  @staticmethod
  def rglob(path: Path | str, pattern: str) -> "Paths":
    """Creates a ``Paths`` object from a root path and an iterator derived straight from
    the ``rglob`` pattern.
    """
    path = Path(path)
    return Paths(path, lambda p: p.rglob(pattern), "r(" + pattern + ")")

  def __init__(
    self,
    root: Path | str,
    itSupplier: Callable[[Path], Iterable[Path]],
    itName: str | None = None,
  ):
    """Creates the ``Paths`` object with a root and an iterable which must
    deliver sub-paths of ``root``. Iterating over the ``Paths`` object will replay the
    iterable, but will fail if a path is not a sub-path of ``root``.

    :param root: a common ancestor of paths of the iterable
    :param itSupplier: sub-paths of ``root``
    :param itName: a nice name of the generated iterator to be used by ``__str__``
    """
    self.root: Path = Path(root)  # note: Path(path) works just fine
    """A common ancestor of the paths returned by iterating this object.
    """
    self._paths = itSupplier
    self._itName = itName if itName is not None else str(itSupplier)

  def __iter__(self) -> Iterator[Path]:
    """Replays the iterator provided to the constructor, failing if it returns a
    path which is not a sub-path of `root`."""
    for p in self._paths(self.root):
      if not p.is_relative_to(self.root):
        raise pb.BuildException(
          "botched iterable in Paths does not provide subdirectory of"
          + f" {self.root} but {p}"
        )
      yield p

  def __fspath__(self) -> str:
    """Calls  ``os.fspath`` on `root`."""
    return fspath(self.root)

  def __str__(self) -> str:
    """Readable short form for a ``Paths``"""
    return f"Paths[{self.root},{self._itName}]"

  def mappedTo(self, otherRoot: Path) -> "Paths":
    """Maps this object to a different common ancestor. All paths returned when
    iterating the new object will have the `root` replaced by ``otherRoot``.

    :param otherRoot: the new common ancestor of all paths
    :return: a ``Paths`` object with ``otherRoot`` as the `root`.
    """
    return Paths(
      otherRoot,
      RootPathMapper(self.root, self._paths),
      "<-(" + str(self.root) + "," + self._itName + ")",
    )


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
  targetPath.parent.mkdir(parents=True, exist_ok=True)
  targetPath.write_text(datetime.datetime.now().isoformat() + "\n")


class RootPathMapper:
  """A ``Callable[[Path], Iterator[Path]]`` which maps paths provided by another
  iterator to a new prefix, think ``["src/a.py", "src/b.py"]`` mapped to
  ``["dest/a.py", "dest/b.py"]``.
  """

  def __init__(self, oldRoot: Path, itGen: Callable[[Path], Iterable[Path]]):
    """Creates the mapper by its input.

    The second parameter, ``itGen`` is not just an iterator but a function to provide
    one so that our result can be iterated over more than once.

    :param oldRoot: a path prefix of all paths provided by ``itGen``
    :param itGen: given ``oldRoot``, must return an ``Iterator[Path]`` which
      may on only have paths prefixed with ``oldRoot``, the canonical example being
      ``lambda p: p.glob(...)``
    """
    self._oldRoot = oldRoot
    self._itGen = itGen

  def __call__(self, newRoot: Path) -> Iterator[Path]:
    """Maps the paths defined in the constructor to have a the new prefix path
    ``newRoot`` by replacing the ``oldRoot`` defined in the constructor.

    :param newRoot: new path prefix of the paths defined in the constructor
    :return: an iterator over the mapped paths, restartable
    """
    for p in self._itGen(self._oldRoot):
      try:
        tail = p.relative_to(self._oldRoot)
      except ValueError as _e:
        raise pb.BuildException(
          "cannot map %s as it does not have prefix %s" % (p, self._oldRoot)
        )
      yield newRoot / tail


def copyFiles(dest: Paths | Path, source: Paths) -> None:
  """Copies files from ``source`` to dest preserving the path segments below
  ``source.root``.

  :param dest: where to copy files to using ``dest.root`` if it is a ``Paths`` object.
  :param source: files to copy
  """
  if isinstance(dest, Paths):
    dest = dest.root
  for p in source:
    tail = p.relative_to(source.root)
    shutil.copyfile(p, dest / tail)
