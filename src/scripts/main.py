#!/usr/bin/python
# -*- coding: UTF-8 -*-

import os
import signal
import sys
import utils
import constants

__version__ = '1.0.2'


def doit():
    # ================================================================
    # @Method:  CLI main entry function
    # @Param:   None
    # @Return:  None
    # @Author:  Joson_Zhang
    # ================================================================
    result = {}
    try:
        import argparse
        # Construct argparser and add major command parameters.
        parser = argparse.ArgumentParser(prog='hsu')
        parser.add_argument('-v', '--version', action='version',
                            version="Version: %s" % __version__)
        parser.add_argument('--format', dest="fmt", choices=['json', 'console'],
                            default="console",
                            help="output format type (console, json)")
        # parser.add_argument('command', metavar='command',
        #                     choices=['verify', 'restart','update',  'remove', 'getversion'],
        #                     help="command (verify, restart, update,remove, getversion)")

        subparsers = parser.add_subparsers(title='subcommands',
                                           dest='subcommands',
                                           description='valid subcommands',
                                           help='command (restart, update,remove, getversion)')

        subparsers.add_parser('restart')
        update_subparser = subparsers.add_parser('update')
        subparsers.add_parser('remove')
        subparsers.add_parser('getversion')

        update_subparser.add_argument('-l', dest='type',
                                      type=str, required=True,
                                      choices=['BIOS', 'BMC'],
                                      help="local ('BIOS', 'BMC')")

        update_subparser.add_argument('options', metavar='options', nargs='*',
                                      help="run %(prog)s command for detail help")
        args = parser.parse_args()

        # qianbiao.ng: make command to support "-""
        cmd = __import__('cmd_' + args.subcommands.replace('-', "_"))
        capitalize_cmd = ''.join(
            x.capitalize() or '_' for x in args.subcommands.split('-'))
        cls = getattr(cmd, 'Cmd' + capitalize_cmd)
        result = {"rc": 0, "msg": "OK", "data": {}}
        obj = cls(args, result)
        obj.run()
    except KeyboardInterrupt as e:
        # modify : DTS2019102207058 2019/10/22 整改ctrl+c情况下的升级失败提示信息
        print("unexpect exception: " + str(e))
        code, message = utils.get_code_message(constants.ABNORMAL_EXIT_CODE)
        result["rc"] = code
        result["msg"] = message
        s = signal.signal(signal.SIGINT, signal.SIG_IGN)
        signal.signal(signal.SIGINT, s)


if __name__ == '__main__':
    root = os.path.split(os.path.realpath(__file__))[0]
    os.chdir(root)
    sys.path.insert(1, os.path.join(root, '../third-party'))

    import platform

    distribution = platform.linux_distribution()[0]
    if "CentOS" in distribution or "Red Hat" in distribution:
        doit()
    else:
        print("HSU tool does support current os distribution")
