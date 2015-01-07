# -*- encoding: utf-8 -*-
#
# Author: Luo Gangyi <luogangyi@chinamobile.com>

import os
from datetime import datetime
import uuid

from novaclient.v1_1 import client
from novaclient import utils
from novaclient import base
from oslo.config import cfg
from eventlet import greenthread
from oslo.utils import encodeutils
import six
from novaclient import exceptions

from ComputeNodeHA.utils import ssh
from ComputeNodeHA.openstack.common.gettextutils import _


# os_auth_url = 'http://192.168.36.72:5000/v2.0'
# os_tenant_name = 'admin'
# os_password = '123456'
# os_username = 'admin'


CLI_OPTIONS = [
    cfg.StrOpt('os-username',
               deprecated_group="DEFAULT",
               default=os.environ.get('OS_USERNAME', 'ceilometer'),
               help='User name to use for OpenStack service access.'),
    cfg.StrOpt('os-password',
               deprecated_group="DEFAULT",
               secret=True,
               default=os.environ.get('OS_PASSWORD', 'admin'),
               help='Password to use for OpenStack service access.'),
    cfg.StrOpt('os-tenant-id',
               deprecated_group="DEFAULT",
               default=os.environ.get('OS_TENANT_ID', ''),
               help='Tenant ID to use for OpenStack service access.'),
    cfg.StrOpt('os-tenant-name',
               deprecated_group="DEFAULT",
               default=os.environ.get('OS_TENANT_NAME', 'admin'),
               help='Tenant name to use for OpenStack service access.'),
    cfg.StrOpt('os-cacert',
               default=os.environ.get('OS_CACERT'),
               help='Certificate chain for SSL validation.'),
    cfg.StrOpt('os-auth-url',
               deprecated_group="DEFAULT",
               default=os.environ.get('OS_AUTH_URL',
                                      'http://localhost:5000/v2.0'),
               help='Auth URL to use for OpenStack service access.'),
    cfg.StrOpt('os-region-name',
               deprecated_group="DEFAULT",
               default=os.environ.get('OS_REGION_NAME'),
               help='Region name to use for OpenStack service endpoints.'),
    cfg.StrOpt('os-endpoint-type',
               default=os.environ.get('OS_ENDPOINT_TYPE', 'publicURL'),
               help='Type of endpoint in Identity service catalog to use for '
                    'communication with OpenStack services.'),
    cfg.BoolOpt('insecure',
                default=False,
                help='Disables X.509 certificate validation when an '
                     'SSL connection to Identity Service is established.'),
]

cfg.CONF.register_cli_opts(CLI_OPTIONS, group="service_credentials")
cfg.CONF(default_config_files=['/etc/ComputeNodeHA/computeNodeHA.conf'])


class EvacuateHostResponse(base.Resource):
    pass


class ComputeNodeHA(object):
    """
    Automatic check state of compute nodes.
    If the nova-compute service of a compute node is down while it was enabled,
    all the virtual machines on this node would be migrated to other available node.
    """

    restart_nova_cmd = "service openstack-nova-compute restart"
    COOL_TIME = 60

    def __init__(self):
        """Initialize a nova client object."""
        conf = cfg.CONF.service_credentials
        tenant = conf.os_tenant_id or conf.os_tenant_name
        self.nova_client = client.Client(
            username=conf.os_username,
            api_key=conf.os_password,
            project_id=tenant,
            auth_url=conf.os_auth_url,
            no_cache=True)

        self.update_time_map = {}


    def _search_dead_host(self):
        """search host whose Status is enabled and State is down"""

        dead_host = []
        hosts = self.nova_client.services.list()
        for host in hosts:
            if host.status == 'enabled' and \
                host.state == 'down' and \
                host.binary == 'nova-compute':

                dead_host.append(host.host)
                print "Compute service on "+host.host+" is down," \
                      "try to migrate all virtual machines on this host!"

        return dead_host

    def _host_evacuate(self, source_host, target_host=None, on_shared_storage=True):
        """Evacuate all instances from failed host."""
        host_name = source_host
        if '@' in source_host:
            host_name = source_host.split('@')[1]
        hypervisors = self.nova_client.hypervisors.search(host_name, servers=True)
        response = []
        for hyper in hypervisors:
            if hasattr(hyper, 'servers'):
                for server in hyper.servers:
                    print "Migrating virtual machine "+server['uuid']+" ..."
                    success,responseMsg = self._server_evacuate(server, target_host, on_shared_storage)
                    response.append(self._server_evacuate(server, target_host, on_shared_storage))

        utils.print_list(response,
                         ["Server UUID", "Evacuate Accepted", "Error Message"])


    def _server_evacuate(self, server, target_host=None, on_shared_storage=True):
        success = True
        error_message = ""
        try:
            self.nova_client.servers.evacuate(server=server['uuid'], host=target_host,
                                on_shared_storage = on_shared_storage)
        except Exception as e:
            success = False
            error_message = _("Error while evacuating instance: %s") % e
        return success, EvacuateHostResponse(base.Manager,
                                    {"server_uuid": server['uuid'],
                                    "evacuate_accepted": success,
                                    "error_message": error_message})


    def _restart_service(self, deadhost):
        '''try to restart compute service first'''

        #deal with name like 'region!child@server-36-72'
        host_name = deadhost
        if '@' in deadhost:
            host_name = host_name.split('@')[1]

        ssh_client = ssh.SshClient(host_name, 22, "admin", "123456")
        ssh_client.exec_cmd(self.restart_nova_cmd)

    def _recheck_status(self, deadhost):
        '''if service is enabled now, return true'''
        hosts = self.nova_client.services.list(host=deadhost)
        for host in hosts:
            print host.host, host.status, host.state, host.binary
            if host.binary == 'nova-compute':
                if host.status == 'enabled' and \
                        host.state == 'up':
                    return True

        return False

    def _in_cooling(self, deadhost):
        if not self.update_time_map.has_key(deadhost):
            self.update_time_map[deadhost] = datetime.now()
            return False
        previous_time = self.update_time_map.get(deadhost)
        delta_time = (datetime.now()-previous_time).seconds
        if delta_time > self.COOL_TIME:
            self.update_time_map[deadhost] = datetime.now()
            return False
        else:
            print deadhost + " is in cooling!"
            return True

    def _handle_deadhost(self, deadhost):

        if self._in_cooling(deadhost):
            return

        self._restart_service(deadhost)
        greenthread.sleep(10)
        if not self._recheck_status(deadhost):
             self._host_evacuate(deadhost)


    def show_vm_detail(self):

        hypervisors = self.nova_client.hypervisors.search('compute-58-11.local', servers=True)
        for hyper in hypervisors:
            if hasattr(hyper, 'servers'):
                for server in hyper.servers:
                    try:
                        tmp_id = encodeutils.safe_encode(server['uuid'])

                        if six.PY3:
                            tmp_id = tmp_id.decode()

                        uuid.UUID(tmp_id)
                        print tmp_id
                        vm = self.nova_client.servers.get(tmp_id)
                        if vm != None:
                            print vm.flavor['id']
                            self._is_boot_from_volume(vm)
                            flavor = self.nova_client.flavors.get(vm.flavor['id'])
                            print flavor.ram,flavor.vcpus
                    except (TypeError, ValueError, exceptions.NotFound):
                        pass

    def _is_boot_from_volume(self, vm):
        # Note(luogangyi): judge logic:
        # if no image attached, it must be started with volume.
        # if a image attached and the image has block device attributes,
        # it must be started with volume.

        image_info = vm.image

        if not image_info:
            print 'VM: '+vm.id+" has no image, boot from volume!"
            return True
        else:
            print 'image id:' + image_info['id']
            image = self.nova_client.images.get(image_info['id'])
            bdms = image.metadata.get('block_device_mapping')
            if bdms:
                for bdm in bdms:
                    if bdm.get('boot_index', -1) == 0:
                        print 'VM: '+vm.id+" has a volume-backed image, boot from volume!"
                        return True
            else:
                print 'VM: '+vm.id+" has a normal image or snapshot image, boot from local disk!"
                return False

    def _has_ephemeral_disk(self, vm):
        flavor = self.nova_client.flavors.get(vm.flavor['id'])
        if flavor.ephemeral>0:
            print 'VM: '+vm.id+" has a ephemeral disk!"
            return True

    def show_hosts(self):
        hosts =  self.nova_client.hosts.list()
        for host in hosts:
            print host.host_name
            if host.service != 'compute' :
                continue
            self.show_host_detail(host.host_name)


    def show_service_list(self):
        hosts = self.nova_client.services.list()
        for host in hosts:
            if host.status == 'enabled' and \
                host.state == 'up' and \
                host.binary == 'nova-compute':
                print host.host
                self.show_host_detail(host.host)


    def show_host_detail(self,name):
        '''
        Right form should be looked like below:

        +---------------------+------------+-----+-----------+---------+
        | HOST                | PROJECT    | cpu | memory_mb | disk_gb |
        +---------------------+------------+-----+-----------+---------+
        | compute-58-09.local | (total)    | 4   | 7857      | 679     |
        | compute-58-09.local | (used_now) | 0   | 512       | 0       |
        | compute-58-09.local | (used_max) | 0   | 0         | 0       |
        +---------------------+------------+-----+-----------+---------+

        or
        +---------------------+----------------------------------+-----+-----------+---------+
        | HOST                | PROJECT                          | cpu | memory_mb | disk_gb |
        +---------------------+----------------------------------+-----+-----------+---------+
        | compute-58-08.local | (total)                          | 4   | 7857      | 679     |
        | compute-58-08.local | (used_now)                       | 1   | 1024      | 1       |
        | compute-58-08.local | (used_max)                       | 1   | 512       | 1       |
        | compute-58-08.local | 8823bd06853f41b799a4b2a310f74aef | 1   | 512       | 1       |
        +---------------------+----------------------------------+-----+-----------+---------+


        '''

        host = self.nova_client.hosts.get(name)
        if len(host) < 3:
            print "Error Host Status"
            return
        for host_inner in host:
            print host_inner.cpu,host_inner.memory_mb




def main():
    cha = ComputeNodeHA()
    cha.show_vm_detail()
    #cha.show_hosts()
    cha.show_service_list()
    pass

if __name__ == '__main__':
    main()