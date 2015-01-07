#!/usr/bin/env python
#
# Author: Luo Gangyi <luogangyi@chinamobile.com>

from setuptools import setup, find_packages

setup(
      name="ComputeNodeHA",
      version="0.10.1",
      description="Compute Node HA",
      author="Luo Gangyi",
      url="https://github.com/luogangyi/ComputeNodeHA",
      license="Apache",
      packages= ['ComputeNodeHA','ComputeNodeHA.utils',
                 'ComputeNodeHA.openstack','ComputeNodeHA.openstack.common'],
      scripts=["bin/compute-node-ha"],
      data_files=[('/etc/ComputeNodeHA', ['computeNodeHA.conf']),
                  ('/etc/init.d', ['init-script/ComputeNodeHA'])]
      )