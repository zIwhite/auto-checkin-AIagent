# Trae CN 渠道 · 配置获取指南

本渠道支持 **Trae CN / TRAE SOLO CN** 的每日签到领积分。

## 需要填什么

「账号列表」每行一个账号：

```
TOKEN#DEVICE_ID#UID#备注
```

| 段 | 说明 |
|---|---|
| TOKEN | `refreshToken`（推荐，脚本自动换 accessToken）或 `accessToken`（JWT） |
| DEVICE_ID | **必须是 Trae 客户端注册过的真实设备号**，不能自己生成 |
| UID | 可留空，建议填写 |
| 备注 | 可省略 |

## 第一步：取真实设备号

在**装了 Trae / TRAE SOLO 客户端并登录过**的机器上运行：

```bash
python channels/trae/tools/get_device_id.py
```

输出形如：

```
>>> 设备号: 1234567890123456
```

设备号来自客户端 `storage.json` 里的键：

```
iCubeAuthInfo://icube-dc:1234567890123456
```

⚠️ 两个必须记住的限制：

- 自己生成的设备号会被服务端拒绝（错误码 **9074**）；
- **一个设备号一天只能签一个账号**，多账号需要多个真实设备号（每台装过客户端的机器一个）。

## 第二步：登录拿 token

在任意一台能打开浏览器的机器上运行：

```bash
python channels/trae/tools/login.py --device-id 1234567890123456
```

脚本会打印一个 Trae 登录链接：

1. 用浏览器打开，手机号/验证码登录；
2. 登录后会跳到打不开的 `http://127.0.0.1:18080/authorize?...`（正常现象）；
3. 复制地址栏完整链接，粘贴回脚本；
4. 脚本输出一整行 `TOKEN#DEVICE_ID#UID#备注`。

默认输出 **accessToken** 行（GitHub Actions 推荐，静态可用约 14 天）；如果要输出 refreshToken 行：

```bash
python channels/trae/tools/login.py --device-id ... --refresh
```

两者的区别：

- **accessToken**：静态可用约 14 天，到期后重新登录更新；GitHub Actions 用它最稳，不存在轮换状态问题。
- **refreshToken**：脚本每次运行会用 `/cloudide/api/v3/trae/oauth/ExchangeToken` 换新 accessToken。据部分实现观察可能不轮换、约半年有效；如果服务端轮换了 refreshToken，旧值会失效，需要重新登录。

## 第三步：填入 GitHub Secret 或平台任务

### GitHub Actions（推荐）

仓库 → Settings → Secrets and variables → Actions → New repository secret：

- Name: `TRAE_ACCOUNTS`
- Value: 上一步输出的那一整行

然后 Actions → **trae checkin** → Run workflow 手动验证一次。之后按每天一次的随机时间自动执行。

### 平台本地任务

「任务管理」→ 新建任务 → 渠道选 `trae`，把那一整行粘贴到「账号列表」。

## 常见错误

| 现象 | 原因 |
|---|---|
| 9074 | 设备号不对（生成号/别人的号），或服务端容量限制；前者需要真实设备号，后者换个时段 |
| 9095 | 当前设备今天已经签过；一天一个设备只能签一个账号 |
| 1001/1002 或 401 | token 失效，重新登录换取 |
| 缺少设备号 | 配置里 DEVICE_ID 为空或不是 12~20 位数字 |
| 未开放签到 | 账号侧活动未开放，不是脚本问题 |

## 风险说明

- 这是第三方接口自动化，可能违反 Trae 服务条款；最坏情况是积分收回或账号受限。
- 从 GitHub Actions 的云 IP 发请求，设备号虽然是真实的，但仍可能被风控记录；建议每天只签一次、不要高频重试。
- token / deviceId 只放在 GitHub Secrets 或本地数据库，不要提交到公开仓库。
