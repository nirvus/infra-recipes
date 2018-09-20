DEPS = [
  'cipd',
  'recipe_engine/context',
  'recipe_engine/json',
  'recipe_engine/path',
  'recipe_engine/platform',
  'recipe_engine/python',
  'recipe_engine/raw_io',
  'recipe_engine/file',
  'recipe_engine/step',
  'infra/go',
]

from recipe_engine.recipe_api import Property
from recipe_engine.config import ConfigGroup, Single

PROPERTIES = {
    '$infra/tilo': Property(
        help='Properties specifically for the TiloApi module',
        param_name='tilo_properties',
        kind=ConfigGroup(
           credentials=Single(str),
           executable=Single(str),
        ), default={},
      ),
}
