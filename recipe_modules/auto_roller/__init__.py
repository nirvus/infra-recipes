DEPS = [
  'infra/gerrit',
  'infra/git',
  'recipe_engine/context',
  'recipe_engine/json',
  'recipe_engine/path',
  'recipe_engine/properties',
  'recipe_engine/raw_io',
  'recipe_engine/step',
  'recipe_engine/time',
  'recipe_engine/url',
]

from recipe_engine.recipe_api import Property
from recipe_engine.config import Single

PROPERTIES = {
  'poll_timeout_secs': Property(kind=Single((float, int)),
                                default=50*60,
                                help='The total amount of seconds to spend polling before timing out'),
  'poll_interval_secs': Property(kind=Single((float, int)),
                                 default=5*60,
                                 help='The interval at which to poll in seconds'),
}
