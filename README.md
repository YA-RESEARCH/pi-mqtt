# pi-mqtt

> 基于 Paho-MQTT 的 RS485 传感器数据采集与控制服务，支持传感器读取和写入

## ✨ 特性

- 📡 **MQTT 驱动** - 通过 MQTT 主题动态控制传感器的读写操作
- 🔧 **配置驱动** - YAML 文件集中管理所有传感器，新增设备无需修改代码
- 📊 **双向通信** - 支持读取传感器数据和写入控制命令
- 🎯 **能力声明** - 通过 `read`/`write` 字段灵活声明传感器能力
- 🧩 **解析器支持** - 内置多种传感器数据解析器，轻松扩展
- � **智能发布** - 按变化发布 + 定时心跳，减少90%以上的冗余消息
- �🕊️ **轻量优雅** - 单文件实现核心逻辑，代码简洁，易于理解和维护

## 🏗️ 项目结构

```
pi-mqtt/
├── 🐍 main.py              # 应用主入口，包含所有核心逻辑
├── ⚙️ sensors.yaml         # MQTT、串口及传感器配置文件
└── 📋 requirements.txt     # 项目依赖
```

## 🚀 快速开始

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
  broker: "172.16.20.4"
  port: 1883
  read_topic: "CO2Weld_K3/workstation/1/sensors/read"    # 读取数据发布主题
  write_topic: "CO2Weld_K3/workstation/1/sensors/write"  # 写入命令订阅主题
  control_topic: "CO2Weld_K3/workstation/1/sensors/control"  # 控制命令主题

serial:
  port: /dev/ttyUSB0  # 修改为你的串口设备
  baudrate: 9600
  parity: N
  stopbits: 1
  bytesize: 8
  timeout: 1

# 发布策略配置（可选）
polling_interval: 1              # 轮询间隔(秒)，默认1秒
force_publish_interval: 60       # 强制发布间隔(秒)，无论数据是否变化都会发布（心跳机制），默认60秒
change_threshold: 0.1            # 数值变化阈值，小于此值的变化不触发发布，默认0.1

sensors:
  # 只读传感器示例
  angle_sensor_1:
    device_id: 80
    read:
      address: 61       # 寄存器地址（支持十进制或0x开头的十六进制）
      count: 2          # 寄存器数量
      parser: "angle"   # 解析器类型
  
  # 可读可写传感器示例
  env_sensor_1:
    device_id: 81
    read:
      address: 0
      count: 3
      parser: "environmental"
    write:
      address: 0
      count: 3
      parser: "environmental"
  
  # 只写传感器示例（模拟量输出）
  voltage_current_output:
    device_id: 1
    write:
      address: 0x0056   # 第7路模拟量输出起始地址
      count: 2          # 2路输出：第1路电压，第2路电流
      parser: "analog_output"
```

### 4️⃣ 启动服务

```bash
python main.py
```

服务启动后，将自动连接到 MQTT Broker 并开始轮询采集传感器数据。

## 💡 智能发布策略

为了减少网络带宽消耗和 MQTT 消息冗余，系统采用**按变化发布 + 定时心跳**的智能发布策略：

### 🎯 发布机制

| 触发条件 | 说明 | 示例 |
|---------|------|------|
| **数据变化** | 传感器数值变化超过阈值时立即发布 | 温度从 25.1°C → 25.3°C（变化0.2 > 阈值0.1） |
| **定时心跳** | 长时间无变化时定期发布，证明系统在线 | 60秒未发布则强制发布一次 |
| **首次读取** | 首次读取到数据必定发布 | 启动时首次读取 |

### ⚙️ 配置参数

在 `sensors.yaml` 中可以自定义发布策略：

```yaml
# 发布策略配置
polling_interval: 1              # 轮询间隔(秒)，默认1秒
force_publish_interval: 60       # 强制发布间隔(秒)，默认60秒
change_threshold: 0.1            # 数值变化阈值，默认0.1
```

**参数说明：**
- `polling_interval`: 传感器数据读取频率，建议 0.1-5 秒
- `force_publish_interval`: 心跳间隔，建议 30-300 秒
- `change_threshold`: 数值变化阈值，低于此值的变化不会触发发布

### 📊 效果对比

以 3 个传感器为例（温湿度、角度、烟雾）：

| 策略 | 每秒消息数 | 每小时消息数 | 网络流量节省 |
|------|-----------|-------------|-------------|
| 传统方式（每次轮询都发布） | 3 条/秒 | 10,800 条 | 0% |
| **智能发布（当前方式）** | 0.1-0.5 条/秒 | 360-1,800 条 | **90%+** |

### 📝 日志说明

启用智能发布后，日志会清晰标识每次发布的原因：

```
📊 数据变化 - 发布到 .../read/angle_sensor_1: {"roll": 12.5, "pitch": 3.2}
💓 心跳发布 - 发布到 .../read/env_sensor_1: {"temperature": 25.3, "humidity": 60.5, "smoke": 120}
⏭️  数据未变化，跳过发布: angle_sensor_1
```

## 🎮 使用方法 (MQTT API)

### 📡 控制传感器采集

通过向控制主题发布消息来控制数据采集：

- **启动采集**: 发布 `start` 到 `CO2Weld_K3/workstation/1/sensors/control`
- **停止采集**: 发布 `stop` 到 `CO2Weld_K3/workstation/1/sensors/control`

**示例 (使用 mosquitto_pub):**

```bash
# 启动读取
mosquitto_pub -h 172.16.20.4 -t "CO2Weld_K3/workstation/1/sensors/control" -m "start"

# 停止读取
mosquitto_pub -h 172.16.20.4 -t "CO2Weld_K3/workstation/1/sensors/control" -m "stop"
```

### 📊 读取传感器数据

订阅读取主题的通配符，即可接收所有传感器的数据。每个传感器的数据会发布到独立的子主题。

**示例 (使用 mosquitto_sub):**

```bash
# 订阅所有传感器数据
mosquitto_sub -h 172.16.20.4 -t "CO2Weld_K3/workstation/1/sensors/read/#" -v
```

**收到的数据格式 (JSON):**

```json
// topic: CO2Weld_K3/workstation/1/sensors/read/angle_sensor_1
{"roll": -1.23, "pitch": 45.67}

// topic: CO2Weld_K3/workstation/1/sensors/read/env_sensor_1
{"temperature": 25.3, "humidity": 60.5, "smoke": 120}
```

### ✍️ 写入传感器数据

通过向写入主题发布 JSON 消息来控制传感器输出。

**消息格式:**

```json
{
  "sensor_id": "voltage_current_output",
  "data": {
    "voltage": 10.5,
    "current": 150
  }
}
```

**字段说明:**
- `voltage`: **电压表显示值(0-12V)**，会自动映射到 4-20mA 输出
- `current`: **电流表显示值(0-200A)**，会自动映射到 4-20mA 输出

**映射关系说明:**

电压表和电流表都是通过 4-20mA 模拟信号来显示的，系统会自动进行线性映射：

| 表类型 | 显示范围 | 对应输出 | 映射公式 |
|--------|----------|----------|----------|
| 电压表 | 0-12V | 4-20mA | `实际输出(µA) = 4000 + (显示值 / 12) × 16000` |
| 电流表 | 0-200A | 4-20mA | `实际输出(µA) = 4000 + (显示值 / 200) × 16000` |

**映射示例:**

```
电压表:
  显示值 0V   →  输出 4mA  (4000 µA)
  显示值 6V   →  输出 12mA (12000 µA)
  显示值 12V  →  输出 20mA (20000 µA)

电流表:
  显示值 0A   →  输出 4mA  (4000 µA)
  显示值 100A →  输出 12mA (12000 µA)
  显示值 200A →  输出 20mA (20000 µA)
```

**示例 (使用 mosquitto_pub):**

```bash
# 设置电压表显示10.5V，电流表显示150A
mosquitto_pub -h 172.16.20.4 -t "CO2Weld_K3/workstation/1/sensors/write" \
  -m '{"sensor_id":"voltage_current_output","data":{"voltage":10.5,"current":150}}'

# 设置电压表显示0V，电流表显示0A（都输出4mA，最小值）
mosquitto_pub -h 172.16.20.4 -t "CO2Weld_K3/workstation/1/sensors/write" \
  -m '{"sensor_id":"voltage_current_output","data":{"voltage":0,"current":0}}'

# 设置电压表显示12V，电流表显示200A（都输出20mA，满刻度）
mosquitto_pub -h 172.16.20.4 -t "CO2Weld_K3/workstation/1/sensors/write" \
  -m '{"sensor_id":"voltage_current_output","data":{"voltage":12,"current":200}}'

# 设置电压表显示6V，电流表显示100A（都输出12mA，中间值）
mosquitto_pub -h 172.16.20.4 -t "CO2Weld_K3/workstation/1/sensors/write" \
  -m '{"sensor_id":"voltage_current_output","data":{"voltage":6,"current":100}}'
```

## 🔧 如何扩展

### 添加新的传感器

添加新的 RS485 传感器非常简单：

#### 1️⃣ 只读传感器

在 `sensors.yaml` 中添加：

```yaml
sensors:
  new_sensor:
    device_id: 85
    read:
      address: 100
      count: 4
      parser: "custom"
```

#### 2️⃣ 只写传感器

```yaml
sensors:
  new_output:
    device_id: 86
    write:
      address: 200
      count: 2
      parser: "custom_output"
```

#### 3️⃣ 可读可写传感器

```yaml
sensors:
  new_rw_sensor:
    device_id: 87
    read:
      address: 50
      count: 2
      parser: "custom"
    write:
      address: 60  # 可以与读地址不同
      count: 2
      parser: "custom_output"
```

### 添加自定义解析器

如果是新类型传感器，需要在 `main.py` 中添加对应的解析器方法：

```python
# 读取解析器
def _parse_custom_data(self, registers):
    """解析自定义传感器数据"""
    value1 = registers[0]
    value2 = registers[1]
    return {"value1": value1, "value2": value2}

# 写入编码器
def _encode_custom_output_data(self, data):
    """编码自定义输出数据"""
    reg1 = data.get('value1', 0)
    reg2 = data.get('value2', 0)
    return [reg1, reg2]
```

重启服务即可。