# coding:utf-8

import os
import sys
import time

'''
#========================================================================
#   @Method:  获取bmc的信息
#   @Param:
#   @Return: host:带内访问bmc的IP地址 带[]
#========================================================================
'''

DEV_NAME = "/dev/hwibmc2"


def openDevice(path):
    '''
    #====================================================================================
    #   @Method:
    #   @Param:
    #   @Return:
    #====================================================================================
    '''
    fd = None
    if os.path.exists(path):
        OPEN_FILE_FLAGS = os.O_RDWR | os.O_APPEND | os.O_EXCL
        try:
            fd = os.open(path, OPEN_FILE_FLAGS)
        except Exception:
            pass

    return fd


def closeDevice(fd):
    '''
    #====================================================================================
    #   @Method:
    #   @Param:
    #   @Return:
    #====================================================================================
    '''
    try:
        if fd is not None:
            os.close(fd)
        return True
    except Exception:
        print("Close char device failed.")
        return False


def writeDevice(fd, data):
    '''
    #====================================================================================
    #   @Method:
    #   @Param:
    #   @Return:
    #====================================================================================
    '''
    success = False
    try:
        os.write(fd, data)
        success = True
    except Exception:
        success = False

    return success


def waitDataReady(fd):
    '''
    #====================================================================================
    #   @Method:  
    #   @Param:
    #   @Return:
    #====================================================================================
    '''

    from select import epoll, EPOLLIN, EPOLLRDNORM
    ready = False

    try:
        ep = epoll()
        ep.register(fd, EPOLLIN | EPOLLRDNORM)

        times = 10
        while not ready and times > 0:
            try:
                events = ep.poll(1)
                # modify : DTS2019102205116 2019/10/28 BMC链接异常，超时处理
                if events is None or len(events) == 0:
                    times = times - 1
                    continue
                for (fileno, event) in events:
                    if fileno == fd and event & (EPOLLIN | EPOLLRDNORM):
                        ready = True
                        break
            except IOError as e:
                times = times - 1
                # modify : DTS2019102205116 2019/10/28 打印错误日志
                print("unexpect exception: " + str(e))
                continue
    finally:
        if ep is not None:
            ep.unregister(fd)
            ep.close()

    return ready


def getinnersession():
    '''
    #====================================================================================
    #   @Method:
    #   @Param:
    #   @Return:
    #====================================================================================
    '''
    fd = None
    token = None

    XARGS = ["0x30", "0x94", "0xdb", "0x07", "0x00", "0x39", "0x04", \
             "0x01", "0x00", "0x00", "0x00", "0x00", "0x00", "0x00", \
             "0x00", "0x00", "0x00", "0x00", "0x00", "0x00", "0x00", \
             "0x00", "0x00", "0x00", "0x00", "0x00", "0x00", "0x00", \
             "0x00", "0x00"]

    SEQ = 0x00
    shift = 0
    # shift left, if little order,
    if "little" == sys.byteorder.lower():
        shift = 2

    header = [0x00, 0x00, 0x00, 0x00, 0x00]
    header[0] = "0x%x" % (0x01)
    header[1] = "0x%x" % (len(XARGS) + 1)
    header[2] = "0x%x" % (int(XARGS[0], 16) << shift)
    header[3] = "0x%x" % (SEQ)
    header[4] = "0x%x" % (int(XARGS[1], 16))

    command = XARGS[2:]

    command = header + command

    hexString = ''.join(['{0:02x}'.format(int(cByte, 16)) for cByte in command]).strip()

    if fd is None:
        fd = openDevice(DEV_NAME)
        time.sleep(1)

    if fd is None:
        return None

    # DTS2017080103277
    hexStringdecode = hexString.decode("hex")

    ret = writeDevice(fd, hexStringdecode)

    if ret != False and waitDataReady(fd):

        data = os.read(fd, 255)
        if data is not None:
            ll = [int(ord(x)) for x in data[9:-1]]
            token = ("%s" % ("".join("%c" % (x) for x in ll)))

    if fd is not None:
        closeDevice(fd)
        fd = None

    return token
