
import yaml
import threading
import time
import json
import logging
from pymodbus.client import ModbusSerialClient
import paho.mqtt.client as mqtt

# 配置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

class SensorMqttManager:
    def __init__(self, config_path="sensors.yaml"):
        self._load_config(config_path)
        self.modbus_client = None
        self.mqtt_client = None
        self.is_running = False
        self.polling_thread = None
        self.lock = threading.Lock()
        
        # 按变化发布机制的状态变量
        self.last_sensor_data = {}      # 缓存上次读取的数据
        self.last_publish_time = {}     # 缓存上次发布的时间戳
        self.force_publish_interval = self.config.get('force_publish_interval', 60)  # 强制发布间隔(秒)，默认60秒
        self.change_threshold = self.config.get('change_threshold', 0.1)  # 数值变化阈值，默认0.1
        
        self._classify_sensors()

    def _load_config(self, config_path):
        """加载 YAML 配置文件"""
        with open(config_path, 'r', encoding='utf-8') as f:
            self.config = yaml.safe_load(f)
        logging.info("配置加载成功")
    
    def _classify_sensors(self):
        """根据配置分类传感器（可读/可写）"""
        self.readable_sensors = {}
        self.writable_sensors = {}
        
        for sensor_id, config in self.config['sensors'].items():
            if 'read' in config:
                self.readable_sensors[sensor_id] = config
                logging.info(f"传感器 {sensor_id} 支持读取")
            if 'write' in config:
                self.writable_sensors[sensor_id] = config
                logging.info(f"传感器 {sensor_id} 支持写入")
        
        logging.info(f"共 {len(self.readable_sensors)} 个可读传感器, {len(self.writable_sensors)} 个可写传感器")
        logging.info(f"发布策略: 变化阈值={self.change_threshold}, 强制发布间隔={self.force_publish_interval}秒")

    def _connect_modbus(self):
        """连接 Modbus"""
        if self.modbus_client and self.modbus_client.is_socket_open():
            return True
        try:
            self.modbus_client = ModbusSerialClient(**self.config['serial'])
            if self.modbus_client.connect():
                logging.info(f"Modbus 连接成功: {self.config['serial']['port']}")
                return True
            else:
                logging.error("Modbus 连接失败")
                return False
        except Exception as e:
            logging.error(f"Modbus 连接异常: {e}")
            return False

    def _setup_mqtt(self):
        """设置并连接 MQTT"""
        mqtt_config = self.config['mqtt']
        self.mqtt_client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=mqtt_config['client_id'])
        self.mqtt_client.on_connect = self._on_connect
        self.mqtt_client.on_message = self._on_message
        try:
            self.mqtt_client.connect(mqtt_config['broker'], mqtt_config['port'], 60)
            self.mqtt_client.loop_start()
            logging.info(f"MQTT 连接成功: {mqtt_config['broker']}")
        except Exception as e:
            logging.error(f"MQTT 连接失败: {e}")

    def _on_connect(self, client, userdata, flags, rc, properties):
        """MQTT 连接回调"""
        if rc == 0:
            control_topic = self.config['mqtt']['control_topic']
            write_topic = self.config['mqtt']['write_topic']
            logging.info(f"成功连接到 MQTT Broker")
            client.subscribe(control_topic)
            client.subscribe(write_topic)
            logging.info(f"已订阅控制主题: {control_topic}")
            logging.info(f"已订阅写入主题: {write_topic}")
        else:
            logging.error(f"MQTT 连接失败，返回码: {rc}")

    def _on_message(self, client, userdata, msg):
        """MQTT 消息回调，处理控制命令和写入命令"""
        topic = msg.topic
        control_topic = self.config['mqtt']['control_topic']
        write_topic = self.config['mqtt']['write_topic']
        
        if topic == control_topic:
            # 处理控制命令
            command = msg.payload.decode()
            logging.info(f"收到控制命令: {command}")
            if command == "start":
                self.start_polling()
            elif command == "stop":
                self.stop_polling()
        elif topic == write_topic:
            # 处理写入命令
            try:
                payload = json.loads(msg.payload.decode())
                logging.info(f"收到写入命令: {payload}")
                self._handle_write_command(payload)
            except json.JSONDecodeError as e:
                logging.error(f"写入命令 JSON 解析失败: {e}")

    def _poll_sensors(self):
        """轮询传感器并发布数据（按变化发布 + 定时心跳）"""
        while self.is_running:
            with self.lock:
                if not self.modbus_client or not self.modbus_client.is_socket_open():
                    logging.warning("Modbus 未连接，尝试重连...")
                    if not self._connect_modbus():
                        time.sleep(5) # 重连失败，等待后重试
                        continue
                
                # 只轮询可读传感器
                for sensor_id, config in self.readable_sensors.items():
                    data = self._read_sensor(sensor_id, config)
                    if data:
                        # 检查数据是否变化和是否需要强制发布
                        data_changed = self._data_changed(sensor_id, data)
                        force_publish = self._should_force_publish(sensor_id)
                        
                        should_publish = data_changed or force_publish
                        
                        if should_publish:
                            topic = f"{self.config['mqtt']['read_topic']}/{sensor_id}"
                            self.mqtt_client.publish(topic, json.dumps(data))
                            
                            # 更新缓存
                            self.last_sensor_data[sensor_id] = data
                            self.last_publish_time[sensor_id] = time.time()
                            
                            # 根据是否变化记录不同的日志
                            if data_changed:
                                logging.info(f"📊 数据变化 - 发布到 {topic}: {data}")
                            else:
                                logging.info(f"💓 心跳发布 - 发布到 {topic}: {data}")
                        else:
                            logging.debug(f"⏭️  数据未变化，跳过发布: {sensor_id}")
                            
            time.sleep(self.config.get('polling_interval', 1))

    def _read_sensor(self, sensor_id, config):
        """读取单个传感器数据"""
        try:
            read_config = config['read']
            res = self.modbus_client.read_holding_registers(
                address=read_config['address'],
                count=read_config['count'],
                device_id=config['device_id']
            )
            if res.isError() or not res.registers:
                logging.warning(f"读取传感器 {sensor_id} 失败")
                return None
            
            parser = getattr(self, f"_parse_{read_config['parser']}_data", lambda r: {})
            return parser(res.registers)
        except Exception as e:
            logging.error(f"读取传感器 {sensor_id} 异常: {e}")
            self.modbus_client.close() # 发生异常时关闭连接，以便下次重连
            return None
    
    def _data_changed(self, sensor_id, new_data):
        """判断传感器数据是否发生变化
        
        Args:
            sensor_id: 传感器ID
            new_data: 新读取的数据
        
        Returns:
            bool: 数据是否变化
        """
        # 第一次读取，必须发布
        if sensor_id not in self.last_sensor_data:
            return True
        
        old_data = self.last_sensor_data[sensor_id]
        
        # 检查每个字段是否变化
        for key in new_data:
            old_val = old_data.get(key)
            new_val = new_data.get(key)
            
            if old_val is None:
                return True  # 新字段出现
            
            # 数值类型：使用阈值判断
            if isinstance(new_val, (int, float)):
                if abs(new_val - old_val) > self.change_threshold:
                    return True
            # 其他类型：直接比较
            elif old_val != new_val:
                return True
        
        return False
    
    def _should_force_publish(self, sensor_id):
        """检查是否需要强制发布（心跳机制）
        
        Args:
            sensor_id: 传感器ID
        
        Returns:
            bool: 是否需要强制发布
        """
        # 第一次发布
        if sensor_id not in self.last_publish_time:
            return True
        
        # 检查距离上次发布的时间
        elapsed = time.time() - self.last_publish_time[sensor_id]
        return elapsed >= self.force_publish_interval

    def _parse_angle_data(self, registers):
        """解析角度传感器数据"""
        to_signed = lambda val: val - 65536 if val & 0x8000 else val
        roll = round((to_signed(registers[0]) / 32768.0) * 180.0, 2)
        pitch = round((to_signed(registers[1]) / 32768.0) * 180.0, 2)
        return {"roll": roll, "pitch": pitch}

    def _parse_environmental_data(self, registers):
        """解析环境传感器数据"""
        to_signed = lambda val: val - 65536 if val & 0x8000 else val
        temperature = round(to_signed(registers[0]) / 10.0, 1)
        humidity = round(registers[1] / 10.0, 1)
        smoke = registers[2]
        return {"temperature": temperature, "humidity": humidity, "smoke": smoke}
    
    def _handle_write_command(self, payload):
        """处理写入命令
        
        消息格式: 
        {
            "sensor_id": "voltage_current_output",
            "data": {
                "voltage": 220.5,
                "current": 15.3
            }
        }
        """
        try:
            sensor_id = payload.get('sensor_id')
            data = payload.get('data')
            
            if not sensor_id or not data:
                logging.error("写入命令格式错误：缺少 sensor_id 或 data")
                return
            
            if sensor_id not in self.writable_sensors:
                logging.error(f"传感器 {sensor_id} 不支持写入")
                return
            
            success = self._write_sensor(sensor_id, data)
            if success:
                logging.info(f"成功写入传感器 {sensor_id}: {data}")
            else:
                logging.error(f"写入传感器 {sensor_id} 失败")
        except Exception as e:
            logging.error(f"处理写入命令异常: {e}")
    
    def _write_sensor(self, sensor_id, data):
        """写入单个传感器数据"""
        with self.lock:
            try:
                if not self.modbus_client or not self.modbus_client.is_socket_open():
                    logging.warning("Modbus 未连接，尝试重连...")
                    if not self._connect_modbus():
                        return False
                
                config = self.writable_sensors[sensor_id]
                write_config = config['write']
                
                # 根据 parser 类型转换数据为寄存器值
                parser_name = write_config['parser']
                encoder = getattr(self, f"_encode_{parser_name}_data", None)
                if not encoder:
                    logging.error(f"未找到编码器: _encode_{parser_name}_data")
                    return False
                
                registers = encoder(data)
                if not registers:
                    logging.error(f"数据编码失败: {data}")
                    return False
                
                # 写入寄存器
                res = self.modbus_client.write_registers(
                    address=write_config['address'],
                    values=registers,
                    device_id=config['device_id']
                )
                
                if res.isError():
                    logging.error(f"写入 Modbus 寄存器失败: {res}")
                    return False
                
                return True
            except Exception as e:
                logging.error(f"写入传感器 {sensor_id} 异常: {e}")
                if self.modbus_client and self.modbus_client.is_socket_open():
                    self.modbus_client.close()
                return False
    
    def _encode_analog_output_data(self, data):
        """编码模拟量输出数据为寄存器值
        
        根据文档: 16位无符号整形值，单位为微安(uA)
        
        电压表和电流表都通过4-20mA信号来模拟显示:
        
        电压表映射关系 (0-12V):
        - 显示值 0V  → 4mA  (4000 µA)
        - 显示值 12V → 20mA (20000 µA)
        - 公式: 实际电流(µA) = 4000 + (显示值 / 12) * 16000
        
        电流表映射关系 (0-200A):
        - 显示值 0A   → 4mA  (4000 µA)
        - 显示值 200A → 20mA (20000 µA)
        - 公式: 实际电流(µA) = 4000 + (显示值 / 200) * 16000
        
        输入格式: {"voltage": 10.5, "current": 150}  
        - voltage: 电压表显示值(0-12V)，会映射到4-20mA
        - current: 电流表显示值(0-200A)，会映射到4-20mA
        输出: [18000, 16000]  # [电压通道(µA), 电流通道(µA)]
        """
        try:
            voltage_display = data.get('voltage', 0)  # 电压表显示值 0-12
            current_display = data.get('current', 0)  # 电流表显示值 0-200
            
            # 电压: 显示值(0-12) -> 4-20mA (4000-20000 µA)
            # 线性映射公式: y = 4000 + (x / 12) * 16000
            voltage_reg = int(4000 + (voltage_display / 12.0) * 16000)
            
            # 电流: 显示值(0-200) -> 4-20mA (4000-20000 µA)
            # 线性映射公式: y = 4000 + (x / 200) * 16000
            current_reg = int(4000 + (current_display / 200.0) * 16000)

            # 确保在4-20mA范围内
            voltage_reg = max(4000, min(20000, voltage_reg))
            current_reg = max(4000, min(20000, current_reg))
            
            registers = [voltage_reg, current_reg]
            
            logging.info(f"编码模拟量输出: voltage={voltage_display}V→{voltage_reg}µA, current={current_display}A→{current_reg}µA, registers={registers}")
            return registers
        except Exception as e:
            logging.error(f"编码模拟量输出数据失败: {e}")
            return None

    def start_polling(self):
        """启动轮询线程"""
        if not self.is_running:
            self.is_running = True
            self.polling_thread = threading.Thread(target=self._poll_sensors)
            self.polling_thread.daemon = True
            self.polling_thread.start()
            logging.info("传感器轮询已启动")

    def stop_polling(self):
        """停止轮询线程"""
        if self.is_running:
            self.is_running = False
            if self.polling_thread:
                self.polling_thread.join()
            logging.info("传感器轮询已停止")

    def run(self):
        """运行管理器"""
        self._setup_mqtt()
        # 默认启动时开始轮询，也可以通过 MQTT 命令控制
        # self.start_polling()
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            logging.info("服务即将停止...")
        finally:
            self.stop()

    def stop(self):
        """停止管理器，清理资源"""
        self.stop_polling()
        if self.mqtt_client:
            self.mqtt_client.loop_stop()
            self.mqtt_client.disconnect()
            logging.info("MQTT 已断开")
        if self.modbus_client and self.modbus_client.is_socket_open():
            self.modbus_client.close()
            logging.info("Modbus 已断开")
        logging.info("服务已停止")

if __name__ == "__main__":
    manager = SensorMqttManager()
    manager.run()
