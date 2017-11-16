# Copyright 2016 The Fuchsia Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from recipe_engine import recipe_api


class MinfsApi(recipe_api.RecipeApi):
    """MinfsApi provides support for Fuchia's MinFS tool.

  Currently this module can only be used with a Zircon build, which produces
  the local minfs binary.
  """

    def __init__(self, *args, **kwargs):
        super(MinfsApi, self).__init__(*args, **kwargs)
        # The path to the minfs command.
        self._minfs = None

    def __call__(self, *args, **kwargs):
        assert self._minfs
        name = kwargs.pop('name', 'minfs ' + args[0])
        cmd = [self._minfs]
        return self.m.step(name, cmd + list(args), **kwargs)

    @property
    def minfs_path(self):
        """Returns the path to the minfs command."""
        return self._minfs

    @minfs_path.setter
    def minfs_path(self, path):
        """Sets the path to the minfs command."""
        self._minfs = path

    def cp(self, remote_file, local_file, image):
        """Copies a file from an image.

    remote_file: string  The path to copy from the image.
    local_file: string  The path to copy to on the host.
    image: string The path to the MinFS image.
    """
        cmd = [
            image,
            'cp',
            '::%s' % remote_file,
            local_file,
        ]

        return self(*cmd)

    def mkfs(self, path, size_mb=100):
        """Creates a MinFS image at the given path

    path: string  The path at which to create the image.
    size_mb: int  The size of the image, in megabytes. Defaults to 100.
    """
        self.m.file.truncate(path, size_mb)
        return self(path, 'mkfs')
