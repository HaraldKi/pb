"""Until PEP-0844 gets implemented we use this.

Another option would be atpublic, but the dependency list shall be kept minimal.

And why not rely on prefixing non-public with "_"? Because I really dislike using
identifiers starting with an underscore on a regular basis.
"""

import inspect
from typing import Protocol, TypeVar, Union, cast


class HasName(Protocol):
  __name__: str


X = TypeVar("X", bound=Union[HasName, str])


def public(item: X) -> X:
  module = inspect.getmodule(inspect.stack()[1].frame)
  if module is None:
    raise Exception("cannot determine module of " + str(item))
  mdict = module.__dict__
  mdict.setdefault("__all__", [])
  all = cast(list[str], mdict.get("__all__"))
  name = item if isinstance(item, str) else item.__name__
  if name not in all:
    all.append(name)
  return item
