# Fuchsia Recipes

This repository contains recipes for Fuchsia.

A recipe is a Python script that runs a series of commands, using the
[recipe engine](https://github.com/luci/recipes-py) framework from the LUCI
project. We use recipes to automatically check out, build, and test Fuchsia in
continuous integration jobs. The commands the recipes use are very similar to
the ones you would use as a developer to check out, build, and test Fuchsia in
your local environment.

## Recipe concepts

### Properties

Recipes are parameterized using properties. The values for these properties can
be set in the
[Buildbucket configuration](https://fuchsia.googlesource.com/infra/config/#Buildbucket-configuration).
In the recipe code itself, they are specified in a global dictionary named
`PROPERTIES` and passed as arguments to a function named `RunSteps`. The recipes
engine automatically looks for these two objects at the top level of the Python
file containing the recipe.

When writing a recipe, you can make your properties whatever you want, but if
you plan to run your recipe on the Gerrit commit queue, there will be some
standard ones starting with `patch_`, which give information about the commit
being tested, and which you can see in the existing recipe code.

### Steps

When a recipe executes, it interacts with the underlying machine by running
steps.

A step is basically just a command, represented as a Python list of the
arguments. You give the step a name, specify the arguments, and the recipe
engine will run it in a subprocess, capture its output, and mark the job as
as failed if the command fails.

Here's an example:

```
api.step('list temporary files', ['ls', '/tmp'])
```

This will execute the command `ls /tmp` on the machine where the recipe is
running, and it will cause a failure if, for example, there is no `/tmp`
directory. When the recipe gets run on Swarming (which is the scheduling system
we use to run Fuchsia continuous integration jobs) this step will show up with
the label "list temporary files" in a list of all the steps that ran.

### Modules

Code is reused across recipes in the form of modules, which live either in the
`recipe_modules` directory of this repo, or in the same directory of the
[recipe engine](https://github.com/luci/recipes-py) repo. The recipe engine's
modules provide general functionality, and we have some modules specific to
Fuchsia in this repo, such as wrappers for QEMU and Jiri.

The recipe engine looks for a list named `DEPS` at the top level of the Python
file containing the recipe, where you can specify the modules you want to use.
Each item in `DEPS` is a string in the form "repo_name/module_name", where the
repo name is "recipe_engine" to get the dependency from the recipe engine repo,
or "infra" to get it from this repo.

### Unit tests

The reason it's important to only interact with the underlying machine via
steps is for testing. The recipes framework provides a way to fake the results
of the steps when testing the recipe, instead of actually running the commands.
It produces an "expected" JSON file, which shows exactly what commands would
have run, along with context such as working directory and environment
variables.

You write tests using the `GenTests` function. Inside `GenTests`, you can use
the `yield` statement to declare individual test cases. `GenTests` takes an API
object, which has functions on it allowing you to specify the properties to
pass to the recipe, as well as fake results for individual steps.

Here's an example test case from the `fuchsia.py` recipe:

```
yield api.test('failed_tests') + api.properties(
    manifest='fuchsia',
    remote='https://fuchsia.googlesource.com/manifest',
    target='x86-64',
    tests='tests.json',
) + api.step_data('run tests', retcode=1)
```

In this example:

* `api.test` simply gives the test case a name, which will be used to name the
  generated JSON "expected" file.
* `api.properties` specifies the properties that will be passed to `RunSteps`.
* `api.step_data` takes the name of one of the steps in the recipe, in this
  case "run tests", and specifies how it should behave. This is where you can
  make the fake commands produce your choice of fake output. Or, as in this
  example, you can specify a return code, in order to cover error-handling code
  branches in the recipe.

To run the unit tests and generate the "expected" data, run the following
command from the root of this repo:

```
python recipes.py test train --filter [recipe_name]
```

The name of the recipe is simply the name of the recipe's Python file minus the
`.py` extension. So, for example, the recipe in `recipes/fuchsia.py` is called
"fuchsia".

After you run the `test train` command, the JSON files with expectations will be
either generated or updated. Look at diff in Git, and make sure you didn't make
any breaking changes.

To just run the tests without updating the expectation files:

```
python recipes.py test run --filter [recipe_name]
```

To debug a single test, you can do this, which limits the test run to a single
test and runs it in pdb:

```
python recipes.py test debug --filter [recipe_name].[test_name]
```

### Choosing unit test cases

When you write new recipes or change existing recipes, your basic goal with unit
testing should be to cover all of your code and to check the expected output to
see if it makes sense. So if you create a new conditional, you should add a new
test case.

For example, let's say you're adding a feature to a simple recipe:

```
PROPERTIES = {
  'word': Property(kind=str, default=None),
}

def RunSteps(api, word):
  api.step('say the word', ['echo', word])

def GenTests(api):
  yield api.test('hello', word='hello')
```

And let's say you want to add a feature where it refuses to say "goodbye". So
you change it to look like this:

```
def RunSteps(api, word):
  if word == 'goodbye':
    word = 'farewell'
  api.step('say the word', ['echo', word])
```

To make sure everything works as expected, you should add a new test case for
your new conditional:

```
def GenTests(api):
  yield api.test('hello', word='hello')
  yield api.test('no_goodbye', word='goodbye')
```

There will now be two generated files when you run `test train`: one called
`hello.json` and one called `no_goodbye.json`, each showing what commands the
recipe would have run depending on how the `word` property is set.

### End-to-end testing

Unit tests should be the first thing you try to verify that your code runs. But
when writing a new recipe or making major changes, you'll also want to make sure
the recipe works when you actually run it. There's a similar command for that:

```
python recipes.py run --properties-file test.json [recipe_name]
```

For this command to work, you need to create a temporary file called `test.json`
specifying what properties you want to run the recipe with. Here's an example
of what that file might look like, for the `fuchsia.py` recipe:

```
{
  "remote": "https://fuchsia.googlesource.com/manifest",
  "manifest": "fuchsia",
  "build_type": "debug",
  "target": "x86-64",
  "use_goma": false,
  "modules": ["test_runner_dev"],
  "tests": "runtests /system/test",
  "use_autorun": true
}
```

Setting `use_goma` to false is currently necessary for local testing of the
Fuchsia recipes, due to the fact that they try to use a service account with
Goma.

Since every end-to-end test run of the Fuchsia recipe involves compiling
Fuchsia from scratch, the above examples uses the "test_runner_dev" module,
which only includes example test binaries. It's much faster to compile than the
default Fuchsia image, and it should give you enough information to test the
recipe.

## Existing Fuchsia recipes

Depending on what you're trying to automate, you may not need to write your own
recipe. We already have several that you can either use as-is with the
appropriate properties, or that may need to be slightly altered to fit a new use
case.

### Fuchsia (fuchsia.py)

This recipe is used for the primary Fuchsia builders, which build and test the
entire Fuchsia project, but it can also be adapted for more specialized usage.

The Fuchsia recipe does the following things:

1. Checks out the Fuchsia code using Jiri, using a manifest specified in the
   `manifest` property.
2. If triggered by the commit queue, patches to the pending commit.
3. Runs `scripts/build-zircon.sh`.
4. Runs `build/gn/gen.py` with modules specified in the `modules` property.
5. Builds Fuchsia using Ninja.
6. If the `tests` property is specified, runs the specified tests with
   [Test Runner](https://fuchsia.googlesource.com/garnet/+/master/bin/test_runner)
   on QEMU, using the Zircon image and `user.bootfs` generated by the previous
   steps.

This is a very flexible recipe, and it should be able to handle use cases such
as running a Ninja build with any combination of Fuchsia modules, running a
subset of the Fuchsia primary tests on QEMU, or running tests on QEMU that
aren't stable or fast enough for the primary builders.

### Zircon (zircon.py)

This is similar to the Fuchsia recipe, but it only builds and tests Zircon. It
does the following:

1. Checks out the Fuchsia code using Jiri. As in the Fuchsia recipe, the
   manifest can be specified, but you probably want to use "zircon" or some
   variation on "zircon" to avoid spending time downloading stuff you won't
   use.
2. Builds Zircon, including an autorun script that calls `runtests` and then
   shuts down.
3. Starts QEMU with the image generated by the previous step, and lets the
   autorun script run the tests.
4. Parses the QEMU output to see if the tests passed.

### Jiri (jiri.py)

This recipe uses Go's build tools to build and test Jiri.

### Cobalt (cobalt.py)

This recipe uses Cobalt's `cobaltb.py` build tool to build and test Cobalt.

### Modules (modules.py)

This recipe builds and tests UI modules, by running `make presubmit-cq`. Tests
are run directly on the host machine using Flutter, without a Fuchsia system or
QEMU.
