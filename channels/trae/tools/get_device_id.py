#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""从本机 Trae 客户端 storage.json 提取真实设备号（x-device-id）。

必须在装过 Trae / TRAE SOLO 客户端并登录过的机器上运行。
设备号不能自己生成：客户端注册过的号才能通过服务端设备校验。

用法：
    python get_device_id.py
"""
import json
import os
import sys

DC_PREFIX = "iCubeAuthInfo://icube-dc:"
DEVICE_MIN_LEN = 12
DEVICE_MAX_LEN = 20


def is_device_id(value):
    value = str(value or "").strip()
    return value.isdigit() and DEVICE_MIN_LEN <= len(value) <= DEVICE_MAX_LEN


def storage_files():
    home = os.path.expanduser("~")
    bases = []
    for base in (os.environ.get("APPDATA"), os.environ.get("LOCALAPPDATA"),
                 os.path.join(home, "Library", "Application Support"),
                 os.path.join(home, ".config")):
        if base and os.path.isdir(base) and base not in bases:
            bases.append(base)

    known = ("TRAE SOLO CN", "Trae CN", "TRAE SOLO", "Trae", "TraeWork", "TraeWork CN")
    found = []
    for base in bases:
        for name in known:
            path = os.path.join(base, name, "User", "globalStorage", "storage.json")
            if os.path.isfile(path) and path not in found:
                found.append(path)
        try:
            for entry in sorted(os.listdir(base)):
                if "trae" in entry.lower():
                    path = os.path.join(base, entry, "User", "globalStorage", "storage.json")
                    if os.path.isfile(path) and path not in found:
                        found.append(path)
        except OSError:
            pass
    return found


def device_ids_in(path):
    ids = []
    try:
        with open(path, "r", encoding="utf-8-sig", errors="replace") as fh:
            data = json.load(fh)
    except Exception as exc:
        print("  ⚠️ 读取失败: %s" % exc)
        return ids
    if not isinstance(data, dict):
        return ids
    for key, value in data.items():
        key = str(key or "")
        if key.startswith(DC_PREFIX):
            candidate = key[len(DC_PREFIX):].strip()
        elif key.rstrip(":") == DC_PREFIX.rstrip(":") and value is not None:
            candidate = str(value).strip()
        else:
            continue
        if is_device_id(candidate) and candidate not in ids:
            ids.append(candidate)
    return ids


def main():
    files = storage_files()
    if not files:
        print("未找到 Trae 的 storage.json。")
        print("请确认：1) 本机装的是 Trae / TRAE SOLO 客户端；2) 客户端已经登录过。")
        return 1
    print("找到 %d 个 storage.json：" % len(files))
    for path in files:
        print("  " + path)
    print()
    all_ids = []
    for path in files:
        ids = device_ids_in(path)
        if ids:
            pretty = "、".join(ids)
            print("  >>> 设备号: %s" % pretty)
            for item in ids:
                if item not in all_ids:
                    all_ids.append(item)
    if not all_ids:
        print("没有在里面找到 iCubeAuthInfo://icube-dc:<数字> 形式的设备号。")
        print("请确认客户端已登录，或换一个 storage.json 再试。")
        return 1
    print()
    print("把上面的设备号填到账号配置第二段，例如：")
    print("  TOKEN#%s#UID#备注" % all_ids[0])
    return 0


if __name__ == "__main__":
    code = main()
    try:
        input("\n按回车键退出...")
    except EOFError:
        pass
    sys.exit(code)
