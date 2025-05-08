#  <img src="apidoc/pythonbuilder-logo.png" width="60"> pythonbuilder &mdash; pythononic project builder

<!-- markdown-toc start - Don't edit this section. Run M-x markdown-toc-refresh-toc -->
**Table of Contents**

  - [Getting Started](#getting-started)
  - [Functional Overview](#functional-overview)
  - [Example](#example)

<!-- markdown-toc end -->

Quick link: [api documentation](https://harald.codeberg.page/pythonbuilder/@main/apidoc/index.html).

See also: [BuildMachine](https://codeberg.org/harald/BuildMachine),
[bashbuilder](https://codeberg.org/harald/bashbuilder)

## Getting Started

Copy `src/pythonbuilder.py` and the other `*.py` files to some place you like. The
suggested place is the subdirectory `./pythonbuilder` in your project directory.

Write a build script in Python, called `pb` (for example), which has the following
structure:
```pyton
#!/usr/bin/env python3
import sys
sys.path += ["pythonbuilder"]
from pythonbuilder import Target, updateTargets, LOG, pbexec, toGraphviz

... multiple calls to the Target constructor
... definition of functions to create your targets ...

updateTargets(*(sys.argv[1:]))
```

Run `./pb target` to build the given target according to the recipe described in
your build script, where target is a name of one of the `Target` objects you created.

A more extensive example, is the [our build script](./bp) or see
[below](#example).

## Functional Overview
A **target** is something you want to build. Usually it is a file or a the
contents of a whole directory. To build `target1` it may be necessary to build
`targetA` and `targetB` first. Then those two are called **dependencies** of
`target1`.

Of course a dependency can have its own dependencies too and different targets
may have the same dependencies. The result is a directed graph without
cycles. If a target directly or indirectly has itself as a dependency, this is
flagged as an error.

To create a target, it has an associated **command**. It is a Python function
with one parameter, the target. If `pythonbuilder` determines that it must
(re-)create a target `target1` with its command `cmd1` it will call the command
with one arguments, namely the target.

```python
  cmd1(target1)
```

To know whether a target needs to be updated, a target has a **state** which,
internally, is a checksum (`hashlib.sha256I()` for now) of the target's content,
combined with the check-sums of its dependencies. A target gets updated if any
of the following two conditions hold:

1. After updating the dependencies their combined state is different from a
   previously recorded state.
2. The state of the target is different from a previously recorded state.

The latter makes sure that manual editing or even deletion of the target can be
detected.

If there is no previous recorded state, then the target is outdated by
definition and must be updated.

If a dependency is updated but its resulting state is the same as
before, like after it was accidentally deleted, the target will not be build
unnecessarily.

## Example

A minimal example, assumed to be stored in file `pb`:
```python
#!/usr/bin/env python3
import subprocess
import sys
sys.path += ["pythonbuilder"]
from pythonbuilder import Target, updateTargets

## Declare an initial target, assume it is an existing file in the project
rmd = Target(Path("README.md"))

## Declare README.html as file to be created by running runPandoc
def runPandoc(target: Target[Path]):
  # The dependencies are in the order in which they are provided to Target below
  input = str(target.dependencies[0].item)
  with open(target.item, "w", encoding="utf-8") as outfile:
    subprocess.run(["pandoc", input], stdout=outfile)

Target(
  Path("README.html"), # target name, often file or directory name
  rmd,                 # one dependency, could be more
  name="readme",       # nicer name to use on the command line
  state="file",        # how to compute a condensed state (fingerprint, checksum)
  cmd=runPandoc        # how to create the target, if it is out-of-date
)

updateTargets(*sys.argv[1:])
```

The default name of a `Target`, which has to be unique over the whole built, is
`str(Target.item)`, where `.item` is initialized by first parameter of
`Target`.

If you run the command `pb README.html` the following will happen (slightly
simplified):
- The builder finds the target for `"README.html"`.
- It checks the dependencies, in this case only `"README.md"`.
- It sees that the latter has no dependencies in itself and no `cmd=` parameter,
  so there is nothing to do for this target.
- Back to `"README.html"` which was never created, so it is not up-to-date and
  its command `runPandoc` is run.

On the command line you could also use `pb readme`, because of the name defined
for the 2nd target.  Also, in the second `Target` constructor call, you could
have used the target name `"readme"` instead of `rmd` to specify the
dependency.

See the [full api](https://harald.codeberg.page/pythonbuilder/@main/apidoc/pythonbuilder.html) for more information.

If you use this in a Java project, the
[mavenrepo](https://harald.codeberg.page/pythonbuilder/@main/apidoc/mavenrepo.MavenArtifact.html) might be interesting too.

