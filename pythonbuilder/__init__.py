"""A library for writing build scripts.

Where a **build script** is really just a python script making use of the API provided
by this library.

See `pythonbuilder.pythonbuilder` to get started and see the main API provided.

**NOTE**: All exported names of `.pythonbuilder` are re-exported here to allow imports
like

```python
from pythonbuilder import task, target, ...
```

"""

from .pythonbuilder import *  # noqa: F403



