DEPS = [
  'cipd',
  'recipe_engine/context',
  'recipe_engine/file',
  'recipe_engine/json',
  'recipe_engine/path',
  'recipe_engine/platform',
  'recipe_engine/properties',
  'recipe_engine/python',
  'recipe_engine/raw_io',
  'recipe_engine/step',
]

from recipe_engine.recipe_api import Property

PROPERTIES = {
    'luci_context': Property(from_environ='LUCI_CONTEXT', default=None),
}
