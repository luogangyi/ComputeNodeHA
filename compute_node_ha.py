# -*- encoding: utf-8 -*-
#
# Author: Luo Gangyi <luogangyi@chinamobile.com>

import os
import time
from novaclient.v1_1 import client
from novaclient import utils
from novaclient import base
from novaclient.openstack.common.gettextutils import _

from oslo.config import cfg
from eventlet import greenpool
from eventlet import greenthread
from datetime import datetime
from oslo.utils import encodeutils
import six
import uuid
from novaclient import exceptions
from utils import ssh
import scheduler

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

        self.scheduler = scheduler.RandomScheduler()


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
                      "try to rebuild all virtual machines on this host!"

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
                    vm = None
                    try:
                        tmp_id = encodeutils.safe_encode(server['uuid'])

                        if six.PY3:
                            tmp_id = tmp_id.decode()

                        uuid.UUID(tmp_id)
                        print tmp_id
                        vm = self.nova_client.servers.get(tmp_id)

                    except (TypeError, ValueError, exceptions.NotFound):
                        pass

                    if vm is None:
                        print "Can't find instance:%s" % server['uuid']
                        continue

                    target_host = self.scheduler.find_host(vm)

                    if target_host is None:
                        print "Can't find suitable host for instance: %s" % server['uuid']
                        continue

                    print "Rebulid instance %s on host %s " % (server['uuid'], target_host['host_name'])
                    success, responseMsg = self._server_evacuate(server, target_host['host_name'], on_shared_storage)
                    response.append(responseMsg)

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
            # print deadhost + " is in cooling!"
            return True

    def _handle_deadhost(self, deadhost):

        if self._in_cooling(deadhost):
            return

        self._restart_service(deadhost)
        greenthread.sleep(10)
        if not self._recheck_status(deadhost):
             self._host_evacuate(deadhost)


    def start(self):

        while True:
            dead_hosts = self._search_dead_host()

            for dead_host in dead_hosts:
                greenthread.spawn_n(self._handle_deadhost, dead_host)

            greenthread.sleep(1)


def main():
    cha = ComputeNodeHA()
    cha.start()
    pass

if __name__ == '__main__':
    greenthread.spawn_n(main())