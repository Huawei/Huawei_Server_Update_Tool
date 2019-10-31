# -*- coding: UTF-8 -*-

import os
import subprocess

from cmd_base import CmdBase
from constants import IBMA_INI_PATH, DRIVE_KO_LIST

'''
#########################################################
# Remove HSU
# usage：hsu remove
##########################################################
'''


class CmdRemove(CmdBase):
    def run(self):
        kept = "IBMA was installed, *drv.ko will be kept"
        ibma_installed = os.path.exists(IBMA_INI_PATH)
        if not ibma_installed:  # remove drives
            for drv in DRIVE_KO_LIST:
                print("Remove drv: " + drv)
                # Modify: DTS2019102205116 不显示查询出来的驱动
                subprocess.call("lsmod | grep %s >/dev/null && rmmod -f %s" % (drv, drv), shell=True)
            self.result["data"] = "HSU has been removed"
        else:
            print(kept)
            self.result["data"] = kept

