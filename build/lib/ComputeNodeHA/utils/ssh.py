# -*- encoding: utf-8 -*-
#
# Author: Luo Gangyi <luogangyi@chinamobile.com>

import paramiko

class SshClient:

    def __init__(self, host,port=22,username=None, password=None):
        self.host = host
        self.port = port
        self.username = username
        self.password = password

        self.ssh_client = ssh_client = paramiko.SSHClient()
        ssh_client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

        try:
            print "Connecting to %s@%s:%d by using SSH" % (username, host, port)
            ssh_client.connect(self.host, self.port, self.username, self.password)
        except Exception as e:
            print e

    def exec_cmd(self, cmd):
        try:
            stdin, stdout, stderr = self.ssh_client.exec_command(cmd)
            print stdout.read()
            print stderr.read()
        except Exception as e:
            print('*** Caught exception: %s: %s' % (e.__class__, e))
            try:
                self.ssh_client.close()
            except:
                pass

def test():
    ssh_client = SshClient("192.168.36.72", 22, "root", "123456")
    ssh_client.exec_cmd("service iptables restart")

if __name__ == "__main__":
    test()





