"""A library for writing build scripts.

Where *build script* denotes any odd python script which uses the functionality provided
here.


### Task based build script

The **modern** approach has a more readable structure and you should go right into
`pythonbuilder.tasks` to learn how to write a **build task**.

### Target based build script

The **older** approach works slightly different with
`pythonbuilder.pythonbuilder.Target`. It defines a target item, dependencies and a
command to update the target item.

"""

from .pythonbuilder import *  # noqa: F403
