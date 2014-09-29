#!/usr/bin/env python
#
# Author: Luo Gangyi <luogangyi@chinamobile.com>

from setuptools import setup

setup(
      name="ComputeNodeHA",
      version="0.10",
      description="Compute Node HA",
      author="Luo Gangyi",
      url="https://github.com/luogangyi/ComputeNodeHA",
      license="Apache",
      packages= ['ComputeNodeHA','ComputeNodeHA.utils'],
      scripts=["bin/compute-node-ha"],
      data_files=[('/etc/ComputeNodeHA', ['computeNodeHA.conf']),]
      )