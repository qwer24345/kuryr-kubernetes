# Copyright (c) 2016 Mirantis, Inc.
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

import abc
import six

import os_vif
import pyroute2
from stevedore import driver as stv_driver

from kuryr_kubernetes import utils

_BINDING_NAMESPACE = 'kuryr_kubernetes.cni.binding'


@six.add_metaclass(abc.ABCMeta)
class BaseBindingDriver(object):
    """Interface to attach ports to pods."""

    @abc.abstractmethod
    def connect(self, vif, ifname, netns, container_id):
        raise NotImplementedError()

    @abc.abstractmethod
    def disconnect(self, vif, ifname, netns, container_id):
        raise NotImplementedError()


def _get_binding_driver(vif):
    mgr = stv_driver.DriverManager(namespace=_BINDING_NAMESPACE,
                                   name=type(vif).__name__,
                                   invoke_on_load=True)
    return mgr.driver


def get_ipdb(netns=None):
    if netns:
        netns = utils.convert_netns(netns)
        ipdb = pyroute2.IPDB(nl=pyroute2.NetNS(netns))
    else:
        ipdb = pyroute2.IPDB()
    return ipdb


def _enable_ipv6(netns):
    # Docker disables IPv6 for --net=none containers
    # TODO(apuimedo) remove when it is no longer the case
    try:
        netns = utils.convert_netns(netns)
        path = utils.convert_netns('/proc/self/ns/net')
        self_ns_fd = open(path)
        pyroute2.netns.setns(netns)
        path = utils.convert_netns('/proc/sys/net/ipv6/conf/all/disable_ipv6')
        with open(path, 'w') as disable_ipv6:
            disable_ipv6.write('0')
    except Exception:
        raise
    finally:
        pyroute2.netns.setns(self_ns_fd)


def _configure_l3(vif, ifname, netns, is_default_gateway):
    with get_ipdb(netns) as ipdb:
        with ipdb.interfaces[ifname] as iface:
            for subnet in vif.network.subnets.objects:
                if subnet.cidr.version == 6:
                    _enable_ipv6(netns)
                for fip in subnet.ips.objects:
                    iface.add_ip('%s/%s' % (fip.address,
                                            subnet.cidr.prefixlen))

        routes = ipdb.routes
        for subnet in vif.network.subnets.objects:
            for route in subnet.routes.objects:
                routes.add(gateway=str(route.gateway),
                           dst=str(route.cidr)).commit()
            if is_default_gateway and hasattr(subnet, 'gateway'):
                routes.add(gateway=str(subnet.gateway),
                           dst='default').commit()


def connect(vif, instance_info, ifname, netns=None, report_health=None,
            is_default_gateway=True, container_id=None):
    driver = _get_binding_driver(vif)
    if report_health:
        report_health(driver.is_alive())
    os_vif.plug(vif, instance_info)
    driver.connect(vif, ifname, netns, container_id)
    _configure_l3(vif, ifname, netns, is_default_gateway)


def disconnect(vif, instance_info, ifname, netns=None, report_health=None,
               container_id=None, **kwargs):
    driver = _get_binding_driver(vif)
    if report_health:
        report_health(driver.is_alive())
    driver.disconnect(vif, ifname, netns, container_id)
    os_vif.unplug(vif, instance_info)
