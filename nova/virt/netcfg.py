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

from nova import flags

FLAGS = flags.FLAGS

class _UbuntuNetConfig:
    __header = """# This file describes the network interfaces available on your system
# and how to activate them. For more information, see interfaces(5).
# Initial content of this file is autogenerated by OpenStack.

# The loopback network interface
auto lo
iface lo inet loopback
"""
    __iface4 = """
auto {name}
iface {name} inet static
        address {address}
        netmask {netmask}
        broadcast {broadcast}
        gateway {gateway}
        dns-nameservers {dns}
"""
    __iface6 = """
iface {name} inet6 static
    address {address_v6}
    netmask {netmask_v6}
    gateway {gateway_v6}
"""

    def __init__(self):
        pass

    def generate(self, nets):
        cfg = [self.__header]
        for net in nets:
            cfg.append(self.__iface4.format(**net))
            if FLAGS.use_ipv6:
                cfg.append(self.__iface6.format(**net))
        yield ('/etc/network/interfaces', ''.join(cfg))


class _RhelNetConfig:
    __header = '''#This file is autogenerated by OpenStack.
'''
    __iface4 = '''
DEVICE="{name}"
NM_CONTROLLED="no"
ONBOOT=yes
TYPE=Ethernet
BOOTPROTO=static
IPADDR={address}
NETMASK={netmask}
BROADCAST={broadcast}
GATEWAY={gateway}
'''
    __iface6 = '''
IPV6INIT=yes
IPV6ADDR={address_v6}
'''
    def __init__(self):
        pass

    def generate(self, nets):
        for net in nets:
            cfg = [self.__header, self.__iface4.format(**net)]
            if FLAGS.use_ipv6:
                cfg.append(self.__iface6.format(**net))
            yield ('/etc/sysconfig/network-scripts/ifcfg-{0}'.format(net['name']), ''.join(cfg))


class NetConfig:
    """Generate network config files for various linux distributions.

    Example usage:

    >>> nc = NetConfig()
    >>> for path, content in nc.generate(nets):
    >>>     # write configuration file
    """

    __implementations = {
        'ubuntu': _UbuntuNetConfig,
        'rhel': _RhelNetConfig
    }

    def __init__(self, os_type):
        """NetConfig constructor.

        :param os_type: linux distribution type.
        :type os_type: str.
        """
        nc = self.__implementations.get(os_type)
        if nc is None:
            raise ValueError('{0} OS type is unsupported'.format(os_type))
        self.__nc = nc()

    def generate(self, nets):
        """Generate network configuration.

        :param nets: Network configuration.
        :returns: generator of tuples (<cfg_file_name>, <cfg_file_content>)
        """
        return self.__nc.generate(nets)
