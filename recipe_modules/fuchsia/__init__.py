DEPS = [
    'infra/cloudkms',
    'infra/gerrit',
    'infra/git',
    'infra/goma',
    'infra/gsutil',
    'infra/isolated',
    'infra/jiri',
    'infra/minfs',
    'infra/qemu',
    'infra/swarming',
    'infra/tar',
    'infra/zbi',
    'recipe_engine/cipd',
    'recipe_engine/buildbucket',
    'recipe_engine/context',
    'recipe_engine/json',
    'recipe_engine/file',
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
    '$infra/fuchsia': Property(
        help='Properties specifically for the fuchsia module',
        param_name='fuchsia_properties',
        kind=ConfigGroup(
          # The GCS bucket to upload build tracing data to.
          build_metrics_gcs_bucket=Single(str),
          # The GCS bucket to upload code coverage artifacts to.
          test_coverage_gcs_bucket=Single(str),
        ), default={},
      ),
}
