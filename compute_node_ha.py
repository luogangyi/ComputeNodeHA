# -*- encoding: utf-8 -*-
#
# Author: Luo Gangyi <luogangyi_sz@139.com>

import os
import time
from novaclient.v1_1 import client
from novaclient import utils
from novaclient import base
from novaclient.openstack.common.gettextutils import _

from oslo.config import cfg
from eventlet import greenpool
from eventlet import greenthread
from utils import ssh

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
cfg.CONF(default_config_files='ceilometer.conf')


class EvacuateHostResponse(base.Resource):
    pass


class ComputeNodeHA(object):
    """
    Automatic check state of compute nodes.
    If the nova-compute service of a compute node is down while it was enabled,
    all the virtual machines on this node would be migrated to other available node.
    """

    restart_nova_cmd = "service openstack-nova-compute restart"

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

        self.pool = greenpool.GreenPool(1000)

    def _search_dead_host(self):
        """search host whose Status is enabled and State is down"""

        dead_host = []
        hosts = self.nova_client.services.list()
        for host in hosts:
            if host.status == 'enabled' and \
                host.state == 'up' and \
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
        return EvacuateHostResponse(base.Manager,
                                    {"server_uuid": server['uuid'],
                                    "evacuate_accepted": success,
                                    "error_message": error_message})


    def _restart_service(self, deadhost):
        '''try to restart compute service first'''

        #deal with name like 'region!child@server-36-72'
        host_name = deadhost
        if '@' in deadhost:
            host_name = host_name.split('@')[1]

        ssh_client = ssh.SshClient(host_name, 22, "root", "123456")
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

    def _handle_deadhost(self, deadhost):
        self._restart_service(deadhost)
        greenthread.sleep(10)
        if not self._recheck_status(deadhost):
             self._host_evacuate(deadhost)


    def start(self):

        while True:
            dead_hosts = self._search_dead_host()

            for dead_host in dead_hosts:
                greenthread.spawn_n(self._handle_deadhost, dead_host)

            greenthread.sleep(60)
            #self._handle_deadhost(dead_host)


def main():
    cha = ComputeNodeHA()
    cha.start()
    pass

if __name__ == '__main__':
    greenthread.spawn_n(main())