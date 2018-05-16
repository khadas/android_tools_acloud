#!/usr/bin/env python
#
# Copyright 2018 - The Android Open Source Project
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""A client that manages Cuttlefish Virtual Device on compute engine.

** CvdComputeClient **

CvdComputeClient derives from AndroidComputeClient. It manges a google
compute engine project that is setup for running Cuttlefish Virtual Devices.
It knows how to create a host instance from Cuttlefish Stable Host Image, fetch
Android build, and start Android within the host instance.

** Class hierarchy **

  base_cloud_client.BaseCloudApiClient
                ^
                |
       gcompute_client.ComputeClient
                ^
                |
       android_compute_client.AndroidComputeClient
                ^
                |
       cvd_compute_client.CvdComputeClient

"""


import getpass
import logging
import os

from acloud.internal.lib import android_compute_client
from acloud.internal.lib import gcompute_client

logger = logging.getLogger(__name__)


class CvdComputeClient(android_compute_client.AndroidComputeClient):
  """Client that manages Anadroid Virtual Device."""

  DATA_POLICY_CREATE_IF_MISSING = "create_if_missing"

  def __init__(self, acloud_config, oauth2_credentials):
    """Initialize.

    Args:
      acloud_config: An AcloudConfig object.
      oauth2_credentials: An oauth2client.OAuth2Credentials instance.
    """
    super(CvdComputeClient, self).__init__(acloud_config, oauth2_credentials)

  def _GetDiskArgs(self, disk_name, image_name, image_project, disk_size_gb):
    """Helper to generate disk args that is used to create an instance.

    Args:
      disk_name: A string
      image_name: A string
      image_project: A string
      disk_size_gb: An integer

    Returns:
      A dictionary representing disk args.
    """
    return [{
        "type": "PERSISTENT",
        "boot": True,
        "mode": "READ_WRITE",
        "autoDelete": True,
        "initializeParams": {
            "diskName": disk_name,
            "sourceImage": self.GetImage(image_name, image_project)["selfLink"],
            "diskSizeGb": disk_size_gb
        },
    }]

  def CreateInstance(
      self, instance, image_name, image_project, build_target, branch, build_id,
      kernel_branch=None, kernel_build_id=None, blank_data_disk_size_gb=None):
    """Create a cuttlefish instance given a stable host image and a build id.

    Args:
      instance: instance name.
      image_name: A string, the name of the GCE image.
      image_project: A string, name of the project where the image belongs.
                     Assume the default project if None.
      build_target: Target name, e.g. "aosp_cf_x86_phone-userdebug"
      branch: Branch name, e.g. "aosp-master"
      build_id: Build id, a string, e.g. "2263051", "P2804227"
      kernel_branch: Kernel branch name, e.g. "kernel-android-cf-4.4-x86_64"
      kernel_build_id: Kernel build id, a string, e.g. "2263051", "P2804227"
      blank_data_disk_size_gb: Size of the blank data disk in GB.
    """
    self._CheckMachineSize()

    # A blank data disk would be created on the host. Make sure the size of the
    # boot disk is large enough to hold it.
    boot_disk_size_gb = (
        int(self.GetImage(image_name, image_project)["diskSizeGb"]) +
        blank_data_disk_size_gb)
    disk_args = self._GetDiskArgs(
        instance, image_name, image_project, boot_disk_size_gb)

    # Transitional metadata variable as outlined in go/cuttlefish-deployment
    # These metadata tell the host instance to fetch and launch one cuttlefish
    # device (cvd-01). Ideally we should use a separate tool to manage CVD
    # devices on the host instance and not through metadata.
    # TODO(b/77626419): Remove these metadata once the cuttlefish-google.service
    # is
    # turned off on the host instance.
    metadata = self._metadata.copy()
    resolution = self._resolution.split("x")
    metadata["cvd_01_dpi"] = resolution[3]
    metadata["cvd_01_fetch_android_build_target"] = build_target
    metadata["cvd_01_fetch_android_bid"] = "{branch}/{build_id}".format(
        branch=branch, build_id=build_id)
    if kernel_branch and kernel_build_id:
      metadata["cvd_01_fetch_kernel_bid"] = "{branch}/{build_id}".format(
          branch=kernel_branch, build_id=kernel_build_id)
    metadata["cvd_01_launch"] = "1"
    metadata["cvd_01_x_res"] = resolution[0]
    metadata["cvd_01_y_res"] = resolution[1]
    if blank_data_disk_size_gb > 0:
      # Policy 'create_if_missing' would create a blank userdata disk if
      # missing. If already exist, reuse the disk.
      metadata["cvd_01_data_policy"] = self.DATA_POLICY_CREATE_IF_MISSING
      metadata["cvd_01_blank_data_disk_size"] = str(
          blank_data_disk_size_gb * 1024)

    # Add per-instance ssh key
    if self._ssh_public_key_path:
      rsa = self._LoadSshPublicKey(self._ssh_public_key_path)
      logger.info("ssh_public_key_path is specified in config: %s, "
                  "will add the key to the instance.",
                  self._ssh_public_key_path)
      metadata["sshKeys"] = "%s:%s" % (getpass.getuser(), rsa)
    else:
      logger.warning(
          "ssh_public_key_path is not specified in config, "
          "only project-wide key will be effective.")

    gcompute_client.ComputeClient.CreateInstance(
        self,
        instance=instance,
        image_name=image_name,
        image_project=image_project,
        disk_args=disk_args,
        metadata=metadata,
        machine_type=self._machine_type,
        network=self._network,
        zone=self._zone)
