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
"""Tests for delete."""

import unittest
import subprocess
import mock

from acloud.delete import delete
from acloud.internal.lib import driver_test_lib
from acloud.internal.lib import utils
from acloud.list import list as list_instances
from acloud.public import report


# pylint: disable=invalid-name,protected-access,unused-argument,no-member
class DeleteTest(driver_test_lib.BaseDriverTest):
    """Test delete functions."""

    # pylint: disable=protected-access
    @mock.patch("os.path.exists", return_value=True)
    @mock.patch("subprocess.check_output")
    def testGetStopcvd(self, mock_subprocess, mock_path_exist):
        """Test _GetStopCvd."""
        mock_subprocess.side_effect = ["fake_id",
                                       "/tmp/bin/run_cvd"]
        expected_value = "/tmp/bin/stop_cvd"
        self.assertEqual(expected_value, delete._GetStopCvd())

    @mock.patch.object(delete, "_GetStopCvd", return_value="")
    @mock.patch("subprocess.check_call")
    def testDeleteLocalCuttlefishInstance(self, mock_subprocess,
                                          mock_get_stopcvd):
        """Test DeleteLocalCuttlefishInstance."""
        mock_subprocess.return_value = True
        instance_object = mock.MagicMock()
        instance_object.instance_dir = "fake_instance_dir"
        instance_object.name = "local-instance"
        delete_report = report.Report(command="delete")
        delete.DeleteLocalCuttlefishInstance(instance_object, delete_report)
        self.assertEqual(delete_report.data, {
            "deleted": [
                {
                    "type": "instance",
                    "name": "local-instance",
                },
            ],
        })
        self.assertEqual(delete_report.status, "SUCCESS")

    @mock.patch("acloud.delete.delete.adb_tools.AdbTools")
    def testDeleteLocalGoldfishInstanceSuccess(self, mock_adb_tools):
        """Test DeleteLocalGoldfishInstance."""
        mock_instance = mock.Mock(adb_port=5555,
                                  device_serial="serial",
                                  instance_dir="/unit/test")
        # name is a positional argument of Mock().
        mock_instance.name = "unittest"

        mock_adb_tools_obj = mock.Mock()
        mock_adb_tools.return_value = mock_adb_tools_obj
        mock_adb_tools_obj.EmuCommand.return_value = 0

        delete_report = report.Report(command="delete")
        delete.DeleteLocalGoldfishInstance(mock_instance, delete_report)

        mock_adb_tools_obj.EmuCommand.assert_called_with("kill")
        mock_instance.DeleteCreationTimestamp.assert_called()
        self.assertEqual(delete_report.data, {
            "deleted": [
                {
                    "type": "instance",
                    "name": "unittest",
                },
            ],
        })
        self.assertEqual(delete_report.status, "SUCCESS")

    @mock.patch("acloud.delete.delete.adb_tools.AdbTools")
    def testDeleteLocalGoldfishInstanceFailure(self, mock_adb_tools):
        """Test DeleteLocalGoldfishInstance with adb command failure."""
        mock_instance = mock.Mock(adb_port=5555,
                                  device_serial="serial",
                                  instance_dir="/unit/test")
        # name is a positional argument of Mock().
        mock_instance.name = "unittest"

        mock_adb_tools_obj = mock.Mock()
        mock_adb_tools.return_value = mock_adb_tools_obj
        mock_adb_tools_obj.EmuCommand.return_value = 1

        delete_report = report.Report(command="delete")
        delete.DeleteLocalGoldfishInstance(mock_instance, delete_report)

        mock_adb_tools_obj.EmuCommand.assert_called_with("kill")
        mock_instance.DeleteCreationTimestamp.assert_called()
        self.assertTrue(len(delete_report.errors) > 0)
        self.assertEqual(delete_report.status, "FAIL")

    # pylint: disable=protected-access, no-member
    def testCleanupSSVncviwer(self):
        """test cleanup ssvnc viewer."""
        fake_vnc_port = 9999
        fake_ss_vncviewer_pattern = delete._SSVNC_VIEWER_PATTERN % {
            "vnc_port": fake_vnc_port}
        self.Patch(utils, "IsCommandRunning", return_value=True)
        self.Patch(subprocess, "check_call", return_value=True)
        delete.CleanupSSVncviewer(fake_vnc_port)
        subprocess.check_call.assert_called_with(["pkill", "-9", "-f", fake_ss_vncviewer_pattern])

        subprocess.check_call.call_count = 0
        self.Patch(utils, "IsCommandRunning", return_value=False)
        subprocess.check_call.assert_not_called()

    @mock.patch.object(delete, "DeleteInstances", return_value="")
    @mock.patch.object(delete, "DeleteRemoteInstances", return_value="")
    def testDeleteInstanceByNames(self, mock_delete_remote_ins,
                                  mock_delete_local_ins):
        """test DeleteInstanceByNames."""
        cfg = mock.Mock()
        # Test delete local instances.
        instances = ["local-instance-1", "local-instance-2"]
        self.Patch(list_instances, "FilterInstancesByNames", return_value="")
        delete.DeleteInstanceByNames(cfg, instances)
        mock_delete_local_ins.assert_called()

        # Test delete remote instances.
        instances = ["ins-id1-cf-x86-phone-userdebug",
                     "ins-id2-cf-x86-phone-userdebug"]
        delete.DeleteInstanceByNames(cfg, instances)
        mock_delete_remote_ins.assert_called()


if __name__ == "__main__":
    unittest.main()
