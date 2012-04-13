# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2010 United States Government as represented by the
# Administrator of the National Aeronautics and Space Administration.
#
# Copyright 2011, Piston Cloud Computing, Inc.
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
"""
Utility methods to resize, repartition, and modify disk images.

Includes injection of SSH PGP keys into authorized_keys file.

"""

import json
import os

from nova import flags
from nova import log as logging
from nova import utils
from nova.virt.injector import GuestFsInjector
from nova.virt.netcfg import NetConfig
from crypt import crypt


LOG = logging.getLogger('nova.compute.disk')
FLAGS = flags.FLAGS
flags.DEFINE_integer('minimum_root_size', 1024 * 1024 * 1024 * 10,
                     'minimum size in bytes of root partition')
flags.DEFINE_integer('block_size', 1024 * 1024 * 256,
                     'block_size to use for dd')
flags.DEFINE_integer('timeout_nbd', 10,
                     'time to wait for a NBD device coming up')
flags.DEFINE_integer('max_nbd_devices', 16,
                     'maximum number of possible nbd devices')

# NOTE(yamahata): DEFINE_list() doesn't work because the command may
#                 include ','. For example,
#                 mkfs.ext3 -O dir_index,extent -E stride=8,stripe-width=16
#                 --label %(fs_label)s %(target)s
#
#                 DEFINE_list() parses its argument by
#                 [s.strip() for s in argument.split(self._token)]
#                 where self._token = ','
#                 No escape nor exceptional handling for ','.
#                 DEFINE_list() doesn't give us what we need.
flags.DEFINE_multistring('virt_mkfs',
                         ['windows=mkfs.ntfs --fast --label %(fs_label)s '
                          '%(target)s',
                          # NOTE(yamahata): vfat case
                          #'windows=mkfs.vfat -n %(fs_label)s %(target)s',
                          'linux=mkfs.ext3 -L %(fs_label)s -F %(target)s',
                          'default=mkfs.ext3 -L %(fs_label)s -F %(target)s'],
                         'mkfs commands for ephemeral device. The format is'
                         '<os_type>=<mkfs command>')


_MKFS_COMMAND = {}
_DEFAULT_MKFS_COMMAND = None


for s in FLAGS.virt_mkfs:
    # NOTE(yamahata): mkfs command may includes '=' for its options.
    #                 So item.partition('=') doesn't work here
    os_type, mkfs_command = s.split('=', 1)
    if os_type:
        _MKFS_COMMAND[os_type] = mkfs_command
    if os_type == 'default':
        _DEFAULT_MKFS_COMMAND = mkfs_command


def mkfs(os_type, fs_label, target):
    mkfs_command = (_MKFS_COMMAND.get(os_type, _DEFAULT_MKFS_COMMAND) or
                    '') % locals()
    if mkfs_command:
        utils.execute(*mkfs_command.split())


def extend(image, size):
    """Increase image to size"""
    file_size = os.path.getsize(image)
    if file_size >= size:
        return
    utils.execute('qemu-img', 'resize', image, size)
    # NOTE(vish): attempts to resize filesystem
    utils.execute('e2fsck', '-fp', image, check_exit_code=False)
    utils.execute('resize2fs', image, check_exit_code=False)

def inject_fs(image, fs_type='ext3'):
    """
    Perform mkfs trough libguestfs
    """
    gfs = utils.import_class('guestfs.GuestFS')()
    gfs.add_drive(image)
    gfs.launch()
    devices = gfs.list_devices()
    gfs.mkfs(fs_type, devices[-1])
    gfs.sync()

def inject_data(image, key=None, nets=None, metadata=None, injected_files=None, admin_pass=None):
    """Injects a ssh key and optionally net data into a disk image.

    It will use GuestFS to inject files.
    """
    with GuestFsInjector(image) as injector:
        inject_data_into_fs(injector, key, nets, metadata, injected_files, admin_pass)


def inject_data_into_fs(injector, key=None, nets=None, metadata=None, injected_files=None, admin_pass=None):
    """Injects data into a root filesystem using injector.
    """
    if injected_files and len(injected_files):
        _inject_files_into_fs(injected_files, injector)
    if key:
        _inject_key_into_fs(key, injector)
    if nets and len(nets):
        _inject_net_into_fs(nets, injector)
    if metadata:
        _inject_metadata_into_fs(metadata, injector)
    if admin_pass:
        _inject_passw_into_fs(admin_pass, injector)


def _inject_metadata_into_fs(metadata, injector):
    metadata = dict([(m.key, m.value) for m in metadata])
    metadata_str = json.dumps(metadata)
    injector.write('meta.js', metadata_str)


def _inject_key_into_fs(key, injector):
    """Add the given public ssh key to root's authorized_keys.

    key is an ssh key string.
    injector is used to insert files.
    """
    sshdir = '/root/.ssh'
    injector.mkdir_p(sshdir)
    injector.chmod(sshdir, 0o700)
    keyfile = os.path.join(sshdir, 'authorized_keys')
    injector.write_append(keyfile,
        '\n# Injected by Nova key\n' + key.strip() + '\n')


def _inject_net_into_fs(nets, injector):
    """Inject /etc/network/interfaces into the filesystem use injector.

    net is the contents of /etc/network/interfaces.
    """
    os_type = injector.get_os_type()
    nc = NetConfig(os_type)
    for cfg_name, content in nc.generate(nets):
        injector.mkdir_p(os.path.dirname(cfg_name))
        injector.write(cfg_name, content)


def _inject_passw_into_fs(password, injector):
    LOG.debug('Injecting admin password')
    users = injector.read_lines('/etc/shadow')
    for i in range(len(users)):
        if users[i].startswith('root'):
            user_data = users[i].split(':')
            user_data[1] = crypt(password)
            users[i] = ':'.join(user_data)
            break
    new_shadow = '\n'.join(users)
    injector.write('/etc/shadow', new_shadow)


def _inject_files_into_fs(injected_files, injector):
    for name, content in injected_files:
        injector.mkdir_p(os.path.dirname(name))
        injector.write(name, content)
