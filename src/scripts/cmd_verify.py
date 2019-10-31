# -*- coding: UTF-8 -*-
from __future__ import print_function

import ConfigParser
import json
import pickle
import subprocess
from cStringIO import StringIO
from itertools import groupby
from operator import itemgetter
from xml.dom.minidom import parseString

from cmd_base import CmdBase
from utils import *

'''
###############################################################################
# Call method：hsu verify
# Input：
#   None
# Output：
#   {
#       "<driver name>":{
#           "v-use":"<current using version>",
#           "v-max":"<server lastest version>",
#           "vlist":["<version-1>", "<version-2>", ...]
#       },
#       ...
#   }
#   name    Driver/FW name
#   v-use   Version using
#   v-max   Latest version on repo server
#   vlist   Usable version(s) list on repo server
###############################################################################
'''
import sys


class CmdVerify(CmdBase):
    '''
    # Read repo baseurl from yum repos.d and replace keywords
    '''

    def _getRepoURL(self, firmware=False):
        path = "/etc/yum.repos.d"
        if not os.path.isdir(path):
            path = "/etc/yum/repos.d"
        try:
            cp = ConfigParser.ConfigParser()
            cp.read(path + "/houp.repo")
            sect = "huawei-server-driver"
            if firmware:
                sect = "huawei-server-firmware"
            s = cp.get(sect, "baseurl")
        except:
            print("Could not get repo url from houp.repo, use default")
            s = DFT_RHEL_REPO_URL
        v = self._getOsVer()
        s = s.replace("$releasever", v)
        s = s.replace("$basearch", self._getOsArch())
        return s

    '''
    # Read local PCI driver list, content as below:
    #   name: ver, mode, device, vendor, subsystem_device, subsystem_vendor
    '''

    def _getDriverSW(self):
        drivers = []

        white_list = get_driver_configs()
        p = subprocess.Popen(["find", "/sys/devices/", "-name", "device"],
                             stdout=subprocess.PIPE,
                             stderr=subprocess.STDOUT)
        out, err = p.communicate()
        buf = StringIO(out)
        while True:
            s = buf.readline().strip()
            if len(s) <= 0:
                break

            # filter PCI hardware
            if not s.startswith("/sys/devices/pci"):
                continue
            paths = os.path.split(s)
            if (None == paths) or (len(paths) != 2):
                continue
            path = paths[0]
            item = {"path": path}
            # read hardware infos
            # (device/vendor/subsystem_device/subsystem_vendor/...)
            try:
                if os.path.isfile(os.path.join(path, "driver/module/version")):
                    item["ver"] = self._readID(
                        os.path.join(path, "driver/module/version"))
                else:
                    item["ver"] = "0"

                item["mode"] = MODE_DRIVER
                item["device"] = self._readID(os.path.join(path, "device"))
                item["vendor"] = self._readID(os.path.join(path, "vendor"))
                item["subsystem_device"] = self._readID(
                    os.path.join(path, "subsystem_device"))
                item["subsystem_vendor"] = self._readID(
                    os.path.join(path, "subsystem_vendor"))
                # link = os.readlink(os.path.join(path,"driver"))
            except(OSError, IOError):
                # print("Could not detect driver for path: " + path)
                continue
            name = ""
            if item["device"] and item["vendor"]:
                for row in white_list:
                    if len(row) < 5:
                        continue
                    if (row[2].lower() == item["vendor"].lower()) and (
                                row[3].lower() == item["device"].lower()):
                        name = row[4]
                        item["type"] = row[1]
                        break

            if "" == name:
                continue
                # names = os.path.split(link)
                # if None == names or len(names) != 2:
                #    continue
                # maybe use same name in driver and inband firmware, use SW/FW prefix for split them
                # Support multiple RAID cards and network cards
            item["name"] = PREF_DRIVER + name
            item["_name"] = name
            drivers.append(item)

        return drv_list_2_map(drivers)

    # Get hardwares (see _getDriverSW) inband FW (NET/DISK/RAID 3 parts)
    def _getInbandFW(self, list):

        # Part #1: NET
        def _getNET():
            for k, v in list.items():
                if (not v.has_key("type")) or (v["type"].lower() != "net"):
                    continue

                drv_path = v["path"]
                cls = self._readID(os.path.join(v["path"], "class"))
                print("[%s] net class: %s" % (now(), str(cls)))
                # Use class file for identify hardware type (NIC/FCoE)
                if cls in ["0x020000", "0x028000", "0x020700"]:
                    # use ethtool -i name | grep -i "firmware" command for
                    # retrieve FW version that using
                    # maybe contain more than one interface, need collect all
                    net_path = os.path.join(drv_path, "net")
                    print("[%s] net dir: %s" % (now(), net_path))
                    value = v.copy()
                    if os.path.isdir(os.path.join(drv_path, "net")):
                        for s in os.listdir(os.path.join(v["path"], "net")):
                            p = subprocess.Popen(
                                'ethtool -i %s | grep -i "firmware"' % s,
                                shell=True, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE)
                            out, err = p.communicate()
                            s = str(out)
                            ss = s.split(":")
                            if ss is None or len(ss) < 2:
                                continue
                            ver = ss[1].strip()
                            value["ver"] = ver.replace(' ', '.').replace('-',
                                                                         '.')
                    else:
                        value["ver"] = "0"
                    value["mode"] = MODE_INBAND
                    list[PREF_FIRMWARE + k[4:]] = value

                elif cls == "0x0c0400":
                    # read host*/fc_host/host*/symbolic_name file for retrieve FW version that using
                    cmd = "cat " + os.path.join(drv_path,
                                                "host*/fc_host/host*/symbolic_name")
                    p = subprocess.Popen(cmd, shell=True,
                                         stdout=subprocess.PIPE,
                                         stderr=subprocess.PIPE)
                    out, err = p.communicate()
                    ss = StringIO(str(out)).read().split(' ')
                    if None == ss or len(ss) < 2:
                        continue
                    for s in ss:
                        if s.startswith("FV") or k.startswith("FW:V"):
                            break
                    s = s.replace("FV", "").replace("FW:v", "")
                    value = v.copy()
                    value["ver"] = s
                    value["mode"] = MODE_INBAND
                    list[PREF_FIRMWARE + k[4:]] = value

        # Part #2: DISK
        def _getDISK():
            # get physical disk info (use disktool for list all physical disks)
            subprocess.call(
                "chmod +x ../tools/disk/disktool >/dev/null 2>/dev/null",
                shell=True)
            result = self._getCmdTable("../tools/disk/disktool -s")
            print("disk:" + str(result))
            if None != result and result.has_key("Device"):
                for name in result["Device"]:
                    result2 = self._getCmdPairs(
                        "../tools/disk/disktool -f i " + name, ':')
                    if None == result2:
                        continue
                    if not result2.has_key("Device Model"):
                        continue
                    # skip LIS/USB/AVAGO/Logical types, it's RAID virtual disk
                    if result2["Device Model"] == "LSI":
                        continue
                    if result2["Device Model"] == "USB":
                        continue
                    if result2["Device Model"] == "AVAGO":
                        continue
                    if result2["Device Model"] == "Logical":
                        continue
                    if not result2.has_key("Serial Number"):
                        continue
                    if not result2.has_key("Firmware Version"):
                        continue
                    item = {}
                    item["ver"] = result2["Firmware Version"].replace(' ',
                                                                      '.').replace(
                        '-', '.')
                    item["mode"] = MODE_INBAND
                    item["type"] = "disk"
                    item["device"] = ''
                    item["vendor"] = ''
                    item["subsystem_device"] = ''
                    item["subsystem_vendor"] = ''
                    list[
                        PREF_FIRMWARE + result2["Device Model"] + "@" + result2[
                            "Serial Number"]] = item

            # get logical disk info (need use raid tools for retrieve its)
            sas2ircu = sas3ircu = storcli64 = 0
            subprocess.call("chmod +x ../tools/raid/* >/dev/null 2>/dev/null",
                            shell=True)
            for k, item in list.items():
                if (not item.has_key("type")) or (
                            item["type"].lower() != "raid"):
                    continue
                sp = ':'
                sn = "Serial No"
                model = "Model Number"
                version = "Firmware Revision"
                item_name = item["name"]
                if item_name == 'Drv-mpt2sas':
                    s = "../tools/raid/sas2ircu " + str(
                        sas2ircu) + " display|egrep -i 'Model Number|Firmware Revision|Serial No'"
                    sas2ircu += 1
                elif item_name == 'Drv-mpt3sas':
                    s = "../tools/raid/sas3ircu " + str(
                        sas3ircu) + " display|egrep -i 'Model Number|Firmware Revision|Serial No'"
                    sas3ircu += 1
                elif item_name == 'Drv-megaraid_sas':
                    if storcli64 > 0:
                        # checked, ignore this cycle
                        continue
                    s = "../tools/raid/storcli64 /call/eall/sall show all | egrep -i 'Model Number|SN|Firmware Revision'"
                    sp = '='
                    sn = "SN"
                    storcli64 += 1
                else:
                    # unknown type, ignore it!
                    continue
                map = self._getCmdPairs(s, sp, True)
                print("disk map:" + str(map))
                if map is None or not map.has_key(sn) or not map.has_key(
                        model) or not map.has_key(version):
                    continue
                if len(map[sn]) != len(map[model]) or len(map[sn]) != len(
                        map[version]):
                    continue
                for i in range(0, len(map[model])):
                    item = {"ver": map[version][i], "mode": MODE_INBAND,
                            "type": "disk", "device": '', "vendor": '',
                            "subsystem_device": '', "subsystem_vendor": ''}
                    list[
                        PREF_FIRMWARE + map[model][i] + "@" + map[sn][i]] = item

        # Part #3: RAID
        def _getRAID():
            sas2ircu = sas3ircu = storcli64 = 0
            subprocess.call("chmod +x ../tools/raid/* >/dev/null 2>/dev/null",
                            shell=True)

            counter = {}
            items = sorted([item for item in list.values()
                            if 'type' in item and item['type'] == 'raid'])
            for item in items:
                name = item["name"]
                if name not in counter:
                    counter[name] = 1
                else:
                    counter[name] = counter[name] + 1
            print(counter)

            version_mapping = {}
            if 'Drv-mpt2sas' in counter:
                command = "../tools/raid/sas2ircu %d display"
                count = counter['Drv-mpt2sas']
                for i in range(0, count):
                    result = get_raid_fm_version(command % i)
                    name_with_bdf = 'Drv-mpt2sas@' + result['pci']
                    name = name_with_bdf if count > 1 else 'Drv-mpt2sas'
                    version_mapping[name] = result['version']

            if 'Drv-mpt3sas' in counter:
                command = "../tools/raid/sas3ircu %d display"
                count = counter['Drv-mpt3sas']
                for i in range(0, counter['Drv-mpt3sas']):
                    result = get_raid_fm_version(command % i)
                    name_with_bdf = 'Drv-mpt3sas@' + result['pci']
                    name = name_with_bdf if count > 1 else 'Drv-mpt3sas'
                    version_mapping[name] = result['version']

            if 'Drv-megaraid_sas' in counter:
                command = "../tools/raid/storcli64 /c%d show"
                count = counter['Drv-megaraid_sas']
                for i in range(0, counter['Drv-megaraid_sas']):
                    result = get_raid_fm_version(command % i)
                    name_with_bdf = 'Drv-megaraid_sas@' + result['pci']
                    name = name_with_bdf if count > 1 else 'Drv-megaraid_sas'
                    version_mapping[name] = result['version']

            print("Final raid version mapping: " + str(version_mapping))

            for k, item in list.items():
                if 'type' in item and item['type'] == 'raid':
                    value = item.copy()
                    if k.find("@") == -1:
                        version = version_mapping[k]
                    else:
                        for key in version_mapping.keys():
                            if is_same_pcie(key.split("@")[1], k.split("@")[1]):
                                version = version_mapping[key]
                                break
                    value["ver"] = version.replace(' ', '.').replace('-', '.')
                    value["mode"] = MODE_INBAND
                    list[PREF_FIRMWARE + k[4:]] = value

        _getNET()
        _getDISK()
        _getRAID()
        return

    # Get hardwares outband FW (use redfish interface, retrieve from iBMC)
    def get_outband_firmwares(self, list):
        # Obtain upgradeable firmware collection resources.
        url = "/redfish/v1/UpdateService/FirmwareInventory"
        resp = self.client.get_resource(url)
        if resp is None or 200 != resp['status_code']:
            return None
        members = resp['resource']['Members']
        for member in members:
            if ODATA_ID_KEY not in member:
                continue
            url = member[ODATA_ID_KEY]
            if url.lower().find('activebmc') >= 0:
                type_ = TYPE_BMC
            elif url.lower().find('bios') >= 0:
                type_ = TYPE_BIOS
            else:
                continue
            resp = self.client.get_resource(url)
            if None == resp or 200 != resp['status_code']:
                continue
            # name: ver, device, vendor, subsystem_device, subsystem_vendor
            # mapping ActiveBMC to iBMC
            name = resp['resource']['Name'] if type_ != 'ibmc' else 'iBMC'
            name = PREF_FIRMWARE + name
            value = dict(ver=resp['resource']['Version'],
                         mode=MODE_OUTBAND,
                         type=type_,
                         device="",
                         vendor="",
                         subsystem_device="",
                         subsystem_vendor="",
                         name=name)
            list[name] = value
        return

    '''
    # Retrieve .repodata/xxx_primary.xml file data as string
    #   It contain all driver's name/version/location/... informations
    '''

    def _getPrimaryXML(self, url):
        s = self._downHttpFileAsString(url + "/repodata/repomd.xml")
        href = None
        try:
            doc = parseString(s)
            try:
                root = doc.documentElement
                datas = root.getElementsByTagName("data") if root else []
                for data in datas:
                    type = data.getAttribute("type")
                    if "primary" != type:
                        continue
                    locas = data.getElementsByTagName(
                        "location") if data else []
                    for loca in locas:
                        href = loca.getAttribute("href")
                        break
                    if None != href and len(href) > 0:
                        break
            finally:
                del doc
        except:
            print("Could not parse primary.xml file")
            return ''
        s = self._downHttpFileAsString(url + "/" + href)
        return self._unGzData(s)

    # Pickup drivers that contain in repo servers XML
    # (means server support the hardware)
    def _driverExistsInXML(self, list):
        result = {}
        url = self._getRepoURL()
        xml = self._getPrimaryXML(url)
        if None == xml or len(xml) <= 0:
            self._error(1, "Failed to get primary.xml from driver reposerver!")
        try:
            doc = parseString(xml)
            try:
                root = doc.documentElement
                for k, v in list.items():
                    if not k.startswith(PREF_DRIVER):
                        continue
                    name = k[4:].split("@")[0]
                    vers = []
                    vmax = ""
                    pkgs = root.getElementsByTagName("package") if root else []
                    for pkg in pkgs:
                        nam = pkg.getElementsByTagName("name") if pkg else []
                        if len(nam) <= 0:
                            continue
                        if (name != nam[0].childNodes[0].data) and (
                                    ("kmod-" + name) != nam[0].childNodes[
                                    0].data):
                            continue
                        ver = pkg.getElementsByTagName("version") if pkg else []
                        loc = pkg.getElementsByTagName(
                            "location") if pkg else []
                        if len(nam) <= 0 or len(ver) <= 0 or len(loc) <= 0:
                            continue
                        ver = ver[0].getAttribute("ver")
                        loc = loc[0].getAttribute("href")
                        if ver > vmax:
                            vmax = ver
                        vers.append(
                            {"version": ver, "location": url + "/" + loc})
                    if len(vers) <= 0:
                        continue
                    vlist2 = []
                    for ver in vers:
                        vlist2.append(ver["version"])
                    result[k] = {"mode": v["mode"], "type": v["type"],
                                 "v-use": v["ver"], "v-max": vmax,
                                 "vlist": vlist2, "vlist2": vers}
            finally:
                del doc
        except:
            print("Could not parse primary.xml file")
        return result

    # Pickup inband and outband FWs that contain in repo server XML
    def _firmwareExistsInXML(self, list):
        # the machine's unique id
        uid = self._get_product_unique_id()
        result = {}
        url = self._getRepoURL(True)
        xml = self._getPrimaryXML(url)
        if None == xml or len(xml) <= 0:
            self._error(1,
                        "Failed to get primary.xml from firmware reposerver!")
            # test code for houp firmware repo server not ready
            # with open("../driver/f4440b51dad237c1bafb447ee9c90c0903e5d03367a205b614eed328ea466004-primary.xml", "rb") as fp:
            #    xml = fp.read()
        try:
            doc = parseString(xml)
            try:
                root = doc.documentElement
                for item_key, item in list.items():
                    # Only check FWs (inband and outband)
                    if not item_key.startswith(PREF_FIRMWARE):
                        continue
                    item_name = item_key[3:]
                    try:
                        # some drivers/FWs use SN as postfix,
                        # need remove the postfix before compare
                        item_name = item_name[:item_name.rindex("@")]
                    except:
                        pass
                    vers = []
                    vmax = ""
                    pkgs = root.getElementsByTagName("package") if root else []

                    # WTF...
                    for pkg in pkgs:
                        nam = pkg.getElementsByTagName("name") if pkg else []
                        if len(nam) <= 0:
                            continue
                        if item["mode"] == MODE_INBAND:  # Inband FW part
                            if item["type"] == "disk":
                                # name is disktool output [Device Model]
                                entries = pkg.getElementsByTagName(
                                    "rpm:entry") if pkg else []
                                found = False
                                for entry in entries:
                                    entry_name = entry.getAttribute("name")
                                    if entry_name.startswith(SPT_MODEL_UID_KEY):
                                        supports = entry_name.split("=")[1]
                                        found = any(s in item_name for s in
                                                    supports.split(";"))
                                        if found:
                                            break
                                if not found:
                                    continue
                            else:  # net, raid, ...
                                uid2 = item["vendor"] + "." + item[
                                    "device"] + "." + item[
                                           "subsystem_vendor"] + "." + item[
                                           "subsystem_device"]
                                entries = pkg.getElementsByTagName(
                                    "rpm:entry") if pkg else []
                                found = False
                                for entry in entries:
                                    entry_name = entry.getAttribute("name")
                                    if entry_name.startswith(
                                            SPT_MODEL_UID_KEY) and entry_name.find(
                                        uid2) > 0:
                                        found = True
                                        break
                                if not found:
                                    continue
                        # Outband FW part
                        elif item["mode"] == MODE_OUTBAND and uid != None:
                            if nam[0].childNodes[0].data.lower().find(
                                    item["type"]) < 0:
                                continue
                            entries = pkg.getElementsByTagName(
                                "rpm:entry") if pkg else []
                            found = False
                            for entry in entries:
                                entry_name = entry.getAttribute("name")
                                if entry_name.startswith(
                                        SPT_MODEL_UID_KEY) and entry_name.find(
                                    uid) > 0:
                                    found = True
                                    break
                            if not found:
                                continue
                        else:
                            continue
                        ver = pkg.getElementsByTagName("version") if pkg else []
                        loc = pkg.getElementsByTagName(
                            "location") if pkg else []
                        if len(nam) <= 0 or len(ver) <= 0 or len(loc) <= 0:
                            continue
                        ver = ver[0].getAttribute("ver")
                        loc = loc[0].getAttribute("href")
                        if ver > vmax:
                            vmax = ver
                        vers.append(
                            {"version": ver, "location": url + "/" + loc})
                    if len(vers) <= 0:
                        continue
                    vlist2 = []
                    for ver in vers:
                        vlist2.append(ver["version"])
                    result[item_key] = {"mode": item["mode"],
                                        "type": item["type"],
                                        "v-use": item["ver"], "v-max": vmax,
                                        "vlist": vlist2, "vlist2": vers}
            finally:
                del doc
        except:
            print("Could not parse primary.xml file")
        return result

    def run(self):
        # Read local all PCI drivers and filter its by driver_version.cfg file
        list = self._getDriverSW()
        print("[%s] =====> Driver List <=====" % now())
        print(json.dumps(list, sort_keys=True, indent=4))
        # list columns as below:
        #   name: ver, mode, type, path, vendor, device,subsystem_vendor, subsystem_device
        # Add Inband F/W
        self._getInbandFW(list)
        print("[%s] =====> Append Inband FW List <======" % now())
        print(json.dumps(list, sort_keys=True, indent=4))
        # Add Outband F/W
        self.get_outband_firmwares(list)
        print("[%s] =====> Append Outband FW List <=====" % now())
        print(json.dumps(list, sort_keys=True, indent=4))

        # Read repo-server filelists
        sws = self._driverExistsInXML(list)
        print("[%s] ==> Filtered by driver repo primary.xml <==" % now())
        print(json.dumps(sws, sort_keys=True, indent=4))

        fws = self._firmwareExistsInXML(list)
        print("[%s] ==> Filtered by firmware repo primary.xml <==" % now())
        print(json.dumps(fws, sort_keys=True, indent=4))
        data = {}
        for k, v in sws.items():
            data[k] = v
        for k, v in fws.items():
            data[k] = v
        print("[%s] ==> Filtered Results <==" % now())
        print(json.dumps(data, sort_keys=True, indent=4))

        with open("hsu_verify.dat", "wb") as file:
            pickle.dump(data, file)
        for k, v in data.items():
            del v["mode"]
            del v["vlist2"]
        self.result["data"] = data
        return

    def readable_print(self, target=sys.stdout):
        # print data as text format (human readable)
        if 0 != self.result['rc']:
            print("Failure: %s" % self.result["msg"])
        else:
            flatten = []
            for item, versions in self.result["data"].items():
                flatten.append([item,
                                versions.get("v-use", None),
                                versions.get("v-max", None),
                                ", ".join(versions.get("vlist", []))])

            from tabulate import tabulate
            headers = ["Item", "Current version", "Latest version",
                       "Available version"]
            print("[Upgrade item list]\n", file=target)
            print(tabulate(flatten, headers=headers, tablefmt='orgtbl'),
                  file=target)
