# -*- coding: UTF-8 -*-

import subprocess
from cmd_base import CmdBase

'''
#########################################################
# Restart server
# usage：hsu restart
##########################################################
'''


class CmdRestart(CmdBase):
    def run(self):
        # focus linux os only now!!!
        subprocess.call("shutdown -r +1 >/dev/null 2>/dev/null &", shell=True)
        self.result["data"] = "System will shutdown 1 minute later"
