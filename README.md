#  <img src="config/pythonbuilder-logo.png" width="60"> pythonbuilder &mdash; pythonic project builder

<!-- markdown-toc start - Don't edit this section. Run M-x markdown-toc-refresh-toc -->
**Table of Contents**

  - [Getting Started](#getting-started)
  - [Some Theory or "Why?"](#some-theory-or-why)
  - [Functional Overview](#functional-overview)
  - [Example](#example)
  - [Why Python](#why-python)
  - [Dependency Graph of pythonbuilder's build](#dependency-graph-of-pythonbuilders-build)

<!-- markdown-toc end -->

Quick link: [api documentation](https://harald.codeberg.page/docs/@main/pythonbuilder/index.html).

See also: [BuildMachine](https://codeberg.org/harald/BuildMachine),
[bashbuilder](https://codeberg.org/harald/bashbuilder)

## Getting Started

Copy `./pythonbuilder` to some place you like. The suggested place is the
sub-directory `./pythonbuilder` in your project directory.

Write a build script in Python, called `pb` (for example), which basically defines

- tasks, which are functions decorated with `@task` and which return a `Target[...]`,
- each task contains one call like `t = target(Path(...), ...)`,
- and checks `t.outdated` to know if anything needs to be done to update the target,

This minimal example shows two tasks to define two targets, one depending on the other:

<!-- inlined file: example, update with 'pb readme' -->
```python
#!/usr/bin/env python3
import sys
from pathlib import Path

from pythonbuilder import (
  Target,
  internalTask,
  main,
  pbexec,
  target,
  task,
)


## Declare a task for a target without dependencies, the input README.md
@internalTask
def readmeMd() -> Target[Path]:
  return target(Path("README.md"))


## Declare a task which depends on readmeMd to make sure that if README.md
## is edited, this task will be run.
@task
def readme() -> Target[Path]:
  ## Get our dependency
  input = readmeMd()

  ## define the target README.html,
  ## depending on input (could be more)
  ## and say that it is a file, not a directory
  t = target(Path("README.html"), input, state="file")

  ## t.outdated will be true if either README.md was changed or README.html
  ## was fumbled with or even deleted.
  if t.outdated:
    pbexec("pandoc", "-t", "html", "-o", t.item, input.item)
  return t


sys.exit(main(sys.argv[1:]))
```
<!-- inlined file end -->

Lets assume you stored the file in `./pb`. Then you can now build `README.html`
from `README.md` by running `python3 ./pb readme`, and the following will happen
(slightly simplified):

- The builder finds the task `readme` and calls it.
- This again calls `readmeMd`, the dependency task. Since `README.md` is an
  input to the build process, its path is just returned wrapped by `target()`
  for build bookkeeping.
- Now task `readme` calls `target()` which checks whether `README.html` is
  out-of-date with regard to the dependency. The returned target's `.outdated`
  field tells the caller.
- If it is outdated, we call `pbexec()`, a shallow wrapper around
  `subprocess.run` to create or update `README.html` with `pandoc`.
  
Try also the following:
- Remove `build/pbstates` to force a full rebuild.
- Use `python3 pb force=readme ll=verbose` to force the target to be out-of-date
  and see that `pandoc` is always run.
- Experiment with
[registerDependencyGraphTask](https://harald.codeberg.page/docs/@main/pythonbuilder/pythonbuilder.html#registerDependencyGraphTask)
to create a dependency graph for your build like the one shown for this project.

See the [full
api](https://harald.codeberg.page/docs/@main/pythonbuilder/pythonbuilder.html)
for more information.

If you use this in a Java project, then
[mavenrepo.MavenArtifact](https://harald.codeberg.page/docs/@main/pythonbuilder/mavenrepo.MavenArtifact.html)
and module
[java](https://harald.codeberg.page/docs/@main/pythonbuilder/java.html)
might be interesting too.
 

## Some Theory or "Why?"

Why do we have build systems at all? What do they do? Why not just write a
script which runs all the commands we need to build our product in the right
order? These days I see one real reason and two pseudo reasons to use a build
system. Lets start with the two pseudo-reasons:

**Dependency resolution:** Sure, these days this is a major thing to even get
started with any non-trivial project: pull in the cornucopia of libraries you
want to use. But, hey, this is just "dependency resolution", not what I call the
genuine task of a build system. Even with a straight script you could have one
command, call it `npm install` or `pulldeps` in some imagined ecosystem, which
pulls your libraries. Just call it first and be done.

**Task library:** There are tasks which need to be done in every build for a
software written in language or eco-system. Not having to repeat the task for
every new software would be great, so a task library to lint, compile, package,
publish and what-not is nice. But still not the genuine task of the build
system. You could have that library for whatever script language you use to
write your build script.

**Guarded execution:** Repeating tasks for which the input did not change will
result in the same output we have already. This is not only annoying, but takes
unnecessary time and, in particular, strains our patience. So the very thing
ancient `make` introduced was to avoid compiling C files which did not change,
based on their last write time stamp. That's what I call "guarded execution": if

- the input did not change and
- the output is still available unchanged

there is no point executing the command which create that output from the input.

And it is exactly that last genuine task of a build system that `pythonbuilder`
implements. In particular the `@task`

- calls dependency tasks, executing their build step only if needed,
- calls `target()` to check whether, given the dependencies and the current
  state of the target item itself, it  needs to be updated,
- runs the build step as needed, conditional on `Target.outdated`.

Agreed, we have `java.py` and `pbpython.py` which provide a bit of the "task
library" bit, but more as an example than as a full blown feature set.

## Functional Overview
A **target** is something you want to build. Usually it is a file or the
contents of a whole directory. To build `target1`, it may be necessary to build
`targetA` and `targetB` first. Then those two are called **dependencies** of
`target1`.

Of course a dependency can have its own dependencies too and different targets
may have the same dependencies. The result is a directed graph without
cycles. If a target directly or indirectly has itself as a dependency, this is
flagged as an error.

A target is represented by on object of class `Target`. The thing to actually
built is wrapped as the field `item` of `Target`.

To create or recreate a target, it has an associated **command**. It is a Python
function with N+1 parameters, the target's `item` as well as the `item` values
of all dependencies. If `pythonbuilder` determines that it must (re-)create a
`target1` with its command `cmd1` it will call the command as:

```python
  cmd1(target1.item, targetA.item, targetB.item)
```

If you use `mypy` or a similar type checker for Python, it helps you to match the
item types of the dependencies to the command.

When pythonbuilder analyzes a target to find out whether its command needs to be
run, we say the it **updates** the target, independent of whether the command is
run or if the target is still up-to-date anyway.  To know whether a target needs
to be updated, a target has a **state** which, internally, often is a checksum
(`hashlib.sha256()` for now) of the target's content, combined with the
check-sums of its dependencies. A target's command is run if any of the
following two conditions hold:

1. After updating all dependencies, their combined state is different from a
   previously recorded combined state.
2. The state of the target is different from a previously recorded state.

The latter makes sure that manual editing or even deletion of the target can be
detected.

If there is no previous recorded state, then the target is outdated by
definition and must be re-created.

If a dependency is created but its resulting state is the same as before, like
after it was accidentally deleted, the target will not be created unnecessarily.


## Why Python?

Well, because I tried other solutions:

- [BuildMachine](https://codeberg.org/harald/BuildMachine) is mostly the same
  but written in Java. While implementing the machinery in Java is great, the
  actual use in writing the "build script" is a bit bumpy despite recent
  improvements whereby source files can be run without compilation
  ... script-like.
- [bashbuilder](https://codeberg.org/harald/bashbuilder) is again mostly the
  same but written in `bash`. Though here it is the other way round: writing a
  build script is as straight forward as writing a bash script. But implementing
  the machinery was an absolute pita, mostly because of the missing or hard to
  use data structures like maps and lists.

Python provides just the right middle ground for both implementing the
machinery, these days even mostly type safe with type hints, and writing the
build script without lots of ceremony.

## Dependency Graph of pythonbuilder's build
<img src="dependencies.svg" width="95%">

## Historic Use

The version prior to October 2026 had an older scheme to define tasks,
namely by calling `Target` directly and using `updateTargets` to run the
build. It is still available on branch `historic-target-based`.

The following is from the old README.md.

Write a build script in Python, called `pb` (for example), which has the following
structure:
```python
#!/usr/bin/env python3
import sys
import pythonbuilder.pbutil as pbutil
from pythonbuilder import Target, pbexec, toGraphviz, ...

def defineTargets() -> None:
  ... multiple calls to the Target constructor ...

... definition of functions to create your targets ...

defineTargets()
if not pbutil.main(*sys.argv[1:]):
  sys.exit(1)
```

Run `./pb target` to build the given target according to the recipe described in
your build script, where target is a name of one of the `Target` objects you created.
