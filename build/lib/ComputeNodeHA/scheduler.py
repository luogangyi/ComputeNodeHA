# -*- encoding: utf-8 -*-
#
# Author: Luo Gangyi <luogangyi@chinamobile.com>


from novaclient.v1_1 import client
from oslo.config import cfg
import random

class BaseScheduler(object):
    '''Base Scheduler Class'''
    all_hosts = []

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

    def _get_all_available_hosts(self):
        #claer each time
        self.all_hosts = []

        hosts = self.nova_client.services.list()
        for host in hosts:
            if host.status == 'enabled' and \
                host.state == 'up' and \
                host.binary == 'nova-compute':

                host_detail = self._get_host_detail(host.host)

                if host_detail is not None:
                    self.all_hosts.append(host_detail)
        return self.all_hosts

    def _get_host_detail(self, host_name):
        '''
        Get Host details from nova client and detail dict.

        Right original form should be looked like below:

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

        host = self.nova_client.hosts.get(host_name)
        if len(host) < 3:
            print "Error Host Status"
            return None

        cpu_left = host[0].cpu - host[1].cpu
        mem_left = host[0].memory_mb - host[1].memory_mb
        disk_left = host[0].disk_gb - host[1].disk_gb

        host_detail = dict(host_name=host_name, cpu_left=cpu_left, mem_left=mem_left, disk_left=disk_left)
        print 'found host %(host_name)s: cpu_left %(cpu_left)d, ' \
              'mem_left %(mem_left)d, disk_left %(disk_left)d' % host_detail
        return host_detail

    def find_host(self, instance):
        return None


class FirstFitScheduler(BaseScheduler):
    '''Using First-Fit Algorithm'''

    def find_host(self, instance):
        '''
        :return host dict as
        dict(host_name=host_name, cpu_left=cpu_left, mem_left=mem_left, disk_left=disk_left)
        '''

        flavor_id = instance.flavor['id']
        flavor = self.nova_client.flavors.get(flavor_id)

        available_hosts = self._get_all_available_hosts()

        for host in available_hosts:
            if host['cpu_left']>flavor.vcpus and host['mem_left']>flavor.ram:
                return host
        #if no host meet requirements
        return None


class RandomScheduler(BaseScheduler):
    '''Using First-Fit Algorithm'''

    def find_host(self, instance):
        '''
        :return host dict as
        dict(host_name=host_name, cpu_left=cpu_left, mem_left=mem_left, disk_left=disk_left)
        '''

        flavor_id = instance.flavor['id']
        flavor = self.nova_client.flavors.get(flavor_id)

        available_hosts = self._get_all_available_hosts()
        #shuffle the host list
        random.shuffle(available_hosts)
        for host in available_hosts:
            if host['cpu_left']>flavor.vcpus and host['mem_left']>flavor.ram:
                return host
        #if no host meet requirements
        return None


# Test
if __name__ == '__main__':
    ffs = FirstFitScheduler()
    print ffs.find_host(ffs.nova_client.servers.get('995d3576-ae95-430a-8119-aa44363bdfb0'))

    rds = RandomScheduler()
    print rds.find_host(rds.nova_client.servers.get('995d3576-ae95-430a-8119-aa44363bdfb0'))