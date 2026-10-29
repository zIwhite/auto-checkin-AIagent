#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""Trae CN / TRAE SOLO CN 每日签到渠道 (纯标准库, 无第三方依赖)。

账号配置格式(每行一个):
    TOKEN#DEVICE_ID#UID#备注

- TOKEN: refreshToken(推荐, 脚本会用 ExchangeToken 换 accessToken) 或 accessToken(JWT)
- DEVICE_ID: Trae 客户端注册过的真实设备号, 不能自己生成; 取法见渠道 README
- UID: 可留空, 但建议填写(部分接口会用到)
- 备注: 可省略, 可含 '#'

限制:
  - 一个设备号一天只能签一个账号; 多账号需要各自真实的设备号
  - 9074 = 服务端容量/风控拒绝, 不是重试就能解决
  - 详见 docs 与 channels/trae/README.md
"""
import base64
import datetime
import json
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

CLIENT_ID = "en1oxy7wnw8j9n"
APP_VERSION = "0.1.43"
UA = "Trae/" + APP_VERSION
UG_HOST = "https://api.trae.cn"
OAUTH_HOST = "https://api.trae.com.cn"
EP_STATUS = UG_HOST + "/trae/api/v2/ug/checkin_credits/status"
EP_CLAIM = UG_HOST + "/trae/api/v2/ug/checkin_credits/claim"
EP_EXCHANGE = OAUTH_HOST + "/cloudide/api/v3/trae/oauth/ExchangeToken"

# SOLO 谱系契约: body 必须是 {"req_source":2}; 空 body 或 1 会被判 9074
REQ_BODY = {"req_source": 2}
AUTH_FAIL_CODES = (1001, 1002)
RATE_CODE = 9074
ALREADY_CODE = 9095
RATE_HTTP = (429, 500, 502, 503, 504)
CONGESTION_HINTS = ("太多", "拥挤", "繁忙", "忙碌", "稍后", "频繁", "限流",
                    "too many", "busy", "later", "retry", "frequent")
ALREADY_HINTS = ("已签", "已领", "明日", "already", "claimed", "checked")
DEVICE_MIN_LEN = 12
DEVICE_MAX_LEN = 20

META = {
    "name": "Trae CN 每日签到",
    "version": "1.0.0",
    "author": "xuwangcheng",
    "description": "Trae CN / TRAE SOLO CN 每日签到领积分。需要真实设备号和 token; 详见渠道 README。",
    "config_schema": [
        {
            "key": "accounts", "label": "账号列表", "type": "textarea", "required": True,
            "placeholder": "TOKEN#DEVICE_ID#UID#备注\nTOKEN#DEVICE_ID#UID#备注",
            "help": "每行一个账号。TOKEN 填 refreshToken 或 accessToken; DEVICE_ID 必须是 Trae 客户端注册过的真实设备号; UID 可留空但建议填写。",
        },
        {"key": "dry_run", "label": "仅测试(不实际请求)", "type": "bool", "default": False},
    ],
}


def log(msg):
    print("[%s] %s" % (datetime.datetime.now().strftime("%H:%M:%S"), msg), flush=True)


def is_valid_device_id(value):
    value = str(value or "").strip()
    return value.isdigit() and DEVICE_MIN_LEN <= len(value) <= DEVICE_MAX_LEN


def is_jwt(token):
    return isinstance(token, str) and token.count(".") == 2


def jwt_payload(token):
    try:
        part = token.split(".")[1]
        part += "=" * (-len(part) % 4)
        payload = json.loads(base64.urlsafe_b64decode(part).decode("utf-8", "replace"))
        return payload if isinstance(payload, dict) else {}
    except Exception:
        return {}


def parse_account_line(line):
    line = (line or "").strip()
    if not line:
        return None
    parts = line.split("#")
    token = parts[0].strip()
    device = parts[1].strip() if len(parts) > 1 else ""
    uid = parts[2].strip() if len(parts) > 2 else ""
    remark = "#".join(parts[3:]).strip() if len(parts) > 3 else ""
    if not token or not device:
        return None
    if not is_valid_device_id(device):
        return {"error": "设备号格式不合法(需 12~20 位数字): %s" % device}
    return {"token": token, "device": device, "uid": uid, "remark": remark or "(未备注)"}


def load_accounts(config):
    accounts, errors = [], []
    for line in str(config.get("accounts") or "").splitlines():
        acc = parse_account_line(line)
        if not acc:
            continue
        if acc.get("error"):
            errors.append(acc["error"])
            continue
        accounts.append(acc)
    return accounts, errors


def find_value(obj, keys):
    """递归找第一个匹配键的值, 兼容 Result/data 等嵌套结构。"""
    if isinstance(obj, dict):
        for key in keys:
            if key in obj:
                return obj[key]
        for value in obj.values():
            found = find_value(value, keys)
            if found is not None:
                return found
    elif isinstance(obj, list):
        for value in obj:
            found = find_value(value, keys)
            if found is not None:
                return found
    return None


def first_value(obj, keys):
    if isinstance(obj, dict):
        for key in keys:
            if key in obj:
                return obj[key]
    return find_value(obj, keys)


def http_post(url, headers, body_obj):
    data = json.dumps(body_obj, ensure_ascii=False).encode("utf-8")
    req = Request(url, data=data, headers=headers, method="POST")
    try:
        with urlopen(req, timeout=25) as resp:
            text = resp.read().decode("utf-8", "replace")
            status = resp.status
    except HTTPError as e:
        status, text = e.code, e.read().decode("utf-8", "replace")
    except URLError as e:
        return 0, None, "URLError: %s" % e
    try:
        return status, json.loads(text), text
    except ValueError:
        return status, None, text


def exchange_token(refresh_token, uid):
    """refreshToken -> (ok, access_token, new_refresh, expires_at, message)"""
    body = {
        "ClientID": CLIENT_ID,
        "RefreshToken": refresh_token,
        "ClientSecret": "-",
        "UserID": uid or "",
    }
    status, obj, text = http_post(EP_EXCHANGE, {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "User-Agent": UA,
    }, body)
    if status == 0:
        return False, None, None, None, "网络错误: %s" % text[:120]
    if not isinstance(obj, dict):
        return False, None, None, None, "换 token 响应异常 (HTTP %s)" % status

    token = first_value(obj, ("Token", "AccessToken", "accessToken"))
    if not isinstance(token, str) or not token:
        err = find_value(obj, ("Message", "message", "Code", "code"))
        return False, None, None, None, "refreshToken 被拒: %s" % str(err or text[:120])[:160]

    new_refresh = first_value(obj, ("RefreshToken", "refreshToken")) or refresh_token
    exp = first_value(obj, ("TokenExpireAt", "expiresAt", "expires_at"))
    try:
        exp = int(exp) if exp else None
        if exp and exp > 10 ** 12:
            exp //= 1000
    except (TypeError, ValueError):
        exp = None
    if not exp:
        duration = first_value(obj, ("TokenExpireDuration", "expiresIn"))
        try:
            exp = int(datetime.datetime.now().timestamp()) + int(duration)
        except (TypeError, ValueError):
            exp = None
    return True, token, new_refresh, exp, "ok"


def ug_headers(token, device):
    return {
        "Authorization": "Cloud-IDE-JWT " + token,
        "X-User-Region": "CN",
        "Content-Type": "application/json",
        "Accept": "application/json",
        "User-Agent": UA,
        "x-device-id": device,
    }


def as_bool(value):
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        return value.strip().lower() in ("1", "true", "yes", "on")
    return bool(value)


def api_status(token, device):
    status, obj, text = http_post(EP_STATUS, ug_headers(token, device), REQ_BODY)
    if status == 0 or not isinstance(obj, dict):
        return {"http": status, "ok": False, "raw": text[:200]}
    root = obj.get("data") if isinstance(obj.get("data"), dict) else obj
    checked = first_value(root, ("checked_in", "checkedIn"))
    did = first_value(root, ("did_checked_in", "didCheckedIn"))
    credits = first_value(root, ("credits", "points"))
    enable = first_value(root, ("enable", "enabled"))
    code = first_value(obj, ("code", "Code"))
    msg = first_value(obj, ("message", "msg", "Message"))
    return {
        "http": status, "ok": status < 400,
        "checked": as_bool(checked),
        "did_checked": as_bool(did) if did is not None else None,
        "credits": credits,
        "enable": as_bool(enable) if enable is not None else None,
        "code": code, "msg": msg,
        "raw": text[:200],
    }


def api_claim(token, device):
    status, obj, text = http_post(EP_CLAIM, ug_headers(token, device), REQ_BODY)
    if status == 0:
        return status, None, "网络错误: %s" % text[:120], None, text
    if not isinstance(obj, dict):
        return status, None, text[:160], None, text
    code = first_value(obj, ("code", "Code"))
    msg = first_value(obj, ("message", "msg", "Message")) or ""
    gained = first_value(obj, ("points", "credits", "credit"))
    return status, code, str(msg), gained, text


def is_rate(code, status, msg):
    if code == RATE_CODE or status in RATE_HTTP:
        return True
    low = str(msg or "").lower()
    return any(hint in low for hint in CONGESTION_HINTS)


def is_already(code, msg):
    if code == ALREADY_CODE:
        return True
    low = str(msg or "").lower()
    return any(hint in low for hint in ALREADY_HINTS)


def resolve_access(acc):
    """返回 (ok, access_token, expires_at, note)"""
    token = acc["token"]
    if is_jwt(token):
        exp = jwt_payload(token).get("exp")
        return True, token, exp, "accessToken"
    ok, access, new_refresh, exp, msg = exchange_token(token, acc.get("uid"))
    if not ok:
        return False, None, None, msg
    if new_refresh and new_refresh != token:
        acc["new_refresh"] = new_refresh
        log("账号[%s] refreshToken 已轮换; GitHub Actions 需要更新Secret" % acc["remark"])
    return True, access, exp, "refreshToken"


def run_account(acc, dry):
    remark = acc["remark"]
    if dry:
        log("账号[%s] [dry-run] 跳过实际请求" % remark)
        return {"remark": remark, "ok": None, "msg": "[dry-run] 未执行", "credits": None,
                "expires_at": None}

    ok, access, exp, note = resolve_access(acc)
    expires_at = None
    if exp:
        try:
            expires_at = datetime.datetime.fromtimestamp(int(exp)).strftime("%Y-%m-%d %H:%M:%S")
        except (ValueError, OSError, OverflowError):
            expires_at = None
    if not ok:
        log("账号[%s] ❌ 鉴权失败: %s" % (remark, note))
        return {"remark": remark, "ok": False, "msg": "鉴权失败: %s" % note,
                "credits": None, "expires_at": expires_at}

    log("账号[%s] 已加载(%s, 设备号 %s)" % (remark, note, acc["device"]))
    state = api_status(access, acc["device"])
    if not state.get("ok"):
        msg = "状态查询失败 HTTP %s %s" % (state.get("http"), (state.get("raw") or "")[:100])
        if state.get("code") in AUTH_FAIL_CODES or state.get("http") in (401, 403):
            msg = "令牌失效, 请重新登录 Trae 获取新 token"
        log("账号[%s] ❌ %s" % (remark, msg))
        return {"remark": remark, "ok": False, "msg": msg, "credits": state.get("credits"),
                "expires_at": expires_at}

    if state.get("code") in AUTH_FAIL_CODES:
        log("账号[%s] ❌ 令牌失效" % remark)
        return {"remark": remark, "ok": False, "msg": "令牌失效, 请重新登录 Trae 获取新 token",
                "credits": state.get("credits"), "expires_at": expires_at}

    if state.get("checked"):
        log("账号[%s] 今日已签到" % remark)
        return {"remark": remark, "ok": True, "msg": "今日已签到", "credits": state.get("credits"),
                "expires_at": expires_at}

    if state.get("enable") is False:
        log("账号[%s] ❌ 该账号未开放签到(enable=false)" % remark)
        return {"remark": remark, "ok": False, "msg": "该账号未开放签到(enable=false)",
                "credits": state.get("credits"), "expires_at": expires_at}

    status, code, msg, gained, raw = api_claim(access, acc["device"])
    if code == 0:
        text = "签到成功" + (" +%s 积分" % gained if gained is not None else "")
        log("账号[%s] ✅ %s" % (remark, text))
        return {"remark": remark, "ok": True, "msg": text,
                "credits": gained if gained is not None else state.get("credits"),
                "expires_at": expires_at}

    if is_already(code, msg):
        log("账号[%s] 今日已签到(%s)" % (remark, msg or code))
        return {"remark": remark, "ok": True, "msg": "今日已签到(%s)" % (msg or code),
                "credits": state.get("credits"), "expires_at": expires_at}

    if is_rate(code, status, msg):
        text = "参与用户太多(%s), 本次未签到成功; 请下个时段再试" % (code or status)
        log("账号[%s] ❌ %s" % (remark, text))
        return {"remark": remark, "ok": False, "msg": text, "credits": state.get("credits"),
                "expires_at": expires_at}

    if code in AUTH_FAIL_CODES:
        text = "令牌失效(code=%s), 请重新登录 Trae 获取新 token" % code
    else:
        text = "签到失败 code=%s %s" % (code, (msg or "")[:80])
    log("账号[%s] ❌ %s" % (remark, text))
    return {"remark": remark, "ok": False, "msg": text, "credits": state.get("credits"),
            "expires_at": expires_at}


def run_status_only(accounts):
    results = []
    for acc in accounts:
        ok, access, _exp, note = resolve_access(acc)
        if not ok:
            log("账号[%s] 状态查询失败: %s" % (acc["remark"], note))
            results.append({"remark": acc["remark"], "checked_in": None})
            continue
        state = api_status(access, acc["device"])
        if not state.get("ok") or state.get("code") in AUTH_FAIL_CODES:
            log("账号[%s] 状态查询失败" % acc["remark"])
            results.append({"remark": acc["remark"], "checked_in": None})
            continue
        checked = bool(state.get("checked"))
        log("账号[%s] 今日签到状态: %s" % (acc["remark"], "已签到" if checked else "未签到"))
        results.append({"remark": acc["remark"], "checked_in": checked})
    all_checked = all(r["checked_in"] is True for r in results)
    return {
        "success": True,
        "message": "今日已签到" if all_checked else "今日未签到",
        "data": {"checked_in": all_checked, "accounts": results},
    }


def run(config):
    dry = bool(config.get("dry_run"))
    accounts, errors = load_accounts(config)
    if not accounts:
        message = "未找到任何账号"
        if errors:
            message += ": " + "; ".join(errors)
        else:
            message += ": 请在任务配置中填写账号列表 (格式 TOKEN#DEVICE_ID#UID#备注)"
        return {"success": False, "message": message}

    if config.get("status_only"):
        if dry:
            return {"success": True, "message": "dry-run", "data": {"checked_in": False}}
        return run_status_only(accounts)

    log("共加载 %d 个账号, 开始签到%s" % (len(accounts), " [dry-run]" if dry else ""))
    results = [run_account(acc, dry) for acc in accounts]

    ok_count = sum(1 for r in results if r.get("ok") is True)
    fail_count = sum(1 for r in results if r.get("ok") is False)
    date_str = datetime.date.today().strftime("%Y-%m-%d")
    if dry:
        title = "Trae 签到 [dry-run] (%d个账号)" % len(results)
    elif fail_count == 0:
        title = "Trae 签到全部成功 (%d/%d)" % (ok_count, len(results))
    else:
        title = "Trae 签到 %d成功 %d失败" % (ok_count, fail_count)

    lines = ["📅 %s Trae 每日签到 (共 %d 个账号)" % (date_str, len(results),), "─" * 28]
    for r in results:
        mark = "✅" if r.get("ok") is True else "➖" if r.get("ok") is None else "❌"
        lines.append("【%s】%s %s" % (r["remark"], mark, r["msg"]))
        if r.get("credits") is not None:
            lines.append("  当前积分: %s" % r["credits"])
    log("\n" + "\n".join(lines))

    expires_info = [{"label": r["remark"], "expires_at": r["expires_at"]}
                    for r in results if r.get("expires_at")]
    balance_info = [{"label": r["remark"], "value": r["credits"]}
                    for r in results if r.get("credits") is not None]
    return {
        "success": fail_count == 0,
        "message": title,
        "data": {"total": len(results), "ok": ok_count, "fail": fail_count,
                 "expires_info": expires_info, "balance_info": balance_info},
    }


# ==================== 平台引导代码, 无需修改 ====================
if __name__ == "__main__":
    import json as _json
    import sys as _sys

    try:
        _config = _json.loads(_sys.stdin.read() or "{}")
    except Exception:
        _config = {}
    try:
        _result = run(_config)
        if not isinstance(_result, dict):
            _result = {"success": False, "message": "run() 未返回字典"}
    except Exception as _exc:  # noqa: BLE001
        _result = {"success": False, "message": "脚本异常: %s" % _exc}
    print("__CHECKIN_RESULT__" + _json.dumps(_result, ensure_ascii=False))
