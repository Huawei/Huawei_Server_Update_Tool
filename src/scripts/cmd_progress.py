# -*- coding: UTF-8 -*-

import pickle
import time

from cmd_async_upgrade import CmdAsyncUpgrade
import utils
from utils import *

'''
###############################################################################
# Call method：hsu progress <task-id>
# Input：
#   task-id hsu upgrade return taskid
# Output：
#   {
#       "<name>":{
#           "state":"<TaskState>",
#           "percent":<value>
#       },
#       ...
#   }
#   state   see redfish API document
#   percent 0-100
###############################################################################
'''


class CmdProgress(CmdAsyncUpgrade):
    # get task progress info by redfish interface
    def query_single_task_progress(self, upgrading, max_wait_sec=300):
        print("query_single_task_progress")
        result = get_failed_msg(upgrading)
        result["percent"] = 100

        start_on = time.time()
        while True:
            if (time.time() - start_on) >= max_wait_sec:
                print("query single task progress time out")
                break
            resp = self.client.get_resource(upgrading["task_id"])
            print(resp)
            # Network not ready? or NoValidSession need try again and again ...
            if resp is None or not isinstance(resp, dict):
                time.sleep(1)
                continue

            # or "Exception" == resp['resource']['TaskState']:
            if 200 != resp.get("status_code"):
                break
            if RESULT_COMPLETE == resp['resource']['TaskState']:
                result = get_success_msg(upgrading)
                result["percent"] = 100
                break
            progress = 0
            try:
                percent = resp['resource']['Oem']['Huawei']['TaskPercentage']
                percent = percent.replace("%", "")
                progress = int(percent)
                if progress >= 100:  # check the task is done?
                    progress = 99
            except (AttributeError, KeyError) as e:
                print("unexpect exception: " + str(e))
            result["state"] = resp['resource']['TaskState']
            result["percent"] = progress
            break
        return result

    def run(self):
        if len(self.args.options) < 1:
            self._error(1, "Usage: hsu progress <task-id>")
            return
        taskid = self.args.options[0]
        task_finished, reset_os = self.get_task_progress(taskid)
        if task_finished and reset_os:
            self._flush()
            # Need reboot X86 OS for active inband upgrades
            print("Rebooting X86 OS, need remove it under release mode!!!")
            # subprocess.call("reboot >/dev/null 2>/dev/null", shell=True)

    def compare_bmc_version(self, item):
        """compare current bmc version with item's expect version

        :param item:
        :return: true if version equals else false
        """
        time.sleep(60)
        current_time = time.time()
        get_bmc_url = "/redfish/v1/UpdateService/FirmwareInventory/ActiveBMC"
        while time.time() - current_time < TO_BMC_RESTART:
            try:
                response = self.client.get_resource(get_bmc_url)
                print(response)
                if str(response).find('NoValidSession') >= 0:
                    self.inner_establish_connection()
                elif response is not None and response.get("status_code") == 200:
                    return item["version"] == response.get("resource").get("Version")
            except Exception as e:
                print("Failed to get BMC version, reason: " + str(e))
            time.sleep(2)

    def get_task_progress(self, taskid, upgrade_method=None):
        # Load cached tasks info
        try:
            with open("hsu_upgrade.dat", "rb") as f:
                data = pickle.load(f)
            if data["taskid"] != taskid:
                raise Exception("Invalid taskid")
        except:
            # modify : DTS2019102207058 2019/10/22 整改升级失败的提示信息
            print("%s invalid task id: %s" % (UPDATE_FAIL, taskid))
            self._error(2, "%s invalid taskid, need run update -l and update again" % UPDATE_FAIL)
            return

        progress = {}  # progress item
        is_updating = False  # identify any firmware is updating
        if "upgrading" in data and "task_id" in data["upgrading"]:
            # Retrieve current upgrading item state and percentage
            upgrading_item = data["upgrading"]

            # timeout validation
            item_type = upgrading_item["type"]
            cost_seconds = time.time() - upgrading_item["start_on"]
            time_out = upgrading_item.get("MaxUpgradeTime")
            print("time_out:", time_out)
            print("cost_seconds", cost_seconds)
            if time_out is not None and cost_seconds > time_out:
                # modify : DTS2019102207058 2019/10/22 整改升级成功的提示信息
                message_tmp = "%s update timeout, limit %ds" % (UPDATE_FAIL, time_out)
                set_code_message(KEY_TIME_OUT, message_tmp)
                code, message_tmp = get_code_message(KEY_TIME_OUT)
                self.result["rc"] = code
                data["done"].append(get_failed_msg(upgrading_item, message_tmp))
                data.pop("upgrading", None)
                utils.update_time_out = True
            else:
                result = self.query_single_task_progress(upgrading_item)
                is_updating = (result["percent"] < 100)
                if not is_updating:
                    data.pop("upgrading", None)
                    success = result["state"] = RESULT_COMPLETE
                    if item_type == TYPE_BIOS and success and result.get("message") is not None:
                        # modify : DTS2019102207058 2019/10/22 整改升级成功的提示信息
                        result["message"] = "%s,%s" % (result.get("message"), "need to"
                                                                              " restart the system to take effect")
                        data["done"].append(result)
                    # when bmc upgrade success, compare bmc version
                    elif item_type == TYPE_BMC and success:
                        version_match = self.compare_bmc_version(upgrading_item)
                        data["done"].append(result if version_match else
                                            get_failed_msg(upgrading_item))
                    else:
                        data["done"].append(result)
                else:
                    progress[result["name"]] = {"state": result["state"],
                                                "message": result["message"],
                                                "percent": result["percent"]}

        items = data["data"]
        if MODE_OUTBAND not in data["data"]:
            items[MODE_OUTBAND] = []

        # if no item is upgrading and got items to be upgraded
        while not is_updating and len(items[MODE_OUTBAND]) > 0:
            failed_msg = {}
            item = items[MODE_OUTBAND][0]
            items[MODE_OUTBAND].remove(item)

            # check whether the item has been upgraded
            installed, result = is_installed(data["done"], item)
            if installed:
                data["done"].append(result)
                continue

            start_on = time.time()  # task start on(used for timeout checking)
            if upgrade_method == UPGRADE_METHOD["LOCAL"]:
                taskid = self.update_outband_fw(item, failed_msg)
            else:
                taskid = self.upgradeOutbandFW(item, failed_msg)

            if taskid is None:  # failed
                message = failed_msg[item["name"]]
                data["done"].append(get_failed_msg(item, message))
            else:  # mark current item as upgrading
                upgrading = item.copy()
                upgrading["start_on"] = start_on  # upgrading start on
                upgrading["task_id"] = taskid
                data["upgrading"] = upgrading
                progress[item["name"]] = {"state": "Running",
                                          "message": "Running",
                                          "percent": 0}
                break

        # add finished item's progress
        print("done:", data["done"])
        for item in data["done"]:
            progress[item["name"]] = {"state": item["state"],
                                      "message": item["message"],
                                      "percent": 100}

        # add pending item's progress
        if MODE_OUTBAND in items:
            for item in items[MODE_OUTBAND]:
                progress[item["name"]] = {"state": "Pending",
                                          "message": "Pending",
                                          "percent": 0}

        # checking whether all item has be processed
        print("is_updating:", is_updating)
        finished = (not is_updating
                    and ("upgrading" not in data or data["upgrading"] is None)
                    and len(items[MODE_OUTBAND]) == 0)
        if finished:
            subprocess.call("rm -rf tmp >/dev/null 2>/dev/null", shell=True)
            subprocess.call("rm -rf hsu_upgrade.dat >/dev/null 2>/dev/null",
                            shell=True)
        else:
            with open("hsu_upgrade.dat", "wb") as f:
                pickle.dump(data, f)
        self.result["data"] = progress
        return finished, data["resetos"]
