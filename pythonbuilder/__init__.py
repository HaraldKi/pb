"""A library to help writing build scripts.

Where "build script" denotes any odd script which also has functions to run only if they
can be excpected to produce a different result.

**NOTE**: All identifiers of module ``pythonbuilder`` are directly available as part of
the package itself, so you may write

.. code-block:: python

  from pythonbuilder import Target

instead of ``from pythonbuilder.pythonbuilder``.

"""

from .pythonbuilder import *  # noqa: F403

