# -*- coding: UTF-8 -*-
from __future__ import print_function

import gzip
import json
import re
import subprocess
import sys
import time
import urllib
import urllib2
from cStringIO import StringIO

from utils import *

'''
#=========================================================================
#   @Description: Process user command base class
#		It save user's input arguments and return values
#		Subclass can change the result variable in run function
#		And when this program exit, will print the result to console
#		It's format depend on --format (args.fmt)
#   @author: Joson_Zhang
#   @Date: 2018/06/03
#=========================================================================
'''


class CmdBase(object):
    from urest import redfish_client
    # Is error occur flag (e.g: invalid input parameter)
    error = False
    # Redfish module instance
    client = redfish_client.RedfishClient()
    # Is flushed protocol output data flag, ignore duplicate output
    flushed = False
    # Save standard input and ouput variables for redirect its to file
    sysstds = [sys.stdout, sys.stderr]

    def __init__(self, args, result):
        # backup caller's input parameters
        self.args = args
        self.result = result
        # redirect stdout and stderr for ignore redfish library print informations
        log_dir = "/var/log/HSU"
        if not os.path.exists(log_dir):
            os.makedirs(log_dir)

        sys.stdout = open(log_dir + "/log.txt", "a+")
        sys.stderr = open(log_dir + "/error.txt", "a+")
        # get os info
        os_ver = self._getOsVer()
        os_arch = self._getOsArch()
        directory = "%s-%s" % (os_ver, os_arch)
        if os_ver == "6.9":
            linux_version = self._get_kernel_version()
            print("linux_version:", linux_version)
            if linux_version.find("4.4.179-1.el6.elrepo.x86_64") != -1:
                directory = "%s-4.4.179-%s" % (os_ver, os_arch)
        print(directory)
        # install virtual-ethernet driver and startup it
        print("[%s] Start install driver tools" % now())
        if not self._getCmdTable("lsmod | grep -E 'host_edma_drv '").has_key(
                "host_edma_drv"):
            subprocess.call(
                "insmod ../tools/vnet/" + directory + '/host_edma_drv.ko >/dev/null 2>/dev/null',
                shell=True)
        if not self._getCmdTable("lsmod | grep -E 'host_cdev_drv '").has_key(
                "host_cdev_drv"):
            subprocess.call(
                "insmod ../tools/vnet/" + directory + '/host_cdev_drv.ko >/dev/null 2>/dev/null',
                shell=True)
        if not self._getCmdTable("lsmod | grep -E 'host_veth_drv '").has_key(
                "host_veth_drv"):
            subprocess.call(
                "insmod ../tools/vnet/" + directory + '/host_veth_drv.ko >/dev/null 2>/dev/null',
                shell=True)
        time.sleep(2)

        print("[%s] Start veth up" % now())
        veth = self._getCmdTable("ip addr | grep -E 'veth:'")
        if not veth.has_key("veth:") or not veth.has_key("UP"):
            subprocess.call("ip link set veth up >/dev/null 2>/dev/null",
                            shell=True)
        self.inner_establish_connection()
        # Destination Net Unreachable
        print("[%s] Start init default repo" % now())
        # initial default houp repo if necessary
        init_default_houp_repo()

    def inner_establish_connection(self):
        """

        Args:
                  arg1            (None):
        Returns:
             None
        Raises:
            None
        Examples:
             None
        Author:  白爱洁 bwx473592
        Date: 2019/10/16 17:11
        """
        ping6_success = False
        for i in range(1, 10):
            ping_bmc_result = os.popen(PING_BMC_CMD).read()
            print("[%s] ping6 result: %s" % (now(), ping_bmc_result))
            received_times = re.findall(r'\d received', ping_bmc_result)
            if len(received_times) > 0:
                if received_times[0][0:1] != '0':
                    ping6_success = True
                    break
            time.sleep(1)
        if not ping6_success:
            code, message = get_code_message(BMC_ERROR)
            print(message)
            self._error(code, message)

        print("[%s] Start create inner session" % now())
        # create redfish client object and initialize it
        # modify : DTS2019102205116 2019/10/28 BMC链接异常，超时处理
        inner_session = self.client.create_inner_session()
        if inner_session is False:
            code, message = get_code_message(BMC_ERROR)
            print(message)
            self._error(code, message)
        else:
            print("[%s] Start set inner bmcinfo" % now())
            self.client.set_inner_bmcinfo()

    def run(self):
        # virtual work function, all sub-class need override the function!!!
        pass

    def __del__(self):
        # print outputs
        self._flush()

    def _flush(self):
        # rollback standard stdout and stderr
        if self.flushed:
            # flushed already, no need do it again
            return
        self.flushed = True
        print("Release redfish session now")
        self.client.delete_inner_session()
        sys.stdout.close()
        sys.stderr.close()
        sys.stdout = self.sysstds[0]
        sys.stderr = self.sysstds[1]
        # print results
        # if error occur, error message print out already, no need print again
        if self.error:
            return

        # print results, format depend on user's input format
        if "json" == self.args.fmt:
            # print data as json format
            print(json.dumps(self.result))
        else:
            self.readable_print(target=sys.stdout)

    def is_console_user(self):
        return FMT_CONSOLE == self.args.fmt

    def readable_print(self, target=sys.stdout):
        # print data as text format (human readable)
        if 0 == self.result['rc']:
            stat = "Success"
        else:
            stat = "Failure"
        print("Status: %s" % (stat))
        msg = self.result["msg"]
        print("Message: %s" % str(msg))
        data = self.result.get("data")
        print("Data: %s" % str(data))

    # command error rapid function
    def _error(self, rc, msg):
        self.result["rc"] = rc
        self.result["msg"] = msg
        self.result["data"] = {}
        exit(-1)

    # extract file name from path/url/uri
    def _getName(self, path):
        list = str(path).split('/')
        if list[-1] != path:
            return list[-1]
        return str(path).split("\\")[-1]

    # examine bin is valid system command
    def _isCmd(self, bin):
        p = subprocess.Popen(["which", bin], stdout=subprocess.PIPE,
                             stderr=subprocess.STDOUT)
        out, err = p.communicate()
        s = str(out).strip()
        if len(s) > 0 and s.find(':') < 0:
            if os.path.exists(s):
                return True
        return False

    # get OS version
    def _getOsVer(self):
        def _byLSB():
            p = subprocess.Popen(["lsb_release", "-a"], stdout=subprocess.PIPE,
                                 stderr=subprocess.STDOUT)
            out, err = p.communicate()
            buf = StringIO(out)
            while True:
                s = buf.readline().strip()
                if len(s) <= 0:
                    break
                list = s.split(':')
                if len(list) < 2:
                    continue
                if 'Release' != list[0]:
                    continue
                return list[1].strip()
            return ''

        def _byFile():
            p = subprocess.Popen(["cat", "/etc/redhat-release"],
                                 stdout=subprocess.PIPE,
                                 stderr=subprocess.STDOUT)
            out, err = p.communicate()
            # format like this: 'CentOS Linux release 7.4.1708 (Core)'
            s = str(out).strip()
            array = s.split(' ')
            if len(array) > 0:
                for i in range(0, len(array)):
                    if array[i].find('.') < 0:
                        continue
                    array2 = array[i].split('.')
                    if len(array2) < 2:
                        continue
                    return array2[0] + "." + array2[1]
            return ''

        if self._isCmd("lsb_release"):
            # if lsb_release command is valid, use it
            s = _byLSB()
        else:
            # otherwise use redhat-release file information
            s = _byFile()
        return s

    # get OS arch (use arch command)
    def _getOsArch(self):
        p = subprocess.Popen(["arch"], stdout=subprocess.PIPE,
                             stderr=subprocess.STDOUT)
        out, err = p.communicate()
        return out.replace('\n', '')

    def _get_kernel_version(self):
        """
        Function：
            获取内核版本
        Args:
             None
        Returns:
             None
        Raises:
            None
        Examples:
             None
        Author:  白爱洁 bwx473592
        Date:  2019/10/21
        """
        p = subprocess.Popen(["uname", "-r"], stdout=subprocess.PIPE,
                             stderr=subprocess.STDOUT)
        out, err = p.communicate()
        return out.replace('\n', '')

    # read file contents as ID (remove tail \r\n)
    def _readID(self, path):
        s = None
        with open(path, "r") as f:
            s = f.readline()
        if (None != s) and (len(s) > 0):
            # s = s.replace('0x', '')
            s = s.replace('\n', '')
        return s

    # Uncompress GZIP data
    def _unGzData(self, data):
        buf = StringIO(data)
        fil = gzip.GzipFile(mode="rb", fileobj=buf)
        try:
            out = fil.read()
        finally:
            fil.close()
        return out

    # HTTP download file function (retrieve rpm/xml/...)
    def _downHttpFile(self, url, path, show_percent=False):
        def _showPercent(got, block, size):
            n = 100.0 * got * block / size
            if n > 100:
                n = 100
            print("Download percent: %.02f%%" % n)

        if False == show_percent:
            urllib.urlretrieve(url, path)
        else:
            urllib.urlretrieve(url, path, _showPercent)

    # HTTP download file as string function (e.g: xml)
    def _downHttpFileAsString(self, url):
        s = ''
        try:
            f = urllib2.urlopen(url, timeout=10)
            s = f.read()
        except:
            print("Failed to download file: " + url)
        return s

    # replace (s) all (old) string to (new) string
    def _strReplaceAll(self, s, old, new):
        while True:
            s2 = s.replace(old, new)
            if s == s2:
                break
            s = s2
        return s2

    # execute cmd and retrieve data as key/value pairs
    def _getCmdPairs(self, cmd, sep='=', vector=False):
        result = {}
        try:
            p = subprocess.Popen(cmd, shell=True, stdout=subprocess.PIPE,
                                 stderr=subprocess.PIPE)
            out, err = p.communicate()
            buf = StringIO(str(out))
            while True:
                s = buf.readline()
                if None == s or len(s) <= 0:
                    break
                s = s.strip()
                i = s.find(sep)
                if i <= 0:
                    continue
                k = s[:i].strip()
                v = s[i + 1:].strip()
                if vector:
                    if not result.has_key(k):
                        result[k] = [v]
                    else:
                        result[k].append(v)
                else:
                    result[k] = v
        except:
            print("Failed to execute command: " + cmd)
        return result

    # execute cmd and retrieve data as table
    def _getCmdTable(self, cmd, sep=' '):
        result = {}
        try:
            p = subprocess.Popen(cmd, shell=True, stdout=subprocess.PIPE,
                                 stderr=subprocess.PIPE)
            out, err = p.communicate()
            buf = StringIO(str(out))
            head = []
            while True:
                s = buf.readline()
                if None == s or len(s) <= 0:
                    break
                s = self._strReplaceAll(s.strip(), sep + sep, sep)
                ss = s.split(sep)
                if None == ss or len(ss) <= 0:
                    continue
                if len(result.keys()) <= 0:
                    # head/title
                    head = ss
                    for s in ss:
                        result[s.strip()] = []
                else:
                    # data
                    for i in range(0, len(head)):
                        if i >= len(ss):
                            result[head[i]].append('')
                        else:
                            result[head[i]].append(ss[i])
        except Exception as e:
            print("Failed to get result table from cmd: " + cmd)
            print(e)
        return result

    def _get_product_unique_id(self):
        """

        Args:
                  arg1            (None):
        Returns:
             通过redfish 接口得到 server/ibmc 的 unique id
        Raises:
            通过redfish 接口得到 server/ibmc 的 unique id 失败
        Examples:
             None
        Author:  白爱洁 bwx473592
        Date: 2019/10/16 17:11
        """
        url = "/redfish/v1/Managers"
        try:
            ret = self.client.get_resource(url)
            print("get product unique id:", ret)
            if None != ret and 200 == ret["status_code"] and len(
                    ret["resource"]["Members"]) > 0:
                url = ret["resource"]["Members"][0].get(ODATA_ID_KEY)
                if url is None:
                    return None
                ret = self.client.get_resource(url)
                if ret is not None and 200 == ret["status_code"]:
                    return ret["resource"]["Oem"]["Huawei"][
                        "ProductUniqueID"]
        except (AttributeError, KeyError) as e:
            print(
                "Failed to get ProductUniqueID by /redfish/v1/Managers interface! %s", str(e))
        return None
