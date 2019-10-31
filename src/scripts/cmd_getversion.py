# -*- coding: UTF-8 -*-
from __future__ import print_function
import sys
import json
from tabulate import tabulate
from utils import *
from cmd_verify import CmdVerify


class CmdGetversion(CmdVerify):
    """
    功能描述： 带外获取iBMC和BIOS的固件版本
    接口：无
    修改记录：无
    """
    def run(self):
        """
        功能描述：带外获取iBMC和BIOS的固件版本
        参数：none
        返回值：none
        异常描述：none
        修改记录：none
        """
        dict_temp = {}
        self.get_outband_firmwares(dict_temp)
        print("[%s] =====> Append Outband FW List <=====" % now())
        print(json.dumps(dict_temp, sort_keys=True, indent=4))
        for k, v in dict_temp.items():
            del v["mode"]
            del v["device"]
            del v["name"]
            del v["subsystem_device"]
            del v["subsystem_vendor"]
            del v["vendor"]
        self.result["data"] = dict_temp
        return

    def readable_print(self, target=sys.stdout):
        """
        功能描述：将result["data"] 中的数据以表格的形式打印出来
        参数：target 把print中的值打印到目标文件
        返回值：none
        异常描述：none
        修改记录：none
        """
        # print data as text format (human readable)
        if 0 != self.result['rc']:
            print("Failure: %s" % self.result["msg"])
        else:
            flatten = []
            for item, versions in self.result["data"].items():
                type_temp = versions.get("type", "").upper()
                if type_temp == "IBMC":
                    type_temp = "iBMC"
                flatten.append([type_temp,
                                versions.get("ver", None)])

            headers = ["Item", "Current version"]
            print("[Upgrade item list]\n", file=target)
            print(tabulate(flatten, headers=headers, tablefmt='orgtbl'),
                  file=target)
