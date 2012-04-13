# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2011, Grid Dynamics
#
# All Rights Reserved.
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.

import os
import os.path
from functools import wraps

from nova import utils


def _abs_path(method):
    """Decorator that used to wrap FileInjector methods
    which accept path as first argument"""
    @wraps(method)
    def wrapper(obj, path, *args, **kwargs):
        return method(obj, obj.abs_path(path), *args, **kwargs)
    return wrapper


class FileInjector:
    """Injector used to inject files on already mounted Filesystem"""
    def __init__(self, mount_root):
        self.__root = mount_root

    def root(self):
        return self.__root

    def get_os_type(self):
        # todo: implement some heuristic
        return "ubuntu"

    def abs_path(self, path):
        p = path
        if p.startswith(os.path.sep):
            p = p[len(os.path.sep):]
        return os.path.join(self.__root, p)

    @_abs_path
    def mkdir(self, path):
        os.mkdir(path)

    @_abs_path
    def mkdir_p(self, path):
        """Works like mkdir -p."""
        return os.makedirs(path)

    @_abs_path
    def isdir(self, path):
        """Check directory is exists."""
        return os.path.isdir(path)

    @_abs_path
    def isfile(self, path):
        """Check file exists."""
        return os.path.isfile(path)

    @_abs_path
    def chmod(self, path, mode):
        """Change file mode.

        mode should be integer.
        """
        utils.execute(('chmod', '{0:o}'.format(mode), path),
            check_exit_code=True, run_as_root=True)

    @_abs_path
    def chown(self, path, uid=None, gid=None):
        """Change file ownership."""
        if uid is None:
            if gid is None:
                return
            param = ':' + gid
        elif gid is None:
            param = uid
        else:
            param = uid + ':' + gid
        utils.execute(('chown', param, path),
            check_exit_code=True, run_as_root=True)

    @_abs_path
    def write(self, path, content):
        """Write content to the file."""
        utils.execute('tee', path, process_input=content, run_as_root=True)

    @_abs_path
    def write_append(self, path, content):
        """Append content to the file.
        If file is not exists then create it first."""
        utils.execute('tee', '-a', path,
            process_input=content, run_as_root=True)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_inst, traceback):
        self.free()

    def free(self):
        pass


class GuestFsInjector:
    """Utility class to inject files into guest system root FS.

    Used for small modifications (like SSH keys injections) of an image before VM launching.
    """
    # Lazy initialization of guestfs
    __guestfs_cls = None

    @classmethod
    def init_guestfs(cls):
        if cls.__guestfs_cls is None:
            cls.__guestfs_cls = utils.import_class('guestfs.GuestFS')
        return cls.__guestfs_cls()

    def __init__(self, image):
        self.__gfs = self.init_guestfs()
        self.__gfs.add_drive(image)
        self.__gfs.launch()
        self.__root = self.__find_root()
        self.__gfs.resize2fs(self.__root)
        self.__gfs.mount(self.__root, '/')
        self.__os_type = None

    def get_os_type(self):
        if self.__os_type is None:
            self.__os_type = self.__gfs.inspect_get_distro(self.__root)
        return self.__os_type

    def __find_root(self):
        roots = self.__gfs.inspect_os()
        if len(roots) > 1:
            raise IOError('More than 1 root file system found')
        if not len(roots):
            raise IOError('Can\'t find root file system')
        return roots[0]

    def mkdir(self, path):
        """Create directory."""
        return self.__gfs.mkdir(path)

    def mkdir_p(self, path):
        """Works like mkdir -p."""
        return self.__gfs.mkdir_p(path)

    def is_dir(self, path):
        """Check directory is exists."""
        return self.__gfs.is_dir(path)

    def is_file(self, path):
        """Check file exists."""
        return self.__gfs.is_file(path)

    def chmod(self, path, mode):
        """Change file mode.

        mode should be integer.
        """
        return self.__gfs.chmod(mode, path)

    def chown(self, path, owner, group):
        """Change file ownership.

        owner and group should be integer id.
        """
        return self.__gfs.chown(owner, group, path)

    def write(self, path, content):
        """Write content to the file."""
        return self.__gfs.write(path, content)

    def write_append(self, path, content):
        """Append content to the file. If file is not exists then create it first."""
        if self.__gfs.exists(path):
            old_content = self.__gfs.read_file(path)
        else:
            old_content = ''
        return self.__gfs.write(path, old_content + content)

    def read_lines(self, path):
        return self.__gfs.read_lines(path)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_inst, traceback):
        self.free()

    def free(self):
        self.__gfs.umount_all()
        self.__gfs.sync()
