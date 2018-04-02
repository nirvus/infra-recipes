# Fuchsia Recipes

This repository contains recipes for Fuchsia.

A recipe is a Python script that runs a series of commands, using the
[recipe engine](https://github.com/luci/recipes-py) framework from the LUCI
project. We use recipes to automatically check out, build, and test Fuchsia in
continuous integration jobs. The commands the recipes use are very similar to
the ones you would use as a developer to check out, build, and test Fuchsia in
your local environment.

## Setting up your environment

A recipe will not run without `vpython`. Please add `vpython` into your PATH by
adding `$FUCHSIA/buildtools/linux-x64`, where `$FUCHSIA` is any Fuchsia
checkout.

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
pass to the recipe, as well as mock results for individual steps.

Here's an example test case for a recipe that accepts input properties
"manifest", "remote", "target", and "tests":

```
yield api.test('failed_tests') + api.properties(
    manifest='fuchsia',
    remote='https://fuchsia.googlesource.com/manifest',
    target='x64',
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
  "project": "garnet",
  "manifest": "manifest/garnet",
  "remote": "https://fuchsia.googlesource.com/garnet",
  "packages": ["garnet/packages/default"],
  "target": "x64",
  "build_type": "debug",
  "run_tests": true,
  "runtests_args": "/system/test",
  "goma_dir": "/usr/local/google/home/mknyszek/goma",
  "upload_snapshots": false,
  "tryjob": true,
  "$recipe_engine/source_manifest": {"debug_dir": null}
}
```

The last line helps prevent an error during local execution. It explicitly
nullifies a debug directory set by the environment on actual bots.

Setting `goma_dir` to false is currently necessary for testing any recipe that
builds some portion of Fuchsia end-to-end. Goma is enabled by default, and so
`goma_dir` is the mechanism which allows you to use a local instance of goma.

For instructions on using goma (Googlers only), see [the Fuchsia
docs](https://fuchsia.googlesource.com/docs/+/master/getting_started.md#googlers-only_goma)
.

If something strange is happening between re-runs, consider deleting the local
work directory as is done on bots (`rm -rf .recipe_deps`).

## Developer workflow

### Formatting

We format python code according to the Chrome team's style, using
[yapf](https://github.com/google/yapf).  After committing your changes you can
format the files in your commit by running this in your recipes project root:
(Make sure yapf is in your PATH)

```sh
git diff --name-only HEAD^ | grep -E '.py$' | xargs yapf -i
```

* `--name-only` tells git to list file paths instead of contents.
* `HEAD^` specifies only files that have changed in the latest commit.
* `-E` enables regular expressions for grep.
* `-i` instructs yapf to format files in-place instead of writing to stdout.

## Existing Fuchsia recipes

See [the generated documentation for our existing recipes and
modules](https://fuchsia.googlesource.com/infra/recipes/+/master/README.recipes.md)
for more information on what they do and how to use them.
