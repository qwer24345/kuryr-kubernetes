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

from kuryr.lib import constants as kl_const
from oslo_log import log as logging

from kuryr_kubernetes import clients
from kuryr_kubernetes import config
from kuryr_kubernetes import constants
from kuryr_kubernetes.controller.drivers import neutron_vif
from kuryr_kubernetes.controller.drivers import utils as c_utils
from kuryr_kubernetes import os_vif_util as ovu

LOG = logging.getLogger(__name__)


class SriovVIFDriver(neutron_vif.NeutronPodVIFDriver):
    """Provides VIFs for SRIOV VF interfaces."""

    ALIAS = 'sriov_pod_vif'

    def __init__(self):
        self._physnet_mapping = self._get_physnet_mapping()

    def request_vif(self, pod, project_id, subnets, security_groups):
        amount = self._get_remaining_sriov_vfs(pod)
        if not amount:
            LOG.error("SRIOV VIF request failed due to lack of "
                      "available VFs for the current pod creation")
            return None

        pod_name = pod['metadata']['name']
        neutron = clients.get_neutron_client()
        vif_plugin = 'sriov'
        subnet_id = next(iter(subnets))
        physnet = self._get_physnet_for_subnet_id(subnet_id)
        LOG.debug("Pod {} handling {}".format(pod_name, physnet))
        rq = self._get_port_request(pod, project_id,
                                    subnets, security_groups)

        port = neutron.create_port(rq).get('port')
        c_utils.tag_neutron_resources('ports', [port['id']])
        vif = ovu.neutron_to_osvif_vif(vif_plugin, port, subnets)
        vif.physnet = physnet

        LOG.debug("{} vifs are available for the pod {}".format(
            amount, pod_name))

        self._reduce_remaining_sriov_vfs(pod)
        return vif

    def activate_vif(self, pod, vif):
        vif.active = True

    def _get_physnet_mapping(self):
        physnets = config.CONF.sriov.default_physnet_subnets

        result = {}
        for name, subnet_id in physnets.items():
            result[subnet_id] = name
        return result

    def _get_physnet_for_subnet_id(self, subnet_id):
        """Returns an appropriate physnet for exact subnet_id from mapping"""
        try:
            physnet = self._physnet_mapping[subnet_id]
        except KeyError:
            LOG.error("No mapping for subnet {} in {}".format(
                subnet_id, self._physnet_mapping))
            raise
        return physnet

    def _get_remaining_sriov_vfs(self, pod):
        """Returns the number of remaining vfs.

        Returns the number of remaining vfs from the initial number that
        got allocated for the current pod. This information is stored in
        pod object.
        """
        containers = pod['spec']['containers']
        total_amount = 0
        for container in containers:
            try:
                requests = container['resources']['requests']
                amount_value = requests[constants.K8S_NPWG_SRIOV_PREFIX]
                total_amount += int(amount_value)
            except KeyError:
                    continue

        return total_amount

    def _reduce_remaining_sriov_vfs(self, pod):
        """Reduces number of available vfs for request"""
        containers = pod['spec']['containers']
        for container in containers:
            try:
                requests = container['resources']['requests']
                num_of_sriov = int(requests[constants.K8S_NPWG_SRIOV_PREFIX])
                if num_of_sriov == 0:
                    continue
                requests[constants.K8S_NPWG_SRIOV_PREFIX] = (
                    str(num_of_sriov - 1))
            except KeyError:
                    continue

    def _get_port_request(self, pod, project_id, subnets, security_groups):
        port_req_body = {
            'project_id': project_id,
            'name': c_utils.get_port_name(pod),
            'network_id': c_utils.get_network_id(subnets),
            'fixed_ips': ovu.osvif_to_neutron_fixed_ips(subnets),
            'device_owner': kl_const.DEVICE_OWNER + ':sriov',
            'device_id': c_utils.get_device_id(pod),
            'admin_state_up': True,
            'binding:vnic_type': 'direct',
            'binding:host_id': c_utils.get_host_id(pod),
        }

        if security_groups:
            port_req_body['security_groups'] = security_groups

        return {'port': port_req_body}
