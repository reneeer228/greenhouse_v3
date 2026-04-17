import uasyncio as asyncio
from umqtt.simple import MQTTClient
from config import *
import ujson
import time

class MQTTManager:
    """Менеджер MQTT соединения"""
    
    def __init__(self, on_message_callback=None):
        self.client = None
        self.connected = False
        self.on_message = on_message_callback
        self._reconnect_attempts = 0
    
    def connect(self):
        """Подключение к MQTT брокеру"""
        try:
            self.client = MQTTClient(
                MQTT_CLIENT_ID,
                MQTT_BROKER,
                port=MQTT_PORT,
                user=MQTT_USER if MQTT_USER else None,
                password=MQTT_PASSWORD if MQTT_PASSWORD else None,
                keepalive=60
            )
            self.client.set_callback(self._message_callback)
            self.client.connect()
            self.connected = True
            self._reconnect_attempts = 0
            print(f"Подключено к MQTT: {MQTT_BROKER}")
            
            # Подписка на топики управления
            self.subscribe(MQTT_TOPIC_PUMP)
            self.subscribe(MQTT_TOPIC_VENT)
            self.subscribe(MQTT_TOPIC_CAMERA_CMD)
            
            return True
        except Exception as e:
            print(f"Ошибка подключения MQTT: {e}")
            self.connected = False
            return False
    
    def disconnect(self):
        """Отключение"""
        if self.client:
            try:
                self.client.disconnect()
            except:
                pass
        self.connected = False
    
    def _message_callback(self, topic, msg):
        """Обработка входящих сообщений"""
        print(f"MQTT сообщение: {topic} = {msg}")
        if self.on_message:
            self.on_message(topic, msg)
    
    def subscribe(self, topic):
        """Подписка на топик"""
        if self.client and self.connected:
            self.client.subscribe(topic)
            print(f"Подписка на: {topic}")
    
    def publish(self, topic, data, retain=False):
        """Публикация данных"""
        if self.client and self.connected:
            if isinstance(data, (dict, list)):
                data = ujson.dumps(data)
            self.client.publish(topic, data, retain=retain)
            return True
        return False
    
    def publish_sensor_data(self, sensor_data):
        """Публикация данных всех датчиков"""
        if not self.connected:
            return False
        
        try:
            # Публикация отдельных показателей
            self.publish(MQTT_TOPIC_TEMP, str(sensor_data['temperature']))
            self.publish(MQTT_TOPIC_HUMIDITY, str(sensor_data['humidity']))
            self.publish(MQTT_TOPIC_CO2, str(sensor_data['co2']))
            self.publish(MQTT_TOPIC_SOIL, str(sensor_data['soil_moisture']))
            self.publish(MQTT_TOPIC_LIGHT, str(sensor_data['light']))
            return True
        except Exception as e:
            print(f"Ошибка публикации: {e}")
            return False
    
    def publish_image(self, image_data):
        """Публикация изображения"""
        if self.connected and image_data:
            # Изображения большие, обычно отправляют base64 или ссылку
            return self.publish(MQTT_TOPIC_CAMERA, image_data)
        return False
    
    def check_msg(self):
        """Проверка входящих сообщений (неблокирующая)"""
        if self.client and self.connected:
            try:
                self.client.check_msg()
            except Exception as e:
                print(f"Ошибка проверки сообщений: {e}")
                self.connected = False
    
    def ping(self):
        """Пинг брокера"""
        if self.client and self.connected:
            try:
                self.client.ping()
            except:
                self.connected = False
    
    def reconnect(self):
        """Переподключение"""
        self._reconnect_attempts += 1
        if self._reconnect_attempts > 5:
            print("Слишком много попыток, жду 60 сек")
            time.sleep(60)
            self._reconnect_attempts = 0
        return self.connect()
