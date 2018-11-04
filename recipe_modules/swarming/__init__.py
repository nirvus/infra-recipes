DEPS = [
  'isolated',
  'recipe_engine/cipd',
  'recipe_engine/context',
  'recipe_engine/json',
  'recipe_engine/path',
  'recipe_engine/raw_io',
  'recipe_engine/step',
]

from recipe_engine.recipe_api import Property

PROPERTIES = {
  'swarming_server': Property(default='https://chromium-swarm.appspot.com'),
}
