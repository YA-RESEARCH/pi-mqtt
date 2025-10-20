
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

    def _load_config(self, config_path):
        """加载 YAML 配置文件"""
        with open(config_path, 'r', encoding='utf-8') as f:
            self.config = yaml.safe_load(f)
        logging.info("配置加载成功")

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
            logging.info(f"成功连接到 MQTT Broker，订阅控制主题: {control_topic}")
            client.subscribe(control_topic)
        else:
            logging.error(f"MQTT 连接失败，返回码: {rc}")

    def _on_message(self, client, userdata, msg):
        """MQTT 消息回调，处理控制命令"""
        command = msg.payload.decode()
        logging.info(f"收到控制命令: {command} on topic {msg.topic}")
        if command == "start":
            self.start_polling()
        elif command == "stop":
            self.stop_polling()

    def _poll_sensors(self):
        """轮询传感器并发布数据"""
        while self.is_running:
            with self.lock:
                if not self.modbus_client or not self.modbus_client.is_socket_open():
                    logging.warning("Modbus 未连接，尝试重连...")
                    if not self._connect_modbus():
                        time.sleep(5) # 重连失败，等待后重试
                        continue
                
                for sensor_id, config in self.config['sensors'].items():
                    data = self._read_sensor(sensor_id, config)
                    if data:
                        topic = f"{self.config['mqtt']['data_topic_prefix']}/{sensor_id}"
                        self.mqtt_client.publish(topic, json.dumps(data))
                        logging.debug(f"发布数据到 {topic}: {data}")
            time.sleep(self.config.get('polling_interval', 0.1))

    def _read_sensor(self, sensor_id, config):
        """读取单个传感器数据"""
        try:
            res = self.modbus_client.read_holding_registers(
                address=config['address'],
                count=config['count'],
                device_id=config['device_id']
            )
            if res.isError() or not res.registers:
                logging.warning(f"读取传感器 {sensor_id} 失败")
                return None
            
            parser = getattr(self, f"_parse_{config['parser']}_data", lambda r: {})
            return parser(res.registers)
        except Exception as e:
            logging.error(f"读取传感器 {sensor_id} 异常: {e}")
            self.modbus_client.close() # 发生异常时关闭连接，以便下次重连
            return None

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
