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
        name = kwargs.pop('name', 'minfs ' + args[1])
        cmd = [self._minfs]
        return self.m.step(name, cmd + list(args), **kwargs)

    @property
    def minfs_path(self):
        """The path to the minfs command."""
        return self._minfs

    @minfs_path.setter
    def minfs_path(self, path):
        """The path to the minfs command."""
        self._minfs = path

    def cp(self, from_path, to_path, image, **kwargs):
        """
        Copies a file or directory from an image.

        Paths inside of the MinFS image are prefixed with '::', so '::'
        refers to the root of the MinFS image.

        Args:
          from_path (str|Path): The path to copy from.
          to_path (str|Path): The path to copy to.
          image (str|Path): The path to the MinFS image.

        Returns:
          A step to perform the copy.
        """
        cmd = [
            image,
            'cp',
            from_path,
            to_path,
        ]

        return self(*cmd, **kwargs)

    def create(self, path, size="100M", **kwargs):
        """
        Creates a MinFS image at the given path.

        Args:
          path (str): The path at which to create the image.
          size (str): The size of the image, number followed by unit. Defaults to 100M.

        Returns:
          A step to perform the creation.
        """
        return self(str(path) + "@" + size, 'create', **kwargs)
