DEPS = [
  'recipe_engine/cipd',
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
from recipe_engine.config import ConfigGroup, Single

PROPERTIES = {
  'luci_context': Property(from_environ='LUCI_CONTEXT', default=None),
  '$infra/goma': Property(
    help='Properties specifically for the goma module',
    param_name='goma_properties',
    kind=ConfigGroup(
      # Path to goma directory.
      goma_dir=Single(str),
      # How many jobs to run in parallel.
      jobs=Single(int),
      # Whether or not to use deps cache.
      deps_cache=Single(bool),
      # Whether or not to use local cache.
      local_output_cache=Single(bool),
    ), default={},
  ),
}
