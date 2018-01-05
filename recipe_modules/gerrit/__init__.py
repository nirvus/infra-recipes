DEPS = [
  'cipd',
  'recipe_engine/context',
  'recipe_engine/json',
  'recipe_engine/path',
  'recipe_engine/step',
]

from recipe_engine.recipe_api import Property

PROPERTIES = {
    'gerrit_host': Property(default='https://fuchsia-review.googlesource.com'),
}
