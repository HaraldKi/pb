"""
Provides a set of functions which I missed in more than one project build.  Most
functions are rather trivial to write but having to repeat them in each project
is a waste.

Using this module is completely optional, obviously.
"""

import datetime
import functools
import inspect
import os
import re
import shutil
from pathlib import Path
from typing import Any, Callable, Generic, Iterable, Iterator, TypeVar

from . import pythonbuilder as pb
from ._public import public

T = TypeVar("T")


@public
class Value(pb.StateProvider, Generic[T]):
  """An in-memory storage cell with a name, a value and a state provider.

  Target items are nearly never a value to be created in itself, but rather the
  name of an item to be updated, with the `Path` being the canonical example. The
  `Value` class provides the same for in memory values."""

  def __init__(self, name: str, value: T, state: Callable[[T], str] = repr) -> None:
    self.name = name
    self.value = value
    self.state = repr

  def __str__(self) -> str:
    return self.name

  def provideState(self) -> str:
    return self.state(self.value)


@public
class Environ(pb.StateProvider):
  def __init__(self, name: str) -> None:
    self.name = name

  def provideState(self) -> str:
    value = os.environ.get(self.name, None)
    return "None" if value is None else "!" + value


@public
class Paths(Iterable[Path], os.PathLike, pb.StateProvider):
  """An iterable on files, much like ``Path().glob()`` but keeps the path from
  which the iteration starts.

  **NOTE**: Objects of this class can be conveniently used as the item of a `Target`
  when combined with `pythonbuilder.stateFileIteratorContent` as the ``state=``
  parameter.

  Many targets have a ``Path`` as their item and use ``state="dir"`` to obtain its
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

  When used as a ``os.PathLike``, the `root` is returned.
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

  @staticmethod
  def filtered(
    path: Path,
    fileOK: Callable[[Path], bool] = lambda p: True,
    dirOK: Callable[[Path], bool] = lambda p: True,
    dirs: bool = False,
    itName: str = "filtered",
  ) -> "Paths":
    """Creates a ``Paths`` object with an iterable created by calling `filterPath`."""
    return Paths(path, lambda p: filterPath(p, fileOK, dirOK, dirs), itName)

  @staticmethod
  def reFiltered(
    path: Path,
    fileI: str = ".",
    *,
    fileX: str | None = None,
    dirI: str = ".",
    dirX: str | None = None,
    dirs: bool = False,
  ) -> "Paths":
    """Creates a ``Paths`` object with an iterable created by calling `filterPathRe`."""
    itName = "✔(" + fileI + ")" if fileI != "." else ""
    itName += "✘(" + fileX + ")" if fileX is not None else ""
    itName += "👍(" + dirI + ")" if dirI != "." else ""
    itName += "👎(" + dirX + ")" if dirX is not None else ""
    """Creates a ``Paths`` object with an iterable created by calling `filterPathRe`."""
    return Paths(
      path, lambda p: filterPathRe(p, fileI, fileX, dirI, dirX, dirs), itName
    )

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
    return os.fspath(self.root)

  def __str__(self) -> str:
    """Readable short form for a ``Paths``"""
    return f"Paths[{self.root},{self._itName}]"

  # FIXME: with Python 3.12 start using @override
  def provideState(self) -> str:
    """Provides the state of the files such that a ``Paths`` object may be used with no
    ``state`` provided when used as a `Target`'s item. The function
    `stateFileIteratorContent` is used to compute the state.
    """
    return pb.stateFileIteratorContent(self)

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

  def withFilter(
    self,
    relativePathFilter: Callable[[Path], Path | None],
    filterName: str | None = None,
  ) -> "Paths":
    """Returns an instance which maps and filters the relative paths of this object.

    Example:

    .. code-block:: python

      allSrc = Paths.rglob(Path("src", "app"), "*")
      nohtml = allSrc.withFilter(lambda p: None if p.suffix == ".html" else p, "nohtml")

    :param relativePathFilter: a function to map paths relative to our root to a changed
      path, the same path or ``None``. A returned path must be a relative path,
      otherwise a `BuildException` is raised. If ``None`` is returned, the input
      path is filtered out.

    :param filterName: for a better ``str()`` output of the filter

    """
    name = filterName if filterName is not None else str(relativePathFilter)
    return Paths(
      self.root,
      functools.partial(self._filter, relativePathFilter),
      self._itName + "|" + name,
    )

  def _filter(
    self, relativePathFilter: Callable[[Path], Path | None], root: Path
  ) -> Iterable[Path]:
    for p in self._paths(self.root):
      relative = p.relative_to(self.root)
      other = relativePathFilter(relative)
      if other is None:
        continue
      if other.is_absolute():
        raise pb.BuildException(
          f"botched filter maps '{p}' to absolute path '{other}'"
          + " but must return None or a relative path"
        )
      yield root / other


def filterPath(
  root: Path,
  fileOK: Callable[[Path], bool] = lambda p: True,
  dirOK: Callable[[Path], bool] = lambda p: True,
  dirs: bool = False,
) -> Iterable[Path]:
  """An iterable producing file and, possibly, directory paths recursively contained in
  the ``root`` path. Symlinks are never followed but are handled as regular
  files.

  ``fileOK`` decides which files to include in the output.

  ``dirOK`` decides which directories to traverse. This can avoid unnecessary traversal
  of subdirectories and may keep file tests simpler. For example if ``dirOK`` is only
  true for a subdirectory "src/module1", getting python files from this subdirectory
  only can just check if a path ends with ``".py"``. Without a ``dirOK``, the prefix
  ``"src/module1/"`` would also have to be checked for each file and, in addition, other
  subdirectories would be traversed unneccesarily.

  The path parameter to both, ``fileOK`` and ``dirOK``, is relative to the ``root``, so
  to include a directory ``a`` below any root, it suffices to use ``dirOK=lambda p:
  p.parts[0]=="a"``.

  Directory paths will only show up in the result if ``dirs=True`` **and** if they
  are traversed.

  :param root: directory to traverse
  :param fileOK: function to test if a file shall be in the output
  :param dirOK: function to test if a directory shall be traversed at all
  :param dirs: if ``True``, provides traversed directory paths in the output
  :return: paths of files and directories

  """
  work: list[Path] = [root]
  while len(work) > 0:
    for p in work.pop().glob("*"):
      relativeP = p.relative_to(root)
      if p.is_dir():
        if dirOK(relativeP):
          work.append(p)
          if dirs:
            yield p
      else:
        if fileOK(relativeP):
          yield p


def filterPathRe(
  root: Path,
  fileI: str = ".",
  fileX: str | None = None,
  dirI: str = ".",
  dirX: str | None = None,
  dirs: bool = False,
) -> Iterable[Path]:
  """An iterable producing file and, possibly, directory paths recursively contained in
  the ``root`` path. This is a wrapper around `filterPath` which creates its ``fileOK``
  and ``dirOK`` from the provided regular expressions as follows:

  Both parameters for `filterPath` are constructed such that the exclude pattern beats
  the include pattern. All patterns are **searched** in paths relative to ``root`` after
  conversion with ``Path.as_posix()``, so paths directly in root will have no ``'/'``
  inside while deeper nested paths will look like ``"a/b/c.d"``

  For example to only include files in subdirectories of ``root`` use ``fileI="/"`` as
  it requires that the path contains at least one ``'/'``, like ``module/some.py``.

  Use ``dirI`` and ``dirX`` to prevent traversal of subdirectories which have not files
  to include as described for `filterPath`.

  :param root: directory to traverse
  :param fileI: regex to match against file paths for inclusion
  :param fileX: regex to match against file paths for exclusion, overrules ``fileI``
  :param dirI: regex to match against directory paths for traversal
  :param dirX: regex to match against directory paths to skip, overrules ``dirI``
  :param dirs: if ``True``, provides traversed directory paths in the output
  :return: paths of files and directories

  """
  dirDescent = re.compile(dirI)
  dirAvoid = None if dirX is None else re.compile(dirX)
  fileInc = re.compile(fileI)
  fileExc = None if fileX is None else re.compile(fileX)

  def include(inc: re.Pattern[str], exc: re.Pattern[str] | None, p: Path) -> bool:
    pstr = p.as_posix()
    return inc.search(pstr) is not None and (exc is None or not exc.search(pstr))

  return filterPath(
    root,
    functools.partial(include, fileInc, fileExc),
    functools.partial(include, dirDescent, dirAvoid),
    dirs,
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


def copyFile(dest: os.PathLike, source: os.PathLike) -> None:
  """A wrapper around ``shutil.copy`` to be used as a command in a target.

  It creates the destination directory, if necessary, swaps the arguments to fit
  ``shutil.copy``, logs the command."""

  destPath = Path(dest)
  destPath.parent.mkdir(0o754, parents=True, exist_ok=True)
  shutil.copy(source, dest)
  pb.logcmd(["copyFile", str(dest), "<-", str(source)])


def copyFiles(dest: Paths | Path, source: Paths | Path) -> None:
  """Copies files from ``source`` to dest preserving the path segments below
  ``source.root``. If the source contains directory paths, these are ignored. If
  the source is a ``Path``, then ``Paths.rglob(source, "*")`` is used.

  :param dest: where to copy files to using ``dest.root`` if it is a ``Paths`` object.
  :param source: files to copy, if a ``Path`` it must be a directory.
  """
  if isinstance(dest, Paths):
    dest = dest.root
  if isinstance(source, Path):
    if not source.is_dir():
      raise pb.BuildException("source must be a directory but is " + str(source))
    source = Paths.rglob(source, "*")

  for p in source:
    if p.is_dir():
      continue
    tail = p.relative_to(source.root)
    out = dest / tail
    out.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(p, dest / tail)
  pb.logcmd(["copyFiles", str(dest), "<-", str(source)])
