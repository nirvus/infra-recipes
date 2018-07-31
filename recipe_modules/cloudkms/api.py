# Copyright 2018 The Fuchsia Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from recipe_engine import recipe_api


class CloudKmsApi(recipe_api.RecipeApi):
  """Module for interacting with CloudKMS.

  This is a thin wrapper of the CloudKMS Go client at
  https://github.com/luci/luci-go/client/cmd/cloudkms
  """

  def __init__(self, *args, **kwargs):
    super(CloudKmsApi, self).__init__(*args, **kwargs)
    self._cloudkms_path = None

  def ensure_cloudkms(self, version=None):
    with self.m.step.nest('ensure_cloudkms'):
      with self.m.context(infra_steps=True):
        cloudkms_package = (
            'infra/tools/luci/cloudkms/%s' % self.m.cipd.platform_suffix())
        cloudkms_dir = self.m.path['start_dir'].join('cipd', 'cloudkms')

        self.m.cipd.ensure(cloudkms_dir,
                           {cloudkms_package: version or 'latest'})
        self._cloudkms_path = cloudkms_dir.join('cloudkms')

        return self._cloudkms_path

  def decrypt(self, step_name, crypto_key_path, ciphertext_file,
              plaintext_file):
    """Decrypts a ciphertext encrypted with a CloudKMS crypto key.

    Args:
      step_name (str): name of the step.
      crypto_key_path (str): path in CloudKMS to the crypto key, generically
        of the form `<project>/<location>/<key ring>/<crypto key name>`, where
        the infixes are CloudKMS concepts detailed at
        https://cloud.google.com/kms/docs/object-hierarchy.
      ciphertext_file (Path): path to a file containing the ciphertext.
      plaintext_file (Path): path to a file to which the plaintext will be
        written.

    Returns:
      A step to perform the decryption.
    """
    assert self._cloudkms_path

    return self.m.step(step_name, [
        self._cloudkms_path,
        'decrypt',
        '-input', ciphertext_file,
        '-output', self.m.raw_io.output(leak_to=plaintext_file),
        crypto_key_path,
    ])
