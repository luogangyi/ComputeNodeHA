# -*- encoding: utf-8 -*-
#
# Author: Luo Gangyi <luogangyi@chinamobile.com>

import paramiko
from ComputeNodeHA.openstack.common import log

LOG = log.getLogger('ComputeNodeHA')


class SshClient:
    """SSH client to connect compute node"""

    def __init__(self, host, port=22, username=None, password=None):
        self.host = host
        self.port = port
        self.username = username
        self.password = password

        self.ssh_client = ssh_client = paramiko.SSHClient()
        ssh_client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

        try:
            LOG.info("Connecting to %s@%s:%d by using SSH",username, host, port)
            ssh_client.connect(self.host, self.port, self.username, self.password)
        except Exception as e:
            LOG.error(e)

    def exec_cmd(self, cmd):
        try:
            stdin, stdout, stderr = self.ssh_client.exec_command(cmd)
            LOG.info(stdout.read())
            LOG.error(stderr.read())

        except Exception as e:
            LOG.error('*** Caught exception: %s: %s', e.__class__, e)
            try:
                self.ssh_client.close()
            except Exception as e:
                LOG.error('*** Caught exception: %s: %s', e.__class__, e)

def test():
    ssh_client = SshClient("192.168.36.72", 22, "root", "123456")
    ssh_client.exec_cmd("service iptables restart")

if __name__ == "__main__":
    test()





