# 智能唤醒灯：软件最小系统

目前实现 **iPhone/网页设置 → Windows 本地后台 → ESP8266 保存 → 测试 LED 渐亮 → 修改/取消**。电脑模拟器使用同一套设备接口，页面始终把模拟器与实物分开显示。

已确认你的开发板是 **NodeMCU（带 USB）**，第一阶段只做灯光唤醒链路，新闻与中文语音下一阶段接入。默认编译环境已设为 `nodemcuv2`。

先从这里运行；完整产品规划保留在 [开发方案 v2](SMART_LAMP_DEVELOPMENT_PLAN.zh-CN.md)，本阶段的范围和差异见 [软件需求与架构](docs/SOFTWARE_MVP.zh-CN.md)。

## 1. 电脑上先跑通

在 PowerShell 打开本目录：

```powershell
cd E:\Code\SMART_LAMP
.\setup.ps1
.\run.ps1
```

另开一个终端：

```powershell
cd E:\Code\SMART_LAMP
.\simulate.ps1
```

打开 [电脑控制页](http://127.0.0.1:8765)。从 `config.local.json` 复制 `admin_token` 到页面登录框，点击“连接”，再点击“30 秒快速演示”。

如果本次会话已经启动后台和模拟器，可以直接打开控制页，不要再启动同端口的第二个后台。

如果 PowerShell 只因脚本执行策略阻止本项目脚本，可以直接执行对应 Python 命令，不必修改系统执行策略：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.lock.txt
.\.venv\Scripts\python.exe -m scripts.bootstrap
.\.venv\Scripts\python.exe -m backend
# 第二个终端：
.\.venv\Scripts\python.exe -m scripts.simulate
```

**预期结果：** 前约 10 秒等待，接着 20 秒逐渐变亮，再保持 10 秒，最后熄灭。界面中 `sim-01` 的圆灯和百分比会变化。

实物未接入时应显示“实物保存 0/1”。模拟器在线不能把它改成实物 1/1。

## 2. 用现有 ESP8266 接入

默认先使用 NodeMCU 开发板上的板载 LED，不需要购买新硬件。代码默认 GPIO2 且低电平亮；不同克隆板可能使用不同板载灯引脚，需要根据实物确认。若使用裸测试 LED，需要串联限流电阻，不能直接接到 GPIO。

1. 查看 `firmware/include/config.h`，填写自己的 `WIFI_SSID` 和 `WIFI_PASSWORD`。
2. 确认 `SERVER_URL` 是电脑的局域网 IP 和 8765 端口；不能在 ESP8266 上填写 `127.0.0.1`。
3. `DEVICE_TOKEN` 已由初始化脚本生成，应与本地配置中的 `lamp-a` 令牌相同。
4. 将板子用支持数据的 USB 线接入电脑，在设备管理器或下述命令中确认 COM 口。

```powershell
[System.IO.Ports.SerialPort]::GetPortNames()

# NodeMCU：先编译，再按实际串口烧录，例如 COM5
.\firmware.ps1 -Board nodemcuv2
.\firmware.ps1 -Board nodemcuv2 -Upload -Port COM5
.\firmware.ps1 -Monitor -Port COM5

# D1 mini 改为：
.\firmware.ps1 -Board d1_mini -Upload -Port COM5
```

`COM5` 只是示例，不代表已检测到你的板子。脚本不带 `-Upload` 时只编译。烧录会替换板上的当前固件。

如果板载灯引脚不同，修改 `LAMP_LED_PIN` 和 `LAMP_LED_ACTIVE_LOW`。外接带电阻 LED 可选 GPIO14，常规接法配置 `ACTIVE_LOW=false`；本阶段不要按完整产品的恒流驱动接线。

电脑、iPhone、ESP8266 连接可互访的家中网络，ESP8266 使用 2.4 GHz。电脑需保持运行、避免睡眠。Windows 防火墙如阻止访问，应仅在可信的专用网络允许该后台；不要关闭整个防火墙。

接入成功后，串口有状态日志，页面中的 `lamp-a` 显示在线，收到并保存计划后显示“实物保存 1/1”。

## 3. iPhone 设置

按 [快捷指令步骤](shortcuts/SETUP.zh-CN.md) 创建“设置唤醒灯”。初版通过家中局域网 HTTP 调试；正式 HTTPS/MQTT 升级仍按产品文档进行。

快捷指令需要电脑的局域网地址，可查看 `config.local.json` 的 `server_url`。这里的地址是初始化时检测的，电脑换网络/IP 后要更新快捷指令与固件。

## 4. 修改、取消与断网

- 网页调整时间/亮度后点“保存 / 修改”，版本递增。
- 点“取消本次”，设备保存新版本后熄灭。离线设备未收到取消时可能继续旧计划，界面明确显示待保存。
- ESP8266 已完成一次同步和校时、保持供电时，断开网络仍能执行已经保存的计划。
- **目前没有外部 RTC：断电重启后必须重新连接电脑校时，才允许亮灯。** Flash 中有计划不代表知道现在几点。
- 这一阶段没有电池管理、三灯休眠、温度检测、新闻抓取或中文播报实现。

## 5. 验证

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\firmware.ps1 -Board nodemcuv2
.\firmware.ps1 -Board d1_mini
```

测试使用临时数据库，不修改正在运行的计划。C++ 调度引擎测试需要 `g++` 或 `clang++`；缺少编译器时 pytest 会标为 skipped，不应当作已验证。

本次实际结果见 [验证记录](docs/VERIFICATION.zh-CN.md)。编译成功、模拟验证和实物 LED 验证分别记录。

## 6. 目录

| 路径 | 用途 |
| --- | --- |
| `backend/` | FastAPI、SQLite、计划版本、认证和设备接口 |
| `web/index.html` | 手机/电脑控制页面 |
| `firmware/` | ESP8266 固件与可在电脑运行测试的 C++ 调度引擎 |
| `scripts/simulate.py` | 明确标注为模拟器的设备客户端 |
| `shortcuts/` | iPhone 设置、修改、取消步骤 |
| `tests/` | 后台和调度边界测试 |
| `config.local.json` | 本地令牌与设备配置，不提交版本库 |
| `firmware/include/config.h` | 本地 Wi-Fi 与设备配置，不提交版本库 |
| `data/` | 运行数据库、模拟器状态与日志 |

停止手动运行的后台或模拟器，使用各自终端的 `Ctrl+C`。也可运行 `.\stop-demo.ps1`，它只匹配本项目虚拟环境下运行后台/模拟器的 Python 进程树，避免误停其他 Python 项目。

