#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Trae CN 一次性登录，生成 GitHub Secret 需要的账号行。

流程：
  1. 输入真实设备号（先跑 get_device_id.py 获取，不能自己编）；
  2. 脚本打印一个登录链接，用浏览器打开并登录；
  3. 登录后浏览器会跳到打不开的 127.0.0.1 地址，复制地址栏完整链接；
  4. 粘贴回来，脚本解析出 refreshToken / accessToken / UID，并输出账号行。

用法：
    python login.py --device-id 1234567890123456
    python login.py --device-id ... --refresh     # 输出 refreshToken 行（默认）
    python login.py --device-id ... --access      # 输出 accessToken 行（约 14 天过期）
"""
import argparse
import base64
import json
import os
import secrets
import socket
import subprocess
import sys
import urllib.parse
import urllib.request
from urllib.error import HTTPError, URLError

CLIENT_ID = "en1oxy7wnw8j9n"
APP_VERSION = "0.1.43"
PLUGIN_VERSION = "2.3.62834"
UA = "Trae/" + APP_VERSION
LOGIN_PAGE = "https://www.trae.cn/authorization"
UG_HOST = "https://api.trae.cn"
OAUTH_HOST = "https://api.trae.com.cn"
EP_STATUS = UG_HOST + "/trae/api/v2/ug/checkin_credits/status"
EP_EXCHANGE = OAUTH_HOST + "/cloudide/api/v3/trae/oauth/ExchangeToken"
CALLBACK_PORT = 18080


def http_post(url, headers, body_obj):
    data = json.dumps(body_obj, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=25) as resp:
            return resp.status, resp.read().decode("utf-8", "replace")
    except HTTPError as exc:
        return exc.code, exc.read().decode("utf-8", "replace")
    except URLError as exc:
        return 0, "URLError: %s" % exc


def build_login_url(machine_id, device_id, port=CALLBACK_PORT):
    params = {
        "login_version": "1",
        "auth_from": "solo",
        "login_channel": "native_ide",
        "plugin_version": PLUGIN_VERSION,
        "auth_type": "local",
        "client_id": CLIENT_ID,
        "redirect": "0",
        "login_trace_id": secrets.token_hex(8),
        "auth_callback_url": "http://127.0.0.1:%d/authorize" % port,
        "machine_id": machine_id,
        "device_id": device_id,
        "x_device_id": device_id,
        "x_machine_id": machine_id,
        "x_device_brand": "PC",
        "x_device_type": "PC",
        "x_os_version": "1.0",
        "x_app_version": APP_VERSION,
        "x_app_type": "stable",
    }
    return LOGIN_PAGE + "?" + urllib.parse.urlencode(params)


def json_param(raw):
    if not raw:
        return {}
    for value in (raw, urllib.parse.unquote(raw)):
        try:
            obj = json.loads(value)
            return obj if isinstance(obj, dict) else {}
        except Exception:
            continue
    return {}


def jwt_payload(token):
    try:
        part = token.split(".")[1]
        part += "=" * (-len(part) % 4)
        return json.loads(base64.urlsafe_b64decode(part).decode("utf-8", "replace"))
    except Exception:
        return {}


def parse_callback(raw):
    raw = (raw or "").strip()
    if not raw:
        return {}
    if not raw.lower().startswith(("http://", "https://")):
        return {"refresh": raw}

    query = urllib.parse.parse_qs(urllib.parse.urlparse(raw).query)
    one = lambda key: (query.get(key) or [""])[0]  # noqa: E731
    user_info = json_param(one("userInfo"))
    user_jwt = json_param(one("userJwt"))
    refresh = (one("refreshToken") or one("refresh_token")
               or user_jwt.get("RefreshToken") or "")
    if not refresh and one("data") and not one("data").lstrip().startswith("{"):
        refresh = one("data")
    access = user_jwt.get("Token") or ""
    uid = str(user_info.get("UserID") or user_jwt.get("UserID") or "")
    if not uid and access:
        uid = str(jwt_payload(access).get("sub") or "")
    nickname = str(user_info.get("ScreenName") or "")
    return {"refresh": refresh, "access": access, "uid": uid, "nickname": nickname}


def exchange(refresh, uid):
    status, text = http_post(EP_EXCHANGE, {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "User-Agent": UA,
    }, {"ClientID": CLIENT_ID, "RefreshToken": refresh, "ClientSecret": "-", "UserID": uid or ""})
    try:
        obj = json.loads(text)
    except Exception:
        return None, "换 token 响应异常 (HTTP %s)" % status
    res = obj.get("Result") or obj.get("data") or obj
    token = res.get("Token") or res.get("AccessToken") or ""
    if not token:
        return None, "refreshToken 被拒 (HTTP %s): %s" % (status, text[:120])
    return {
        "access": token,
        "refresh": res.get("RefreshToken") or refresh,
        "uid": str(res.get("UserID") or uid or ""),
    }, "ok"


def verify(access, device):
    status, text = http_post(EP_STATUS, {
        "Authorization": "Cloud-IDE-JWT " + access,
        "X-User-Region": "CN",
        "Content-Type": "application/json",
        "Accept": "application/json",
        "User-Agent": UA,
        "x-device-id": device,
    }, {"req_source": 2})
    print("状态接口 HTTP %s: %s" % (status, text[:300]))
    return status


def port_busy(port):
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(0.5)
    try:
        sock.connect(("127.0.0.1", port))
        return True
    except Exception:
        return False
    finally:
        sock.close()


def copy_to_clipboard(text):
    try:
        import tkinter
        root = tkinter.Tk()
        root.withdraw()
        root.clipboard_clear()
        root.clipboard_append(text)
        root.update()
        root.destroy()
        return True
    except Exception:
        pass
    for cmd in (["clip"], ["pbcopy"]):
        try:
            subprocess.run(cmd, input=text.encode("utf-8"), check=True)
            return True
        except Exception:
            continue
    return False


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--device-id", dest="device", default="")
    parser.add_argument("--remark", default="主号")
    parser.add_argument("--access", action="store_true", help="输出 accessToken 行（默认）")
    parser.add_argument("--refresh", action="store_true", help="输出 refreshToken 行")
    parser.add_argument("--port", type=int, default=CALLBACK_PORT)
    args = parser.parse_args()

    device = (args.device or os.environ.get("TRAE_DEVICE_ID") or "").strip()
    if not device:
        device = input("请输入真实设备号（先运行 get_device_id.py 获取）: ").strip()
    if not (device.isdigit() and 12 <= len(device) <= 20):
        print("设备号格式不对：应为 12~20 位十进制数字。")
        return 1

    if port_busy(args.port):
        print("⚠️ 端口 %d 已被其他程序占用，浏览器回调可能被它接走。" % args.port)
        print("   请先关闭占用该端口的程序，或换一个端口：--port 18081")
        print()

    machine_id = secrets.token_hex(16)
    url = build_login_url(machine_id, device, args.port)
    print()
    print("=" * 66)
    print("在浏览器打开下面的链接，用手机号/验证码登录：")
    print()
    print(url)
    print()
    print("登录后会跳到打不开的 127.0.0.1 地址（正常现象）。")
    print("复制浏览器地址栏里的完整链接，粘贴到下面。")
    print("=" * 66)
    raw = input("\n粘贴回调链接（或直接粘贴 refreshToken）: ").strip()
    info = parse_callback(raw)
    if not info.get("refresh") and not info.get("access"):
        print("没有解析到 token。请确认粘贴的是完整的回调链接。")
        return 1

    access = info.get("access") or ""
    refresh = info.get("refresh") or ""
    uid = info.get("uid") or ""

    if not access and refresh:
        print("\n用 refreshToken 换取 accessToken 验证...")
        data, msg = exchange(refresh, uid)
        if data:
            access = data["access"]
            refresh = data["refresh"]
            uid = uid or data.get("uid", "")
        else:
            print("⚠️ %s" % msg)
    if access:
        status = verify(access, device)
        if status in (401, 403):
            print("⚠️ 状态接口返回 %s，token 可能无效。" % status)
    if not uid:
        uid = str(jwt_payload(access).get("sub") or "") if access else ""

    print()
    print("=" * 66)
    if args.refresh:
        line = "%s#%s#%s#%s" % (refresh, device, uid, args.remark)
        label = "refreshToken（可能轮换；确认不轮换再用于 GitHub Actions）"
    else:
        line = "%s#%s#%s#%s" % (access, device, uid, args.remark)
        label = "accessToken（约 14 天过期，需定期更新；GitHub Actions 推荐）"
    if not line.split("#")[0]:
        print("❌ 没有可用的 token，无法生成账号行。")
        return 1
    print("复制下面这一整行，填入 GitHub Secret 或渠道「账号列表」：")
    print()
    print(line)
    print()
    print("类型: %s" % label)
    if copy_to_clipboard(line):
        print("（已尝试复制到剪贴板）")
    print("=" * 66)
    return 0


if __name__ == "__main__":
    code = 1
    try:
        code = main()
    except Exception as exc:
        print("脚本异常: %s" % exc)
    try:
        input("\n按回车键退出...")
    except EOFError:
        pass
    sys.exit(code)
