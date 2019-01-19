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
r"""RemoteImageLocalInstance class.

Create class that is responsible for creating a local instance AVD with a
remote image.
"""
from __future__ import print_function
import logging
import os
import subprocess
import sys

from acloud import errors
from acloud.create import local_image_local_instance
from acloud.internal import constants
from acloud.internal.lib import android_build_client
from acloud.internal.lib import auth
from acloud.internal.lib import utils
from acloud.setup import setup_common

# Download remote image variables.
_CVD_HOST_PACKAGE = "cvd-host_package.tar.gz"
_CUTTLEFISH_COMMON_BIN_PATH = "/usr/lib/cuttlefish-common/bin/"
_CONFIRM_DOWNLOAD_DIR = ("Download dir %(download_dir)s does not have enough "
                         "space (available space %(available_space)sGB, "
                         "require %(required_space)sGB).\nPlease enter "
                         "alternate path or 'q' to exit: ")
# The downloaded image artifacts will take up ~8G:
#   $du -lh --time $ANDROID_PRODUCT_OUT/aosp_cf_x86_phone-img-eng.XXX.zip
#   422M
# And decompressed becomes 7.2G (as of 11/2018).
# Let's add an extra buffer (~2G) to make sure user has enough disk space
# for the downloaded image artifacts.
_REQUIRED_SPACE = 10
_CF_IMAGES = ["cache.img", "cmdline", "kernel", "ramdisk.img", "system.img",
              "userdata.img", "vendor.img"]
_BOOT_IMAGE = "boot.img"
UNPACK_BOOTIMG_CMD = "%s -boot_img %s" % (
    os.path.join(_CUTTLEFISH_COMMON_BIN_PATH, "unpack_boot_image.py"),
    "%s -dest %s")
ACL_CMD = "setfacl -m g:libvirt-qemu:rw %s"

logger = logging.getLogger(__name__)


class RemoteImageLocalInstance(local_image_local_instance.LocalImageLocalInstance):
    """Create class for a remote image local instance AVD.

    RemoteImageLocalInstance just defines logic in downloading the remote image
    artifacts and leverages the existing logic to launch a local instance in
    LocalImageLocalInstance.
    """

    def GetImageArtifactsPath(self, avd_spec):
        """Download the image artifacts and return the paths to them.

        Args:
            avd_spec: AVDSpec object that tells us what we're going to create.

        Raises:
            errors.NoCuttlefishCommonInstalled: cuttlefish-common doesn't install.

        Returns:
            Tuple of (local image file, host bins package) paths.
        """
        if not setup_common.PackageInstalled("cuttlefish-common"):
            raise errors.NoCuttlefishCommonInstalled(
                "Package [cuttlefish-common] is not installed!\n"
                "Please run 'acloud setup --host' to install.")

        avd_spec.image_download_dir = self._ConfirmDownloadRemoteImageDir(
            avd_spec.image_download_dir)

        image_dir = self._DownloadAndProcessImageFiles(avd_spec)
        launch_cvd_path = os.path.join(image_dir, "bin",
                                       constants.CMD_LAUNCH_CVD)
        if not os.path.exists(launch_cvd_path):
            raise errors.GetCvdLocalHostPackageError(
                "No launch_cvd found. Please check downloaded artifacts dir: %s"
                % image_dir)
        return image_dir, image_dir

    @utils.TimeExecute(function_description="Downloading Android Build image")
    def _DownloadAndProcessImageFiles(self, avd_spec):
        """Download the CF image artifacts and process them.

        Download from the Android Build system, unpack the boot img file,
        and ACL the image files.

        Args:
            avd_spec: AVDSpec object that tells us what we're going to create.

        Returns:
            extract_path: String, path to image folder.
        """
        cfg = avd_spec.cfg
        build_id = avd_spec.remote_image[constants.BUILD_ID]
        build_target = avd_spec.remote_image[constants.BUILD_TARGET]

        extract_path = os.path.join(
            avd_spec.image_download_dir,
            "acloud_image_artifacts",
            build_id)

        logger.debug("Extract path: %s", extract_path)
        # TODO(b/117189191): If extract folder exists, check if the files are
        # already downloaded and skip this step if they are.
        if not os.path.exists(extract_path):
            os.makedirs(extract_path)
            self._DownloadRemoteImage(cfg, build_target, build_id, extract_path)
            self._UnpackBootImage(extract_path)
            self._AclCfImageFiles(extract_path)

        return extract_path

    @staticmethod
    def _DownloadRemoteImage(cfg, build_target, build_id, extract_path):
        """Download cuttlefish package and remote image then extract them.

        Args:
            cfg: An AcloudConfig instance.
            build_target: String, the build target, e.g. cf_x86_phone-userdebug.
            build_id: String, Build id, e.g. "2263051", "P2804227"
            extract_path: String, a path include extracted files.
        """
        remote_image = "%s-img-%s.zip" % (build_target.split('-')[0],
                                          build_id)
        artifacts = [_CVD_HOST_PACKAGE, remote_image]

        build_client = android_build_client.AndroidBuildClient(
            auth.CreateCredentials(cfg))
        for artifact in artifacts:
            temp_filename = os.path.join(extract_path, artifact)
            build_client.DownloadArtifact(
                build_target,
                build_id,
                artifact,
                temp_filename)
            utils.Decompress(temp_filename, extract_path)
            try:
                os.remove(temp_filename)
                logger.debug("Deleted temporary file %s", temp_filename)
            except OSError as e:
                logger.error("Failed to delete temporary file: %s", str(e))

    @staticmethod
    def _UnpackBootImage(extract_path):
        """Unpack Boot.img.

        Args:
            extract_path: String, a path include extracted files.

        Raises:
            errors.BootImgDoesNotExist: boot.img doesn't exist.
            errors.UnpackBootImageError: Unpack boot.img fail.
        """
        bootimg_path = os.path.join(extract_path, _BOOT_IMAGE)
        if not os.path.exists(bootimg_path):
            raise errors.BootImgDoesNotExist(
                "%s does not exist in %s" % (_BOOT_IMAGE, bootimg_path))

        logger.info("Start to unpack boot.img.")
        try:
            subprocess.check_call(
                UNPACK_BOOTIMG_CMD % (bootimg_path, extract_path),
                shell=True)
        except subprocess.CalledProcessError as e:
            raise errors.UnpackBootImageError(
                "Failed to unpack boot.img: %s" % str(e))
        logger.info("Unpack boot.img complete!")

    @staticmethod
    def _AclCfImageFiles(extract_path):
        """ACL related files.

        Use setfacl so that libvirt does not lose access to this file if user
        does anything to this file at any point.

        Args:
            extract_path: String, a path include extracted files.

        Raises:
            errors.CheckPathError: Path doesn't exist.
        """
        logger.info("Start to acl files: %s", ",".join(_CF_IMAGES))
        for image in _CF_IMAGES:
            image_path = os.path.join(extract_path, image)
            if not os.path.exists(image_path):
                raise errors.CheckPathError(
                    "Specified file doesn't exist: %s" % image_path)
            subprocess.check_call(ACL_CMD % image_path, shell=True)
        logger.info("ACL files completed!")

    @staticmethod
    def _ConfirmDownloadRemoteImageDir(download_dir):
        """Confirm download remote image directory.

        If available space of download_dir is less than _REQUIRED_SPACE, ask
        the user to choose a different d/l dir or to exit out since acloud will
        fail to download the artifacts due to insufficient disk space.

        Args:
            download_dir: String, a directory for download and decompress.

        Returns:
            String, Specific download directory when user confirm to change.
        """
        while True:
            download_dir = os.path.expanduser(download_dir)
            if not os.path.exists(download_dir):
                answer = utils.InteractWithQuestion(
                    "No such directory %s.\nEnter 'y' to create it, enter "
                    "anything else to exit out[y/N]: " % download_dir)
                if answer.lower() == "y":
                    os.makedirs(download_dir)
                else:
                    print("Exiting acloud!")
                    sys.exit()

            stat = os.statvfs(download_dir)
            available_space = stat.f_bavail*stat.f_bsize/(1024)**3
            if available_space < _REQUIRED_SPACE:
                download_dir = utils.InteractWithQuestion(
                    _CONFIRM_DOWNLOAD_DIR % {"download_dir":download_dir,
                                             "available_space":available_space,
                                             "required_space":_REQUIRED_SPACE})
                if download_dir.lower() == "q":
                    print("Exiting acloud!")
                    sys.exit()
            else:
                return download_dir
