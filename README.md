# pi-mqtt

> 基于 Paho-MQTT 的 RS485 传感器数据采集服务，支持动态启停控制

## ✨ 特性

- 📡 **MQTT 驱动** - 通过 MQTT 主题动态控制传感器的启动与停止。
- 🔧 **配置驱动** - YAML 文件集中管理所有传感器，新增设备无需修改代码。
- 📊 **实时数据** - 后台轮询采集，通过 MQTT 实时发布最新数据。
- 🧩 **解析器支持** - 内置多种传感器数据解析器，轻松扩展。
- 🕊️ **轻量优雅** - 单文件实现核心逻辑，代码简洁，易于理解和维护。

## 🏗️ 项目结构

```
� pi-mqtt/
├── 🐍 main.py              # 应用主入口，包含所有核心逻辑
├── ⚙️ sensors.yaml         # MQTT、串口及传感器配置文件
└── 📋 requirements.txt     # 项目依赖
```

## �🚀 快速开始

### 1️⃣ 环境准备

```bash
# (可选) 创建并激活 Python 虚拟环境
uv venv
source .venv/bin/activate
```

### 2️⃣ 安装依赖

```bash
# 使用 uv 或 pip 安装依赖
uv pip install -r requirements.txt --index-url https://pypi.tuna.tsinghua.edu.cn/simple
```

### 3️⃣ 配置传感器

编辑 `sensors.yaml` 文件，根据你的设备修改 `serial`（串口）和 `sensors`（传感器列表）配置。

```yaml
# sensors.yaml
mqtt:
  broker: "mqtt.eclipseprojects.io"
  port: 1883
  # ... 其他 MQTT 配置

serial:
  port: /dev/ttyUSB0  # 修改为你的串口设备
  baudrate: 9600
  # ... 其他串口配置

sensors:
  angle_sensor_1:     # 传感器 ID
    slave_id: 80      # 从站地址
    address: 61       # 寄存器地址
    count: 2          # 寄存器数量
    parser: "angle"   # 解析器类型
  # ... 在此添加更多传感器
```

### 4️⃣ 启动服务

```bash
python main.py
```

服务启动后，将自动连接到 MQTT Broker 并开始轮询采集传感器数据。

## 🎮 使用方法 (MQTT API)

### 📡 控制传感器采集

通过向 `sensors/control` 主题发布消息来控制数据采集：

- **启动采集**: 发布 `start`
- **停止采集**: 发布 `stop`

**示例 (使用 mosquitto_pub):**

```bash
# 启动
mosquitto_pub -h mqtt.eclipseprojects.io -t sensors/control -m "start"

# 停止
mosquitto_pub -h mqtt.eclipseprojects.io -t sensors/control -m "stop"
```

### 📊 获取传感器数据

订阅 `sensors/data/#` 通配符主题，即可接收所有传感器的数据。每个传感器的数据会发布到独立的子主题 `sensors/data/{sensor_id}`。

**示例 (使用 mosquitto_sub):**

```bash
# 订阅所有传感器数据
mosquitto_sub -h mqtt.eclipseprojects.io -t "sensors/data/#" -v
```

**收到的数据格式 (JSON):**

```json
// topic: sensors/data/angle_sensor_1
{ "roll": -1.23, "pitch": 45.67 }
```

## 🔧 如何扩展

添加新的 RS485 传感器非常简单：

1.  **添加配置**: 在 `sensors.yaml` 的 `sensors` 列表下添加一个新的条目，定义其 `device_id`, `address`, `count` 和 `parser`。
2.  **(可选) 添加解析器**: 如果是新类型传感器，需要在 `main.py` 中添加一个对应的 `_parse_{parser_name}_data` 方法。
3.  **重启服务**：重新运行 `main.py` 即可。