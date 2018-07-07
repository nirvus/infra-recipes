DEPS = [
  'infra/cipd',
  'infra/gerrit',
  'infra/git',
  'infra/goma',
  'infra/gsutil',
  'infra/hash',
  'infra/isolated',
  'infra/jiri',
  'infra/minfs',
  'infra/qemu',
  'infra/swarming',
  'infra/tar',
  'recipe_engine/context',
  'recipe_engine/json',
  'recipe_engine/file',
  'recipe_engine/path',
  'recipe_engine/platform',
  'recipe_engine/properties',
  'recipe_engine/raw_io',
  'recipe_engine/source_manifest',
  'recipe_engine/step',
]

from recipe_engine.recipe_api import Property

PROPERTIES = {
  'goma_dir': Property(kind=str, help='Path to goma', default=None),
  'goma_local_cache': Property(kind=bool, help='Whether to use a local cache for goma', default=False),
}
