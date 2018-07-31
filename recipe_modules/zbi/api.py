# Copyright 2018 The Fuchsia Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from recipe_engine import recipe_api


class ZbiApi(recipe_api.RecipeApi):
    """ZbiApi provides support for Zircon's ZBI tool."""

    def __init__(self, *args, **kwargs):
        super(ZbiApi, self).__init__(*args, **kwargs)
        # The path to the zbi command.
        self._zbi = None

    @property
    def zbi_path(self):
        """The path to the zbi tool."""
        return self._zbi

    @zbi_path.setter
    def zbi_path(self, path):
        """Sets the path to the zbi tool."""
        self._zbi = path

    def copy_and_extend(self, step_name, input_image, output_image, manifest):
        """
        Creates a copy of a ZBI and extends its bootFS manifest.

        A copy of |input_image| is made at |output_image|, and the files
        given in |manifest| are added to the latter's bootFS manifest.

        Args:
          step_name (str): The name of the step.
          input_image (Path): The path to the input image.
          output_image (Path): The path to the output image.
          manifest (dict[str]Path): a dictionary of destination-to-source
            mappings, where destination/source are paths to files or
            directories on target/host, respectively.

        Returns:
          A step to perform the operation.
        """
        assert self.zbi_path

        cmd = [
          self.zbi_path,
          '-o',
          self.m.raw_io.output(leak_to=output_image),
          input_image,
        ]

        for dest in manifest:
          src = manifest[dest]
          cmd.extend(['-e', dest, src])

        return self.m.step(step_name, cmd)
