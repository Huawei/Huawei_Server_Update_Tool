#! /usr/bin/python
# -*- coding: UTF-8 -*-
"""
功    能： 带外BIOS和BMC的固件升级
版权信息：华为技术有限公司，版本所有(C) 2020-2019
修改记录：2019-10-16 12:00 白爱洁 bwx473592 创建
"""

from __future__ import print_function
import json
import time
import traceback

import utils
import zipfile
import xml.dom.minidom
import pickle
from cmd_progress import CmdProgress
from utils import *
import cmd_upgrade

running_item = None
item_name_format = None


class CmdUpdate(CmdProgress):
    """
    功能描述：带外BIOS和BMC的固件升级
    接口：none
    修改记录：none
    """

    def unzip_file(self, zip_path, tmp_purpose_dir_path):
        """

        Args:
                  zip_path            (str):   zip文件路径
                  purposeDirPath      (str):   目标目录
        Returns:
             解压之后的路径
        Raises:
            None
        Examples:
             None
        Author:  白爱洁 bwx473592
        Date: 2019/10/16 17:11
        """
        zFile = None
        purpose_dir_path = None
        update_code_message_key = KEY_UNZIP_SUCCEED
        try:
            fileSuffix = os.path.splitext(zip_path)[-1]
            if utils.compareStr(fileSuffix, ".zip"):
                dirName = os.path.basename(zip_path).replace(fileSuffix, "")
                purpose_dir_path = os.path.join(tmp_purpose_dir_path, dirName)
                if not os.path.exists(purpose_dir_path):
                    os.makedirs(purpose_dir_path)
                zFile = zipfile.ZipFile(zip_path, "r")
                # ZipFile.namelist(): 获取ZIP文档内所有文件的名称列表
                for fileM in zFile.namelist():
                    zFile.extract(fileM, purpose_dir_path)
            else:
                update_code_message_key = KEY_FILE_TYPE_ERROR
        except (OSError, IOError) as e:
            purpose_dir_path = None
            update_code_message_key = KEY_UNZIP_ERROR
            print("unexpect exception: " + str(e))
        finally:
            if zFile is not None:
                zFile.close()
        return update_code_message_key, purpose_dir_path

    def find_hpm(self, sourcedir, file_type):
        """

        Args:
                  sourcedir            (str):   文件所在的目录
                  file_type            (str):   文件后缀
        Returns:
              hpm包的路径
        Raises:
            None
        Examples:
             None
        Author:  白爱洁 bwx473592
        Date: 2019/10/16 17:11
        """
        file_walk = os.walk(sourcedir)
        for path, dir_list, file_list in file_walk:
            for file_name in file_list:
                fileSuffix = os.path.splitext(file_name)[-1]
                if utils.compareStr(fileSuffix, "." + file_type):
                    return os.path.join(path, file_name)
        return None

    def get_node_value(self, child_node, name):
        """

        Args:
                  child_node            (class):   child_node 节点
                  name                  (str):     节点名
        Returns:
             value 节点名对应的值
        Raises:
            None
        Examples:
             None
        Author:  白爱洁 bwx473592
        Date: 2019/10/16 17:11
        """
        if child_node is None:
            return None
        value = None
        index = 0
        temp_list = child_node.getElementsByTagName(name)
        if utils.list_subscript_crossing(temp_list, index):
            moudle_name = temp_list[index]
            child_nodes = moudle_name.childNodes
            if utils.list_subscript_crossing(child_nodes, index):
                value = child_nodes[index].data
        return value

    def get_version_data(self, file_path):
        """

        Args:
                  file_path            (str):   version.xml 的文件路径
        Returns:
             version.xml 部分内容的键值对
        Raises:
            None
        Examples:
             None
        Author:  白爱洁 bwx473592
        Date: 2019/10/16 17:11
        """
        version_data = {}
        doc = xml.dom.minidom.parse(file_path)
        collection = doc.documentElement
        firmware_package_node = collection.getElementsByTagName("Package")
        for child_node in firmware_package_node:
            type = self.get_node_value(child_node, "Module")
            version_data["Module"] = type
            version_data["Version"] = self.get_node_value(child_node, "Version")
            version_data["SupportModelUID"] = self.get_node_value(child_node, "SupportModelUID")
            time_out = self.get_node_value(child_node, "MaxUpgradeTime")
            # modify : DTS2019102310600 2019/10/24 整改升级成功的提示信息
            if time_out is None or re.match("^[0-9]+$", time_out) is None:
                if type.lower() == TYPE_BIOS.lower():
                    time_out = UPGRADE_TIME_OUT.get(TYPE_BIOS)
                elif type.lower() == TYPE_BMC.lower():
                    time_out = UPGRADE_TIME_OUT.get(TYPE_BMC)
            else:
                time_out = int(time_out)
            version_data["MaxUpgradeTime"] = time_out
        return version_data

    def init_dict_item(self, arg_type, arg_hpm_path, version_data):
        """

        Args:
                  arg_type                (str):   控制台输入的升级类型（BIOS/BMC）
                  arg_hpm_path            (str):   hpm包的路径
                  version_data            (dict):   version.xml中的键值对
        Returns:
             单个固件包中hpm文件的信息 data
        Raises:
            None
        Examples:
             None
        Author:  白爱洁 bwx473592
        Date: 2019/10/16 17:11
        """
        item_type = {
            "BMC": TYPE_BMC,
            'BIOS': TYPE_BIOS,
        }
        item_name = {
            "BMC": "FW-iBMC",
            'BIOS': 'FW-Bios',
        }
        item = {}
        item["type"] = item_type[arg_type]
        item["location"] = arg_hpm_path
        item["name"] = item_name[arg_type]
        item["version"] = version_data["Version"]
        item["MaxUpgradeTime"] = version_data["MaxUpgradeTime"]
        return item

    def get_data(self, arg_type, hpm_path, version_data):
        """

        Args:
                  arg_type            (str):   控制台输入的升级类型（BIOS/BMC）
                  hpm_path            (str):   hpm包的路径
                  version_data        (dict):  解析version.xml 所得到字典类型的值
        Returns:
             多个固件包中hpm文件的信息 data
        Raises:
            None
        Examples:
             None
        Author:  白爱洁 bwx473592
        Date: 2019/10/16 17:11
        """
        data = {MODE_OUTBAND: []}
        item = self.init_dict_item(arg_type, hpm_path, version_data)
        data[MODE_OUTBAND].append(item)
        return data

    def get_body(self, arg_type, data):
        """

        Args:
                  arg_type            (str):   控制台输入的升级类型（BIOS or BMC）
                  data                (list):  固件包中hpm文件的信息
        Returns:
             body字典类型 存储升级任务的信息
        Raises:
            None
        Examples:
             None
        Author:  白爱洁 bwx473592
        Date: 2019/10/16 17:11
        """
        body = {}
        body["taskid"] = arg_type
        body["data"] = data
        body["done"] = []
        body["resetos"] = True
        return body

    def init_hsu_upgrade_dat(self, data):
        """

        Args:
                  data            (dict):   待写入文件的数据
        Returns:
             None
        Raises:
            None
        Examples:
             None
        Author:  白爱洁 bwx473592
        Date: 2019/10/16 17:11
        """
        try:
            with open("hsu_upgrade.dat", "wb") as f:
                pickle.dump(data, f)
        except IOError as e:
            print("Unexpect exception: " + str(e))
        finally:
            if f is not None:
                f.close()

    def check(self, version_data, check_data):
        """

        Args:
                  version_data            (dict):    version.xml中的数据
                  check_data              (dict):    校验数据
        Returns:
             是否校验成功
        Raises:
            None
        Examples:
             None
        Author:  白爱洁 bwx473592
        Date: 2019/10/16 17:11
        """
        version_moudle = version_data["Module"]
        arg_type = check_data["Type"]
        check_uid = check_data["UID"]
        version_uid = version_data["SupportModelUID"]
        if version_moudle is None \
                or arg_type is None \
                or version_uid is None \
                or check_uid is None \
                or version_moudle.lower().find(arg_type.lower()) < 0 \
                or version_uid.find(check_uid) < 0:
            # modify : DTS2019102207058 2019/10/22 整改升级失败的提示信息
            code, message = get_code_message(KEY_TYPE_UID_NOT_MATCH)
            self.print_error_message(code, message)
            return False
        return True

    def print_error_message(self, rc, message):
        """

        Args:
                  rc            (int):   错误码
                  message       (str):   错误信息
        Returns:
             None
        Raises:
            None
        Examples:
             None
        Author:  白爱洁 bwx473592
        Date: 2019/10/16 17:11
        """
        print(rc, message)
        if self.is_console_user():
            print(message, file=self.sysstds[0])
            self.error = True
        else:
            self._error(rc, message)

    def run(self):
        zip_path = self.args.options[0]
        arg_type = self.args.type
        update_code_message_key, unzip_dir = self.unzip_file(zip_path, "/tmp/")
        print(update_code_message_key, unzip_dir)
        TEMP_PATH["UNZIP_PATH"] = unzip_dir
        if update_code_message_key != KEY_UNZIP_SUCCEED or unzip_dir is None:
            # modify : DTS2019102207058 2019/10/22 整改升级失败的提示信息
            code, message = get_code_message(update_code_message_key)
            self.print_error_message(code, message)
            # modify : DTS2019102205116 2019/10/22 修改os._exit()参数0应该被给予的异常，
            # 同时不应该让程序终止，因为程序还需走_del_函数来释放session，所以使用return
            return

        version_xml_path = os.path.join(unzip_dir, "version.xml")
        hpm_path = self.find_hpm(unzip_dir, "hpm")

        if not os.path.isfile(version_xml_path) or not hpm_path:
            # modify : DTS2019102207058 2019/10/22 整改升级失败的提示信息
            code, message_tmp = get_code_message(KEY_FIRMWARE_PACKAGE_ERROR)
            self.print_error_message(code, message_tmp)
            # modify : DTS2019102205116 2019/10/22 修改os._exit()参数0应该被给予的异常，
            # 同时不应该让程序终止，因为程序还需走_del_函数来释放session，所以使用return
            return

        uid = self._get_product_unique_id()
        # modify : DTS2019102207058 2019/10/22 整改升级失败的提示信息
        if uid is None:
            code, message_tmp = get_code_message(KEY_GET_UID_ERROR)
            self.print_error_message(code, message_tmp)
            return

        check_data = {"UID": uid, "Type": arg_type}
        version_data = self.get_version_data(version_xml_path)
        print("version_data:", version_data)
        print("check_data:", check_data)
        if not self.check(version_data, check_data):
            return

        data = self.get_data(arg_type, hpm_path, version_data)
        body = self.get_body(arg_type, data)
        self.init_hsu_upgrade_dat(body)

        # step3: get progress
        while utils.update_time_out is False:
            try:
                task_finished, reset_os = self.get_task_progress(body["taskid"], UPGRADE_METHOD["LOCAL"])
                print("[%s] task finished: %s, progress result: %s" % (
                    now(), task_finished, self.result))

                if task_finished:
                    print("[%s] local upgrade final result: %s" % (
                        now(), json.dumps(self.result)))
                    print("[%s] local upgrade job finished " % (now()))

                    if self.is_console_user():
                        self.error = True
                        cmd_upgrade.print_readable_progress(self.result, stream=self.sysstds[0])
                    else:
                        self.error = False
                        results = self.result['data']
                        all_completed = cmd_upgrade.is_all_upgrade_completed(results)
                        if not all_completed:
                            # modify : DTS2019102207058 2019/10/22 整改升级失败的提示信息
                            rc = self.result.get("rc")
                            if rc is not None and rc != 0:
                                self._error(rc, json.dumps(results))
                            else:
                                self._error(10, json.dumps(results))
                    return
                else:
                    if self.is_console_user() \
                            and len(self.result["data"]) > 0:
                        cmd_upgrade.print_readable_progress(self.result,
                                                            stream=self.sysstds[0])
                # wait 2 second between query task progress command
                time.sleep(2)
            except Exception as e:
                print("unexpect exception: " + str(e))
                # disable delegated command's output
                # command.flushed = True
                # catch un-handled exceptions, and mark task failed
                traceback.print_exc()
                self._error(10, e.message)
            finally:
                if self.is_console_user():
                    print("\n".join([" " for i in range(1, 10)]))

    def __del__(self):
        super(CmdUpdate, self).__del__()
        unzip_path = TEMP_PATH["UNZIP_PATH"]
        if unzip_path is not None and os.path.exists(unzip_path):
            try:
                import shutil
                shutil.rmtree(TEMP_PATH["UNZIP_PATH"])
            except OSError as e:
                print("Unexpect exception: " + str(e))
