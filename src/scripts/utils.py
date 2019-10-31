# -*- coding: UTF-8 -*-
import ConfigParser
import os
import re
import subprocess
from datetime import datetime
from string import lower

from constants import *

pidfile = "/tmp/hsu-tool.pid"
update_time_out = False

update_code_message = {
    KEY_FILE_TYPE_ERROR: {UPDATE_CODE: 5, UPDATE_MESSAGE: "%s please enter a zip type firmware package" % UPDATE_FAIL},
    KEY_UNZIP_ERROR: {UPDATE_CODE: 6, UPDATE_MESSAGE: "%s decompression failed" % UPDATE_FAIL},
    KEY_FIRMWARE_PACKAGE_ERROR: {UPDATE_CODE: 7,
                                 UPDATE_MESSAGE: "%s please check if your firmware package is correct" % UPDATE_FAIL},
    KEY_TYPE_UID_NOT_MATCH: {UPDATE_CODE: 8,
                             UPDATE_MESSAGE: "%s please confirm if the firmware package and firmware match" % UPDATE_FAIL},
    KEY_UNZIP_SUCCEED: {UPDATE_CODE: 200, UPDATE_MESSAGE: "decompression succeeded"},
    KEY_TIME_OUT: {UPDATE_CODE: 9, UPDATE_MESSAGE: "%s update timeout, limit %ds" % (UPDATE_FAIL, 0)},
    KEY_GET_UID_ERROR: {UPDATE_CODE: 10,
                        UPDATE_MESSAGE: "%s failed to get UID through redfish interface" % UPDATE_FAIL},
    ABNORMAL_EXIT_CODE: {UPDATE_CODE: -1, UPDATE_MESSAGE: "update failed"},
    UPLOAD_FIRMWARE_PACKAGE_ERROR: {UPDATE_CODE: 11, UPDATE_MESSAGE: "%s upload firmware package failed" % UPDATE_FAIL},
    UPDATE_OUTBAND_FW_ERROR: {UPDATE_CODE: 12, UPDATE_MESSAGE: "%s update outband fw failed" % UPDATE_FAIL},
    BMC_ERROR: {UPDATE_CODE: -2, UPDATE_MESSAGE: "%s could not connect to BMC now, please try later" % UPDATE_FAIL}
}


def now():
    return str(datetime.now().strftime("%Y-%m-%d %H:%M:%S"))


def create_pidfile():
    """
    create a pidfile for current progress
    :return: True if created, False if exists
    """
    if os.path.isfile(pidfile):
        print ("[%s] pidfile %s already exists" % (now(), pidfile))
        # if pidfile exists, then check if pid really running
        with open(pidfile, "r") as f:
            pid = f.read()
            if is_running(pid):
                print ("[%s] pidfile exists, pid is running" % now())
                return False
            else:
                print ("[%s] pid not exist, pidfile removed" % now())
                os.unlink(pidfile)

    pid = str(os.getpid())
    with open(pidfile, 'w') as f:
        f.write(pid)
        print ("[%s] pidfile %s created" % (now(), pidfile))
    return True


def remove_pidfile():
    print ("[%s] pidfile %s removed" % (now(), pidfile))
    os.unlink(pidfile)


def is_running(pid):
    return os.path.isdir('/proc/{}'.format(pid))


def get_code_message(update_code_message_key):
    """
    Function:
         获取UPDATE_CODE_MESSAGE错误码和错误信息
    Args:
              key            (str):   关键字
    Returns:
         code：                       信息码
         message：                    信息码对应的信息
    Raises:
        None
    Examples:
         None
    Author:  白爱洁 bwx473592
    Date: 2019/10/22 16:29
    """
    uid_match = update_code_message.get(update_code_message_key)
    code = 0
    message = ""
    if uid_match is not None:
        code = uid_match.get(UPDATE_CODE, 0)
        message = uid_match.get(UPDATE_MESSAGE, "")
    return code, message


def set_code_message(update_code_message_key, message):
    """
    Function:
         设置UPDATE_CODE_MESSAGE错误码对应的错误信息
    Args:
        update_code_message_key            (str):   update_code_message 的key值
        message                            (str):   update_code_message key对应的value
    Returns:
         None
    Raises:
        None
    Examples:
         None
    Author:  白爱洁 bwx473592
    Date: 2019/10/22 16:29
    """
    uid_match = update_code_message.get(update_code_message_key)
    if uid_match is not None:
        uid_match[UPDATE_MESSAGE] = message


def key_dic(data, key_item):
    """
    Function:
         找到key_所属的字典
    Args:
              key_item            (str):   字典中的key值
              data                (str):   redfish接口返回的数据
    Returns:
         key_value_dict          （dict）：key_所对应的字典结构
         find                    （True/False）: key_对应的字典结构是否找到的标志
    Raises:
        None
    Examples:
         None
    Author:  白爱洁 bwx473592
    Date:2019/10/24
    """
    key_value_dict = None
    find = False
    try:
        if isinstance(data, dict) and key_item in dict(data).iterkeys():
            find = True
            return data, find

        elif isinstance(data, dict) and key_item not in dict(data).iterkeys():
            for key in dict(data).iterkeys():
                key_value_dict, find = key_dic(data[key], key_item)
                if find:
                    return key_value_dict, find

        elif isinstance(data, list):
            for data_list in list(data):
                key_value_dict, find = key_dic(data_list, key_item)
                if find:
                    return key_value_dict, find
    except Exception as e:
        print("unexpect exception: " + str(e))
    return key_value_dict, find


def get_success_msg(item):
    name = item["name"]
    version = item["version"]
    # modify : DTS2019102207058 2019/10/22 整改升级成功的提示信息
    message = "%s update to version %s succeeded" % (name, version)
    return {
        "name": name,
        "state": RESULT_COMPLETE,
        "message": message,
        "package": item["location"]
    }


def get_failed_msg(item, message=None):
    name = item["name"]
    version = item["version"]
    # modify : DTS2019102207058 2019/10/22 整改升级失败的提示信息
    dft_message = "%s failed to update `%s` to version `%s`" % (UPDATE_FAIL, name, version)
    return {
        "name": name,
        "state": RESULT_FAILED,
        "message": message if message else dft_message,
        "package": item["location"]
    }


def should_upgrade_item(item):
    """should upgrade item according to item's mode & max-version
    & current-version
    :param item:
    :return: True if upgrade else not upgrade
    """
    max_version = item["v-max"]
    current_version = item["v-use"]
    mode = item["mode"]
    if mode == MODE_DRIVER:
        return max_version > current_version
    if mode == MODE_OUTBAND:
        return max_version > current_version
    if mode == MODE_INBAND:
        return max_version != current_version


def is_installed(installed_list, item):
    """checking is an item installed according to whether the item's install
    package download url has exits in the installed item list
    :param installed_list: a list of object : {
        "name": name,
        "state": RESULT_COMPLETE,
        "message": message,
        "package": package download url
    }
    :param item:
    :return:
    """
    item_name = item["name"]
    item_package_url = item["location"]

    print("[%s] checked whether item %s installed" % (now(), item_name))
    for installed in installed_list:
        if installed["package"] == item_package_url:
            if installed["state"] == RESULT_COMPLETE:
                result = get_success_msg(item)
            else:
                result = get_failed_msg(item, installed["message"])

            print("[%s] item %s installed" % (now(), item_name))
            print("[%s] result diff, old %s, new %s" % (
                now(), installed, result))
            return True, result

    print("[%s] item %s not installed" % (now(), item_name))
    return False, None


def drv_list_2_map(driver_list):
    """convert a driver list to map with name as key
    :param driver_list:
    :param key:
    :return:
    """
    mapped = {}

    unique_driver_mapping = {}
    names = []
    for driver in driver_list:
        if lower(driver["device"]) in ("0x37d1", "0x37ce"):
            continue
        key = "|".join([driver["device"],
                        driver["vendor"],
                        driver["subsystem_device"],
                        driver["subsystem_vendor"]])
        if key not in unique_driver_mapping:
            unique_driver_mapping[key] = driver
            names.append(driver["name"])

    unique_driver_list = unique_driver_mapping.values()
    for driver in unique_driver_list:
        name = driver["name"]
        count = names.count(name)
        if count == 1:
            mapped[name] = driver
        else:
            bdf = driver["path"].split("/")[-1]
            mapped["%s@%s" % (name, bdf)] = driver

    return mapped


def get_driver_configs():
    """ parse driver_name.cfg into an object array which contains Object like:
    #   Device  type  vender_id device_id  Driver  sub_vendor_id   sub_system_id
    :return:
    """
    with open("../config/driver_name.cfg", "rb") as f:
        return [line.strip().split() for line in f.readlines() if len(line) > 1]


def init_default_houp_repo():
    """copy config/houp.os.repo file to os yum repo folder if not exists
    :return:
    """
    yum_repo_path = "/etc/yum.repos.d"
    if not os.path.isdir(yum_repo_path):
        yum_repo_path = "/etc/yum/repos.d"
    target_houp_repo_path = os.path.join(yum_repo_path, "houp.repo")
    if not os.path.exists(target_houp_repo_path):
        print("houp repo not found in %s, create default now" % yum_repo_path)
        import platform
        import shutil
        distribution = platform.linux_distribution()[0]
        if "CentOS" in distribution:
            shutil.copy2("../config/houp.centos.repo",
                         target_houp_repo_path)
        elif "Red Hat" in distribution:
            shutil.copy2("../config/houp.rhel.repo",
                         target_houp_repo_path)
        else:
            raise Exception("HSU tool does support current os distribution")


def is_drive_gpgcheck_enabled():
    return get_repo_config(HOUP_DRV_SECTION, 'gpgcheck') == '1'


def is_firmware_gpgcheck_enabled():
    return get_repo_config(HOUP_FM_SECTION, 'gpgcheck') == '1'


def get_repo_config(section, key):
    """get houp.repo config item value

    :param section: config section
    :param key:     config item
    :return:
    """
    path = "/etc/yum.repos.d"
    if not os.path.isdir(path):
        path = "/etc/yum/repos.d"

    try:
        cp = ConfigParser.ConfigParser()
        cp.read(path + "/houp.repo")
        return cp.get(section, key)
    except:
        raise ValueError("Could not get %s.%s from houp.repo" % (section, key))


def is_rpm_valid(filepath):
    """check whether rpm file is valid

    :param filepath:
    :return:
    """
    cmd = "rpm --checksig " + filepath
    # stdout, stderr = subprocess.Popen(cmd, shell=True, stdout=subprocess.PIPE,
    #                           stderr=subprocess.PIPE).communicate()
    result = os.popen(cmd).read()
    return result.find('NOT OK') == -1


def get_raid_fm_version(command):
    p = subprocess.Popen(command, shell=True, stdout=subprocess.PIPE,
                         stderr=subprocess.PIPE)
    out, err = p.communicate()
    result = re.search(r"^PCI Address = (.*)$", out, flags=re.M)
    pci_address = result.group(1)

    result = re.search("^(FW|firmware) Version = (.*)$", out, flags=re.M)
    fw_version = result.group(2)

    return {
        "pci": pci_address,
        "version": fw_version
    }


def is_same_pcie(target_pcie, standard_pcie):
    """
    :Function: compare PCIe
    :param target_pcie: Get PCIe From RAIDCard Tools Command(00:01:00:00/00h:01h:00h:00h/0:65:0:0)
    :param standard_pcie: Get PCIe From system Command(0000:01:00.0)
    :return: true:0,false:1
    """
    # Compare PCIe from RAID card tools command and PCIe from system command
    target_pcie_segments = re.split(':', target_pcie.replace('h', ''))
    standard_pcie_segments = re.split(r':|\.', standard_pcie)
    count1 = len(target_pcie_segments)
    count2 = len(standard_pcie_segments)
    if count1 != count2:
        return False
    for index in range(count2):
        if int(target_pcie_segments[index], 16) != int(standard_pcie_segments[index], 16):
            return False
    return True


def compareStr(str1, str2):
    """

    Args:
              str1            (str):   字符串1
              str2            (str):   字符串2
    Returns:
         字符串对比结果（True or False）
    Raises:
        None
    Examples:
         None
    Author:  白爱洁 bwx473592
    Date: 2019/10/16 17:11
    """
    if None is str1 or str2 is None:
        return False
    return str1.lower() == str2.lower()


def list_subscript_crossing(list_tmp, index):
    """

    Args:
              list_tmp            (list):   列表
              list_tmp            (int):    列表中的索引
    Returns:
        下标是否越界 （True or False）
    Raises:
        None
    Examples:
         None
    Author:  白爱洁 bwx473592
    Date: 2019/10/16 17:11
    """
    return list_tmp and index > -len(list_tmp) and index < len(list_tmp)
