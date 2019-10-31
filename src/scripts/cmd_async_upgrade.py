# -*- coding: UTF-8 -*-

import pickle
import utils
import time
from cStringIO import StringIO
import json
import constants
from utils import *
from cmd_base import CmdBase

'''
###############################################################################
# Call method：hsu upgrade [<name> <version>,...]
# Input：
#   name    hsu verify return list.<driver name>
#   version hsu verify return list.<vlist> any one
# Output：
#   {
#       "taskid":"<task-id>"
#   }
#   taskid  return task id (string type), need call hsu progress <taskid> for retrieve progress info
###############################################################################
'''


class CmdAsyncUpgrade(CmdBase):
    # upload single file to iBMC server (through redfish interface)
    def _uploadFile2BMC(self, path):
        print("_uploadFile2BMC")
        url = "/redfish/v1/UpdateService/FirmwareInventory"
        if not os.path.isfile(path):
            return None
        name = self._getName(path)

        fin = open(path, 'rb')
        try:
            files = {'imgfile': (name, fin, "multipart/form-data",
                                 {'user_name': self.client.username})}
            if files is None:
                return None
            resp = self.client.create_resource(url, files=files)
            # Return as below:
            #   {'status_code': 202, 'resource': '{"success":true}', 'headers': {'content-length': '16', ...}}
            print("resp:", resp)
            if resp is None:
                return None
            if resp.get('status_code') != 202:
                # modify : DTS2019102207058 2019/10/22 整改升级失败的提示信息
                message_resolution_dict, message_find = utils.key_dic(resp, "MessageId")
                if message_find:
                    message_tmp = message_resolution_dict.get("Message")
                    print("message_tmp:", message_tmp)
                    resolution = message_resolution_dict.get("Resolution")
                    print("resolution:", resolution)
                    if message_tmp is not None or resolution is not None:
                        message_tmp = "%s failed to upload hpm file \nErrorMessage: %s \nResolution : %s" % (
                            UPDATE_FAIL, message_tmp, resolution)
                        utils.set_code_message(UPLOAD_FIRMWARE_PACKAGE_ERROR, message_tmp)
                return None
            return name
        except Exception as e:
            print("unexpect exception: ", str(e))
        finally:
            fin.close()

    # check user inputs, and get upgrade list (no inputs means upgrade all to latest version)
    def _getUpgradeList(self):
        n = len(self.args.options)
        if 0 != (n % 2):
            self._error(1, "Invalid argument pair")
            return None
        # Arrange name/version options into K-V map
        kvs = {}
        for i in range(0, len(self.args.options), 2):
            kvs[self.args.options[i]] = self.args.options[i + 1]
        # Try load verify command cached data
        try:
            with open("hsu_verify.dat", "rb") as file:
                data = pickle.load(file)
        except:
            print("File hsu_verify.data not exists, run verify before upgrade")
            self._error(2, "Need run verify first")
            return None
        # Find input name and check it
        kvp = {}
        if len(kvs) > 0:
            for k, v in kvs.items():
                found = False
                for k2, v2 in data.items():
                    if k != k2:
                        continue
                    for item in v2["vlist2"]:
                        if item["version"] != v:
                            continue
                        found = True
                        value = item.copy()
                        value["mode"] = v2["mode"]
                        value["type"] = v2["type"]
                        kvp[k] = value
                        break
                    break
                if not found:
                    self._error(3, "Invalid name (%s) or version (%s)" % (k, v))
                    return None
        else:  # No parameters, means upgrade all verified data
            for k2, v2 in data.items():
                if should_upgrade_item(v2):
                    v = v2["v-max"]
                    for item in v2["vlist2"]:
                        if item["version"] != v:
                            continue
                        value = item.copy()
                        value["mode"] = v2["mode"]
                        value["type"] = v2["type"]
                        kvp[k2] = value
                        break
        # sort upgrade items, according 2018/06/13 meeting, upgrade follow as below:
        #   driver array
        #   inband array
        #   outband array(3.1 BIOS, 3.2 iBMC)
        print("=====> Upgrade list (unsorted) <=====")
        print(json.dumps(kvp, sort_keys=True, indent=4, separators=(',', ': ')))
        print("=====================================")
        result = {}
        items = []

        # Qianbiao.NG  ...
        for k, v in kvp.items():
            if v["mode"] == MODE_DRIVER:
                item = {"name": k, "version": v["version"],
                        "location": v["location"], "type": v["type"]}
                items.append(item)
        if len(items) > 0:
            result[MODE_DRIVER] = items
        items = []
        for k, v in kvp.items():
            if v["mode"] == MODE_INBAND:
                item = {"name": k, "version": v["version"],
                        "location": v["location"], "type": v["type"]}
                items.append(item)
        if len(items) > 0:
            result[MODE_INBAND] = items
        items = []
        for k, v in kvp.items():
            if v["mode"] == MODE_OUTBAND and v["type"] == TYPE_BIOS:
                item = {"name": k, "version": v["version"],
                        "location": v["location"],
                        "type": TYPE_BIOS}
                items.append(item)
        for k, v in kvp.items():
            if v["mode"] == MODE_OUTBAND and v["type"] == TYPE_BMC:
                item = {"name": k, "version": v["version"],
                        "location": v["location"],
                        "type": TYPE_BIOS}
                items.append(item)
        if len(items) > 0:
            result[MODE_OUTBAND] = items
        return result

    # Upgrade driver function (use rpm tool), errors will fill in elist if occur
    def _upgradeDriver(self, item, elist):
        self._downHttpFile(item["location"], "hsu_upgrade.rpm")
        if is_drive_gpgcheck_enabled() and not is_rpm_valid("hsu_upgrade.rpm"):
            elist[item["name"]] = "RPM package gpg md5 not ok"
            return False

        p = subprocess.Popen("rpm --force --nodeps -i hsu_upgrade.rpm",
                             shell=True,
                             stdout=subprocess.PIPE,
                             stderr=subprocess.STDOUT)
        out, err = p.communicate()
        if 0 != p.returncode:
            elist[item["name"]] = str(out).strip().decode()
            return False
        return True

    # Get inband base URI function (prefix URI)
    def _inbandGetBaseURI(self):
        url = "/redfish/v1" + "/Managers"
        ret = self.client.get_resource(url)
        if None != ret and 200 == ret["status_code"] and len(
                ret["resource"]["Members"]) > 0:
            return ret["resource"]["Members"][0][ODATA_ID_KEY]
        return ''

    # Enable/Disable inband SP Service
    def _inbandSetSPService(self, spEnable, restartTimeout=30,
                            deployTimeout=7200, deployStatus=True):
        url = self._inbandGetBaseURI() + "/SPService"
        # Get/Update If-Match value
        self.client.get_resource(url)
        payload = {"SPStartEnabled": spEnable,
                   "SysRestartDelaySeconds": restartTimeout,
                   "SPTimeout": deployTimeout, "SPFinished": deployStatus}
        ret = self.client.set_resource(url, payload)
        if None != ret and 200 == ret["status_code"]:
            return True
        return False

    # Get inband FW update base URI
    def _inbandGetFwUpdateURI(self):
        url = self._inbandGetBaseURI() + "/SPService/SPFWUpdate"
        ret = self.client.get_resource(url)
        if None != ret and 200 == ret["status_code"] and len(
                ret["resource"]["Members"]) > 0:
            return ret["resource"]["Members"][0][ODATA_ID_KEY]
        return None

    # Do inband FW upgrade action, upload files to iBMC, needn't wait
    # until OS restarted, it will do automatically by iBMC
    def upgradeInbandFW(self, base, item, elist):
        subprocess.call("rm -rf tmp && mkdir tmp >/dev/null 2>/dev/null",
                        shell=True)
        self._downHttpFile(item["location"], "tmp/hsu_upgrade.rpm")
        if is_firmware_gpgcheck_enabled() and not is_rpm_valid("tmp/hsu_upgrade.rpm"):
            elist[item["name"]] = "RPM package gpg md5 not ok"
            return False
        # for tgz test only!!!
        if item["location"].lower().endswith(".tgz"):
            cmd = "cd tmp && tar -xvzf hsu_upgrade.rpm"
        else:
            cmd = "cd tmp && rpm2cpio hsu_upgrade.rpm | cpio -div"
        p = subprocess.Popen(cmd, shell=True, stdout=subprocess.PIPE,
                             stderr=subprocess.STDOUT)
        out, err = p.communicate()
        buf = StringIO(out)
        zip = asc = ""
        while True:
            s = buf.readline().strip()
            if len(s) <= 0:
                break
            s = "tmp/" + s
            if s.lower().endswith(".zip"):
                zip = s
            elif s.lower().endswith(".asc"):
                asc = s
        if len(zip) <= 0 or len(asc) <= 0:
            elist[item["name"]] = "Not found zip or asc in rpm file"
            return None
        nzip = self._uploadFile2BMC(zip)
        if None == nzip:
            elist[item["name"]] = "Failed to upload zip file"
            return None
        nasc = self._uploadFile2BMC(asc)
        if None == nasc:
            elist[item["name"]] = "Failed to upload asc file"
            return None
        payload = {'ImageURI': ('file:///tmp/web/' + nzip),
                   "SignalURI": ('file:///tmp/web/' + nasc),
                   "ImageType": "Firmware", "Parameter": "all",
                   "UpgradeMode": "Recover", "ActiveMethod": "OSRestart"}
        url = base + "/Actions/SPFWUpdate.SimpleUpdate"
        resp = self.client.create_resource(url, payload)
        if resp is None or 200 != resp["status_code"]:
            reason = resp["error"]["@Message.ExtendedInfo"][0]["Message"]
            elist[item["name"]] = reason
            return False

        # wait until firmware file transfer done
        count = 10
        while count > 0:
            print("try to get SPFWUpdate transfer file progress")
            transfer_resp = self.client.get_resource(base)
            filename = transfer_resp["resource"]["TransferFileName"]
            percent = transfer_resp["resource"]["TransferProgressPercent"]
            percent = percent if percent else "0"
            print("transfer file %s percent %s" % (nzip, percent))
            if nzip == filename:
                if 100 == percent:
                    print("transfer file %s finished" % nzip)
                    break
            count -= 1
            time.sleep(1)
        return True

    # Do outband FW upgrade, upload files to iBMC, and need check it is done cycle
    def upgradeOutbandFW(self, item, elist):
        url = "/redfish/v1/UpdateService/Actions/UpdateService.SimpleUpdate"
        subprocess.call("rm -rf tmp && mkdir tmp >/dev/null 2>/dev/null",
                        shell=True)
        self._downHttpFile(item["location"], "tmp/hsu_upgrade.rpm")
        if is_firmware_gpgcheck_enabled() and not is_rpm_valid("tmp/hsu_upgrade.rpm"):
            elist[item["name"]] = "RPM package gpg md5 not ok"
            return None

        cmd = "cd tmp && rpm2cpio hsu_upgrade.rpm | cpio -div"
        p = subprocess.Popen(cmd, shell=True, stdout=subprocess.PIPE,
                             stderr=subprocess.STDOUT)
        out, err = p.communicate()
        buf = StringIO(out)
        hpm = ""
        while True:
            s = buf.readline().strip()
            if len(s) <= 0:
                break
            s = "tmp/" + s
            if s.lower().endswith(".hpm"):
                hpm = s
        if len(hpm) <= 0:
            elist[item["name"]] = "Not found hpm in rpm file"
            return None
        nhpm = self._uploadFile2BMC(hpm)
        if nhpm is None:
            elist[item["name"]] = "Failed to upload hpm file"
            return None
        payload = {'ImageURI': ('/tmp/web/' + nhpm)}
        resp = self.client.create_resource(url, payload)
        # Return as below:
        #   {'status_code': 202, 'resource': {u'@odata.type': u'#Task.v1_0_2.Task', u'Name': u'Upgarde Task',
        #   u'TaskState': u'Running', u'Messages': [], u'@odata.id': u'/redfish/v1/TaskService/Tasks/2',
        #   u'@odata.context': u'/redfish/v1/$metadata#TaskService/Tasks/Members/$entity',
        #   u'StartTime': u'2018-06-26T02:47:16+00:00', u'Id': u'2',
        #   u'Oem': {u'Huawei': {u'TaskPercentage': None}}}, 'headers': {'content-length': '315', ...}}
        if 202 != resp["status_code"]:
            msg = 'Unknown'
            if resp.has_key("resource") and resp["resource"].has_key("Message"):
                msg = resp["resource"]["Message"]
            elist[item["name"]] = "Failed to upgrade outband FW: " + msg
            return None
        return resp["resource"][ODATA_ID_KEY]

    def update_outband_fw(self, item, error_list):
        """

        Args:
                  item            (dict):   升级包信息 eg:{'version': u'6.78', 'type': 'bios',
                                            'location': '/tmp/2288H V5_5288 V5-BC1SPSCB03-10GE SFP -BIOS-V678/biosimage.hpm',
                                            'name': u'FW-Bios'}
                  error_list           (dict):   错误信息
        Returns:
             任务id eg:/redfish/v1/TaskService/Tasks/2
        Raises:
            None
        Examples:
             None
        Author:  白爱洁 bwx473592
        Date: 2019/10/16 17:11
        """
        url = "/redfish/v1/UpdateService/Actions/UpdateService.SimpleUpdate"
        nhpm = self._uploadFile2BMC(item.get("location"))
        item_name = item.get("name")
        if nhpm is None and item_name is not None:
            # modify : DTS2019102207058 2019/10/22 整改升级失败的提示信息
            code, message = get_code_message(UPLOAD_FIRMWARE_PACKAGE_ERROR)
            error_list[item_name] = message
            self.result["rc"] = code
            return None

        payload = {'ImageURI': ('/tmp/web/' + nhpm)}
        resp = self.client.create_resource(url, payload)
        print("payload:", resp)
        if resp is None or resp.get("resource") is None:
            return None
        # Return as below:
        #   {'status_code': 202, 'resource': {u'@odata.type': u'#Task.v1_0_2.Task', u'Name': u'Upgarde Task',
        #   u'TaskState': u'Running', u'Messages': [], u'@odata.id': u'/redfish/v1/TaskService/Tasks/2',
        #   u'@odata.context': u'/redfish/v1/$metadata#TaskService/Tasks/Members/$entity',
        #   u'StartTime': u'2018-06-26T02:47:16+00:00', u'Id': u'2',
        #   u'Oem': {u'Huawei': {u'TaskPercentage': None}}}, 'headers': {'content-length': '315', ...}}
        if 202 != resp.get("status_code"):
            msg = 'Unknown'
            resp_resource = resp.get("resource")
            if resp_resource is not None:
                msg = resp_resource.get("Message", 'Unknown')
            # modify : DTS2019102207058 2019/10/22 整改升级失败的提示信息
            message = "%s failed to upgrade outband FW: %s" % (UPDATE_FAIL, str(msg))
            set_code_message(UPDATE_OUTBAND_FW_ERROR, message)
            code, message = get_code_message(UPDATE_OUTBAND_FW_ERROR)
            error_list[item_name] = message
            self.result["rc"] = code
            return None
        return resp.get("resource").get(ODATA_ID_KEY)

    def run(self):
        # Collect upgrade list and sort it by rules
        data = self._getUpgradeList()
        print("=====> Upgrade list (sorted) <======")
        print(
            json.dumps(data, sort_keys=True, indent=4, separators=(',', ': ')))
        print("====================================")
        if data is None:
            return
        # Enter install step
        try:
            # Calculate all update counts
            n = 0
            if data.has_key(MODE_DRIVER):
                n += len(data[MODE_DRIVER])
            if data.has_key(MODE_INBAND):
                n += len(data[MODE_INBAND])
            if data.has_key(MODE_OUTBAND):
                n += len(data[MODE_OUTBAND])
            # upgrade drivers and remove it from list
            item = {}
            done = []
            failed_msg = {}
            bNeedResetOS = False

            if constants.MODE_DRIVER in data:  # Upgrade driver(s) if exists
                for item in data[MODE_DRIVER]:
                    installed, result = is_installed(done, item)
                    if installed:
                        done.append(result)
                        continue

                    if self._upgradeDriver(item, failed_msg):
                        done.append(get_success_msg(item))
                    else:
                        message = failed_msg[item["name"]]
                        done.append(get_failed_msg(item, message))

            if constants.MODE_INBAND in data:  # Upgrade Inband FW(s) if exists
                sBaseURI = self._inbandGetFwUpdateURI()
                bNeedResetOS = self._inbandSetSPService(True)
                for item in data[MODE_INBAND]:
                    installed, result = is_installed(done, item)
                    if installed:
                        done.append(result)
                        continue

                    if sBaseURI is not None and bNeedResetOS:
                        if self.upgradeInbandFW(sBaseURI, item, failed_msg):
                            done.append(get_success_msg(item))
                        else:
                            message = failed_msg[item["name"]]
                            done.append(get_failed_msg(item, message))
                    else:
                        # Failed to enable SP, ignore all inband FW upgrade
                        message = "Failed to enable SP"
                        done.append(get_failed_msg(item, message))

            ################################################################
            # Qianbiao.NG outband upgrade has been moved to progress task #
            ###############################################################

            task_id = time.strftime("%Y%m%d%H%M%S")
            # Create new hsu_upgrade.dat file for store tasks id
            body = {"taskid": task_id, "n": n, "data": data, "done": done,
                    "resetos": bNeedResetOS}
            with open("hsu_upgrade.dat", "wb") as f:
                pickle.dump(body, f)
            # always return taskid for caller can call progress command
            # for retrieve upgrade progress list
            if True:  # bHasSuccess:
                data = {"taskid": task_id}
                if len(failed_msg) > 0:
                    data["message"] = "Failed to install %s package(s): %s" % (
                        str(failed_msg.keys()), str(failed_msg.values()))
                self.result["data"] = data
            else:
                self._error(9, "Failed to install %s package(s): %s" % (
                    str(failed_msg.keys()), str(failed_msg.values())))
        except IOError as e:
            print("Unexpect exception: " + str(e))
        finally:
            subprocess.call("rm -rf tmp >/dev/null 2>/dev/null", shell=True)
            subprocess.call("rm -rf hsu_verify.dat >/dev/null 2>/dev/null",
                            shell=True)
            subprocess.call("rm -rf hsu_upgrade.rpm >/dev/null 2>/dev/null",
                            shell=True)
