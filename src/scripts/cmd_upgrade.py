# -*- coding: UTF-8 -*-
from __future__ import print_function

import json
import sys
import time
import traceback

from utils import *

reload(sys)
sys.setdefaultencoding('UTF-8')

from cmd_progress import CmdProgress
from cmd_async_upgrade import CmdAsyncUpgrade
from cmd_verify import CmdVerify

'''
#########################################################
# upgarde all drivers and firmware
# exec：hsu auto-upgrade
#   {
#       "<name>":{
#           "state":"<TaskState>",
#           "percent":<value>
#       },
#       ...
#   }
#   percent ，0-100
##########################################################
'''

running_item = None
item_name_format = None


def is_all_upgrade_completed(results):
    for _, result in results.items():
        if not result or result['state'] != 'Completed':
            return False
    return True


def print_readable_progress(progress_result, stream=sys.stdout):
    """print readable progress to target stream

    :param progress_result:
    :param stream:
    :return:
    """

    def item_cmp(one, other):
        w1 = get_item_weight(one)
        w2 = get_item_weight(other)
        if w1 == w2:
            return 1 if one[0] < other[0] else -1
        return w1 - w2

    def get_item_weight(i):
        weight = 20 if str(i[0]).startswith("Drv-") else 10
        return weight + SORTED_RESULT_STATUS[i[2]]

    def get_item(name, item_):
        return [name, item_.get("message", None),
                item_.get("state", None), str(item_.get("percent", 0)) + "%"]

    def print_finished_item(item_):
        completed = item_[2] == RESULT_COMPLETE
        msg = item_[1][len(item_[0]) + 1:] if completed else item_[1]
        name = item_name_format.format(name=item_[0])
        print("%s: %s (%s)" % (name, RESULT_MAPPING[item_[2]], msg),
              file=stream)

    def print_running_item(item_):
        name = item_name_format.format(name=item_[0])
        print(" " * (len(name) + 10) + "\r", end="\r", file=stream)
        stream.flush()
        print("%s: %s\r" % (name, item_[3]), end="\r", file=stream)
        stream.flush()

    global running_item
    global item_name_format
    if item_name_format is None:
        max_item_name_len = len(max(progress_result["data"].keys(), key=len))
        item_name_format = "{name: <%d}" % (max_item_name_len + 1)

    if running_item is None:
        # filter all processing items
        flatten = []
        for item_name, progress in progress_result["data"].items():
            if progress.get("state", None) != RESULT_PENDING:
                flatten.append(get_item(item_name, progress))
        # sort items
        sorted_items = sorted(flatten, cmp=item_cmp, reverse=True)
        if sorted_items[-1][2] == RESULT_RUNNING:
            running_item = sorted_items.pop(-1)

        # print finished items
        for item in sorted_items:
            print_finished_item(item)

    # print running item
    if running_item is not None:
        item_name = running_item[0]
        updated_item = progress_result["data"].get(item_name)
        running_item = get_item(item_name, updated_item)
        if running_item[2] != RESULT_RUNNING:
            print_finished_item(running_item)
            running_item = None
            # get next running item
            for item_name, progress in progress_result["data"].items():
                if progress.get("state", None) == RESULT_RUNNING:
                    running_item = get_item(item_name, progress)
                    print_running_item(running_item)
        else:
            print_running_item(running_item)


class CmdUpgrade(CmdProgress):
    def run(self):
        # qianbiao.ng: because hsu command does not handle exception,
        # so we re-catch exceptions

        print("+------------------------------------------------+")
        print("[%s] Start auto upgrade job now " % (now()))
        print("+------------------------------------------------+")

        command = None
        pidfile_created = False
        try:
            # create pidfile for current progress
            pidfile_created = create_pidfile()
            if not pidfile_created:
                msg = "Other upgrade task is running now, " \
                      "please wait until it finished"
                self._error(1, msg)
                return

            # step1: run verify
            verify_result = {"rc": 0, "msg": "OK", "data": {}}
            command = CmdVerify(self.args, verify_result)
            command.run()
            if verify_result["rc"] != 0:
                self.result = verify_result
                return
            else:
                command.flushed = True
                # if command.is_console_user():
                #     command.readable_print(target=command.sysstds[0])

            print("[%s] verify result: %s" % (now(),
                                              json.dumps(verify_result)))

            # step2: run upgrade
            # remove auto option to keep back compatibility
            if len(self.args.options) == 1 and self.args.options[0] == "auto":
                self.args.options.pop(0)

            upgrade_result = {"rc": 0, "msg": "OK", "data": {}}
            command = CmdAsyncUpgrade(self.args, upgrade_result)
            command.run()
            task_id = upgrade_result["data"]["taskid"]
            print("[%s] upgrade result: %s" % (now(),
                                               json.dumps(upgrade_result)))

            # no_task = task_id is None or len(task_id) == 0
            # if task failed or task finished
            if upgrade_result["rc"] != 0:
                self.result = upgrade_result
                return
            else:
                command.flushed = True

            progress_result = {"rc": 0, "msg": "OK", "data": {}}
            command = CmdProgress(self.args, progress_result)
            # step3: get progress
            while True:
                command.flushed = True
                command.error = False
                task_finished, _ = command.get_task_progress(task_id)
                print("[%s] task finished: %s, progress result: %s" % (
                    now(), task_finished, progress_result))

                if task_finished:
                    print("[%s] auto upgrade final result: %s" % (
                        now(), json.dumps(progress_result)))
                    print("[%s] auto upgrade job finished " % (now()))

                    self.result = progress_result
                    no_item_upgrade = len(progress_result['data']) == 0
                    up_to_date_msg = "All items are up to date"
                    if self.is_console_user():
                        self.flushed = True
                        if no_item_upgrade:
                            print(up_to_date_msg, file=command.sysstds[0])
                        else:
                            self.readable_print(target=command.sysstds[0])
                    else:
                        if no_item_upgrade:
                            self.result["data"] = up_to_date_msg
                        else:
                            results = progress_result['data']
                            all_completed = is_all_upgrade_completed(results)
                            if not all_completed:
                                self._error(10, json.dumps(results))
                    return
                else:
                    if command.is_console_user() \
                            and len(progress_result["data"]) > 0:
                        print_readable_progress(progress_result,
                                                stream=command.sysstds[0])

                # wait 2 second between query task progress command
                time.sleep(2)
        except Exception as e:
            print("Unexpect exception: " + str(e))
            # disable delegated command's output
            # command.flushed = True
            # catch un-handled exceptions, and mark task failed
            traceback.print_exc()
            self._error(10, e.message)
        finally:
            # remove pid file
            if pidfile_created:
                remove_pidfile()
            if self.is_console_user():
                print("\n".join([" " for i in range(1, 10)]))

    def readable_print(self, target=sys.stdout):
        print_readable_progress(self.result, stream=target)
