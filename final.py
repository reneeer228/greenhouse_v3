# ============================================================
# ИМПОРТЫ
# ============================================================
import network
import uasyncio as asyncio
import time
from machine import Pin, ADC, I2C, SPI
import dht
import ujson
from umqtt.simple import MQTTClient
import os
import gc

# ============================================================
# КОНФИГУРАЦИЯ
# ============================================================

# === Настройки WiFi ===
WIFI_SSID = "ВАШ_WIFI_SSID"
WIFI_PASSWORD = "ВАШ_WIFI_PASSWORD"

# === Настройки MQTT ===
MQTT_BROKER = "broker.hivemq.com"
MQTT_PORT = 1883
MQTT_CLIENT_ID = "pico_greenhouse_01"
MQTT_USER = ""
MQTT_PASSWORD = ""

# Топики MQTT
MQTT_TOPIC_TEMP = "greenhouse/temperature"
MQTT_TOPIC_HUMIDITY = "greenhouse/humidity"
MQTT_TOPIC_CO2 = "greenhouse/co2"
MQTT_TOPIC_SOIL = "greenhouse/soil_moisture"
MQTT_TOPIC_LIGHT = "greenhouse/light"
MQTT_TOPIC_PUMP = "greenhouse/pump/cmd"
MQTT_TOPIC_VENT = "greenhouse/vent/cmd"
MQTT_TOPIC_CAMERA = "greenhouse/camera/status"

# === Распиновка GPIO ===
PIN_DHT = 0
PIN_SOIL = 26
PIN_LIGHT = 27
PIN_CO2 = 28

PIN_LCD_SDA = 4
PIN_LCD_SCL = 5
LCD_I2C_ADDR = 0x27

PIN_PUMP = 6
PIN_VENT_STEP = 7
PIN_VENT_DIR = 8
PIN_VENT_EN = 9

# === ArduCam Mega 5MP SPI пины ===
PIN_CAM_CS = 17
PIN_CAM_MOSI = 19
PIN_CAM_MISO = 16
PIN_CAM_SCK = 18

# === Пороги автоматизации ===
SOIL_MOISTURE_LOW = 30
SOIL_MOISTURE_HIGH = 60
TEMP_HIGH = 28
TEMP_LOW = 22

# === Интервалы ===
SENSOR_READ_INTERVAL = 30
CAMERA_CAPTURE_INTERVAL = 3600  # 1 час в секундах
WEB_SERVER_PORT = 80

# === Файлы камеры ===
CAMERA_PHOTO_FILE = "photo.jpg"
CAMERA_PHOTO_DIR = "/photos"

# ============================================================
# КЛАСС: LCD ДИСПЛЕЙ I2C
# ============================================================
class LCD_I2C:
    def __init__(self, addr=LCD_I2C_ADDR, cols=16, rows=2):
        self.i2c = I2C(0, sda=Pin(PIN_LCD_SDA), scl=Pin(PIN_LCD_SCL), freq=100000)
        self.addr = addr
        self.cols = cols
        self.rows = rows
        self._backlight = 0x08
        self._init_lcd()
    
    def _init_lcd(self):
        time.sleep_ms(50)
        self._write_cmd(0x03)
        time.sleep_ms(5)
        self._write_cmd(0x03)
        time.sleep_ms(5)
        self._write_cmd(0x03)
        time.sleep_ms(5)
        self._write_cmd(0x02)
        
        self._write_cmd(0x28)
        self._write_cmd(0x0C)
        self._write_cmd(0x06)
        self._write_cmd(0x01)
        time.sleep_ms(5)
    
    def _write_byte(self, data, mode):
        byte = data | self._backlight | mode
        self.i2c.writeto(self.addr, bytes([byte]))
        self.i2c.writeto(self.addr, bytes([byte | 0x04]))
        self.i2c.writeto(self.addr, bytes([byte & ~0x04]))
        time.sleep_us(100)
    
    def _write_cmd(self, cmd):
        self._write_byte(cmd & 0xF0, 0)
        self._write_byte((cmd << 4) & 0xF0, 0)
    
    def _write_data(self, data):
        self._write_byte(data & 0xF0, 1)
        self._write_byte((data << 4) & 0xF0, 1)
    
    def clear(self):
        self._write_cmd(0x01)
        time.sleep_ms(2)
    
    def set_cursor(self, col, row):
        addr = col + (0x40 if row > 0 else 0)
        self._write_cmd(0x80 | addr)
    
    def print(self, text):
        for char in str(text):
            self._write_data(ord(char))
    
    def display_data(self, temp, humidity, soil, light, co2):
        self.clear()
        self.set_cursor(0, 0)
        line1 = f"T:{temp:.1f}C H:{humidity:.0f}%"
        self.print(line1.ljust(16)[:16])
        
        self.set_cursor(0, 1)
        line2 = f"Soil:{soil:.0f}% L:{light:.0f}%"
        self.print(line2.ljust(16)[:16])
    
    def display_message(self, line1, line2=""):
        self.clear()
        self.set_cursor(0, 0)
        self.print(str(line1).ljust(16)[:16])
        if line2 and self.rows > 1:
            self.set_cursor(0, 1)
            self.print(str(line2).ljust(16)[:16])

# ============================================================
# КЛАСС: ДАТЧИКИ
# ============================================================
class SensorsManager:
    def __init__(self):
        self.dht_sensor = dht.DHT22(Pin(PIN_DHT))
        self.soil_adc = ADC(Pin(PIN_SOIL))
        self.light_adc = ADC(Pin(PIN_LIGHT))
        self.co2_adc = ADC(Pin(PIN_CO2))
        
        self.soil_min = 0
        self.soil_max = 65535
        
        self.last_data = {
            'temperature': 0.0,
            'humidity': 0.0,
            'soil_moisture': 0.0,
            'light': 0.0,
            'co2': 400,
            'timestamp': 0
        }
    
    def read_dht(self):
        try:
            self.dht_sensor.measure()
            temp = self.dht_sensor.temperature()
            hum = self.dht_sensor.humidity()
            return temp, hum
        except Exception as e:
            print(f"[DHT Error] {e}")
            return None, None
    
    def read_soil_moisture(self):
        raw = self.soil_adc.read_u16()
        percent = (raw - self.soil_min) / (self.soil_max - self.soil_min) * 100
        return max(0, min(100, round(percent, 1)))
    
    def read_light(self):
        raw = self.light_adc.read_u16()
        percent = (raw / 65535) * 100
        return round(percent, 1)
    
    def read_co2(self):
        raw = self.co2_adc.read_u16()
        voltage = raw * 3.3 / 65535
        ppm = int(400 + (voltage / 3.3) * 1600)
        return max(400, min(2000, ppm))
    
    def read_all(self):
        temp, hum = self.read_dht()
        soil = self.read_soil_moisture()
        light = self.read_light()
        co2 = self.read_co2()
        
        if temp is not None:
            self.last_data['temperature'] = temp
            self.last_data['humidity'] = hum
        
        self.last_data['soil_moisture'] = soil
        self.last_data['light'] = light
        self.last_data['co2'] = co2
        self.last_data['timestamp'] = time.time()
        
        return self.last_data
    
    def get_status(self):
        return self.last_data

# ============================================================
# КЛАСС: НАСОС
# ============================================================
class PumpController:
    def __init__(self):
        self.relay = Pin(PIN_PUMP, Pin.OUT)
        self.relay.value(0)
        self.is_active = False
        self.auto_mode = True
        self.last_activation = 0
    
    def on(self):
        self.relay.value(1)
        self.is_active = True
        self.last_activation = time.time()
        print("[Pump] ON")
    
    def off(self):
        self.relay.value(0)
        self.is_active = False
        print("[Pump] OFF")
    
    def toggle(self):
        if self.is_active:
            self.off()
        else:
            self.on()
    
    def pump_for_duration(self, duration_sec):
        self.on()
        time.sleep(duration_sec)
        self.off()
        return True
    
    def get_status(self):
        return {
            'is_active': self.is_active,
            'auto_mode': self.auto_mode,
            'last_activation': self.last_activation
        }

# ============================================================
# КЛАСС: ВЕНТИЛЯЦИЯ
# ============================================================
class VentilationController:
    def __init__(self, steps_per_rev=200, rpm=60):
        self.step_pin = Pin(PIN_VENT_STEP, Pin.OUT)
        self.dir_pin = Pin(PIN_VENT_DIR, Pin.OUT)
        self.en_pin = Pin(PIN_VENT_EN, Pin.OUT)
        
        self.en_pin.value(0)
        
        self.steps_per_rev = steps_per_rev
        self.step_delay = 60 / (rpm * steps_per_rev) / 2
        
        self.position = 0
        self.target_position = 0
        self.is_moving = False
    
    def _step(self, direction):
        self.dir_pin.value(direction)
        self.step_pin.value(1)
        time.sleep(self.step_delay)
        self.step_pin.value(0)
        time.sleep(self.step_delay)
    
    def move_steps(self, steps, direction):
        self.is_moving = True
        for _ in range(abs(steps)):
            self._step(direction)
        self.is_moving = False
    
    def set_position(self, target_percent):
        target = min(100, max(0, target_percent))
        diff = target - self.position
        steps_needed = int(diff * self.steps_per_rev * 2 / 100)
        
        if steps_needed > 0:
            self.move_steps(steps_needed, 1)
        elif steps_needed < 0:
            self.move_steps(abs(steps_needed), 0)
        
        self.position = target
        self.target_position = target
        print(f"[Ventilation] Position: {self.position}%")
    
    def open(self, percent=100):
        self.set_position(percent)
    
    def close(self):
        self.set_position(0)
    
    def get_status(self):
        return {
            'position': self.position,
            'target': self.target_position,
            'is_moving': self.is_moving
        }

# ============================================================
# КЛАСС: ARDUCAM MEGA 5MP SPI
# ============================================================
class ArduCamController:
    """Контроллер для ArduCam Mega 5MP SPI"""
    
    # Регистры ArduCam
    REG_TEST = 0x00
    REG_FRAME_CONTROL = 0x01
    REG_FIFO_SIZE = 0x02
    REG_FIFO = 0x03
    REG_CAPTURE = 0x04
    
    # Команды
    CMD_CAPTURE = 0x01
    CMD_READ_FIFO = 0x3D
    
    def __init__(self):
        self.cs_pin = Pin(PIN_CAM_CS, Pin.OUT)
        self.cs_pin.value(1)
        
        # Инициализация SPI
        self.spi = SPI(1,
                      baudrate=8000000,
                      polarity=0,
                      phase=0,
                      bits=8,
                      firstbit=SPI.MSB,
                      sck=Pin(PIN_CAM_SCK),
                      mosi=Pin(PIN_CAM_MOSI),
                      miso=Pin(PIN_CAM_MISO))
        
        self.last_capture_time = 0
        self.photo_count = 0
        self.is_initialized = False
        self.last_error = None
        
        # Создаем директорию для фото
        try:
            os.mkdir(CAMERA_PHOTO_DIR)
        except:
            pass
        
        print("[Camera] Initializing ArduCam Mega 5MP...")
        
        if self._init_camera():
            self.is_initialized = True
            print("[Camera] Initialized successfully!")
        else:
            print("[Camera] Initialization failed!")
    
    def _init_camera(self):
        """Инициализация камеры"""
        try:
            # Проверка связи через SPI
            self._write_reg(self.REG_TEST, 0x55)
            test_val = self._read_reg(self.REG_TEST)
            
            if test_val != 0x55:
                print(f"[Camera] SPI test failed: {hex(test_val)}")
                return False
            
            time.sleep_ms(100)
            return True
            
        except Exception as e:
            print(f"[Camera] Init error: {e}")
            self.last_error = str(e)
            return False
    
    def _write_reg(self, reg, value):
        """Запись в регистр через SPI"""
        self.cs_pin.value(0)
        time.sleep_us(10)
        self.spi.write(bytes([reg | 0x80, value]))
        time.sleep_us(10)
        self.cs_pin.value(1)
    
    def _read_reg(self, reg):
        """Чтение регистра через SPI"""
        self.cs_pin.value(0)
        time.sleep_us(10)
        self.spi.write(bytes([reg & 0x7F]))
        result = self.spi.read(1)
        time.sleep_us(10)
        self.cs_pin.value(1)
        return result[0] if result else 0
    
    def capture_photo(self):
        """Захват фото с камеры"""
        if not self.is_initialized:
            print("[Camera] Not initialized!")
            return False, "Camera not initialized"
        
        try:
            print("[Camera] Starting capture...")
            
            # Очистка FIFO
            self._write_reg(self.REG_FRAME_CONTROL, 0x01)
            time.sleep_ms(10)
            
            # Запуск захвата
            self._write_reg(self.REG_CAPTURE, self.CMD_CAPTURE)
            
            # Ожидание завершения (таймаут 5 сек)
            timeout = 5000
            start = time.ticks_ms()
            
            while time.ticks_diff(time.ticks_ms(), start) < timeout:
                status = self._read_reg(self.REG_FRAME_CONTROL)
                if status & 0x08:
                    break
                time.sleep_ms(100)
            else:
                print("[Camera] Capture timeout!")
                return False, "Capture timeout"
            
            # Чтение размера изображения
            size_bytes = self._read_fifo_size()
            
            if size_bytes == 0:
                print("[Camera] Zero size image")
                return False, "Zero size image"
            
            print(f"[Camera] Image size: {size_bytes} bytes")
            
            # Чтение данных изображения
            image_data = self._read_fifo(size_bytes)
            
            if not image_data:
                return False, "Failed to read FIFO"
            
            # Формирование имени файла
            timestamp = time.time()
            filename = f"{CAMERA_PHOTO_DIR}/photo_{int(timestamp)}.jpg"
            
            # Сохранение фото
            with open(filename, 'wb') as f:
                f.write(image_data)
            
            # Обновляем последнее фото
            self._update_latest_photo(filename)
            
            self.last_capture_time = time.time()
            self.photo_count += 1
            
            print(f"[Camera] Photo saved: {filename}")
            
            gc.collect()
            
            return True, filename
            
        except Exception as e:
            print(f"[Camera] Capture error: {e}")
            self.last_error = str(e)
            gc.collect()
            return False, str(e)
    
    def _read_fifo_size(self):
        """Чтение размера данных в FIFO"""
        self.cs_pin.value(0)
        time.sleep_us(10)
        
        self.spi.write(bytes([self.REG_FIFO_SIZE | 0x80]))
        size_bytes = self.spi.read(4)
        
        time.sleep_us(10)
        self.cs_pin.value(1)
        
        if len(size_bytes) == 4:
            size = size_bytes[0] | (size_bytes[1] << 8) | (size_bytes[2] << 16) | (size_bytes[3] << 24)
            return size
        return 0
    
    def _read_fifo(self, size):
        """Чтение данных из FIFO"""
        try:
            max_size = min(size, 1024 * 512)  # Максимум 512KB
            
            data = bytearray(max_size)
            
            self.cs_pin.value(0)
            time.sleep_us(10)
            
            self.spi.write(bytes([self.CMD_READ_FIFO]))
            
            chunk_size = 512
            for i in range(0, max_size, chunk_size):
                chunk = min(chunk_size, max_size - i)
                self.spi.readinto(memoryview(data)[i:i+chunk])
            
            time.sleep_us(10)
            self.cs_pin.value(1)
            
            return bytes(data)
            
        except Exception as e:
            print(f"[Camera] FIFO read error: {e}")
            return None
    
    def _update_latest_photo(self, filename):
        """Обновление последнего фото"""
        try:
            try:
                os.remove(CAMERA_PHOTO_FILE)
            except:
                pass
            
            with open(filename, 'rb') as src:
                with open(CAMERA_PHOTO_FILE, 'wb') as dst:
                    while True:
                        chunk = src.read(512)
                        if not chunk:
                            break
                        dst.write(chunk)
            
            self._cleanup_old_photos(24)
            
        except Exception as e:
            print(f"[Camera] Update photo error: {e}")
    
    def _cleanup_old_photos(self, keep_count):
        """Удаление старых фото"""
        try:
            files = os.listdir(CAMERA_PHOTO_DIR)
            photos = sorted([f for f in files if f.startswith('photo_') and f.endswith('.jpg')])
            
            while len(photos) > keep_count:
                old_file = f"{CAMERA_PHOTO_DIR}/{photos[0]}"
                os.remove(old_file)
                photos.pop(0)
                print(f"[Camera] Deleted old photo: {old_file}")
                
        except Exception as e:
            print(f"[Camera] Cleanup error: {e}")
    
    def get_latest_photo_path(self):
        """Получить путь к последнему фото"""
        try:
            if CAMERA_PHOTO_FILE in os.listdir():
                return CAMERA_PHOTO_FILE
            
            files = os.listdir(CAMERA_PHOTO_DIR)
            photos = sorted([f for f in files if f.startswith('photo_') and f.endswith('.jpg')])
            
            if photos:
                return f"{CAMERA_PHOTO_DIR}/{photos[-1]}"
            
        except:
            pass
        
        return None
    
    def get_status(self):
        """Получить статус камеры"""
        return {
            'initialized': self.is_initialized,
            'photo_count': self.photo_count,
            'last_capture': self.last_capture_time,
            'last_error': self.last_error,
            'latest_photo': self.get_latest_photo_path()
        }

# ============================================================
# КЛАСС: MQTT КЛИЕНТ
# ============================================================
class MQTTManager:
    def __init__(self, cmd_callback=None):
        self.client = None
        self.connected = False
        self.cmd_callback = cmd_callback
        self._reconnect_attempts = 0
    
    def connect(self):
        try:
            self.client = MQTTClient(
                MQTT_CLIENT_ID,
                MQTT_BROKER,
                port=MQTT_PORT,
                user=MQTT_USER if MQTT_USER else None,
                password=MQTT_PASSWORD if MQTT_PASSWORD else None,
                keepalive=60
            )
            self.client.set_callback(self._on_message)
            self.client.connect()
            self.connected = True
            self._reconnect_attempts = 0
            
            print(f"[MQTT] Connected to {MQTT_BROKER}")
            
            self.client.subscribe(MQTT_TOPIC_PUMP)
            self.client.subscribe(MQTT_TOPIC_VENT)
            
            return True
            
        except Exception as e:
            print(f"[MQTT Error] {e}")
            self.connected = False
            return False
    
    def disconnect(self):
        if self.client:
            try:
                self.client.disconnect()
            except:
                pass
        self.connected = False
    
    def _on_message(self, topic, msg):
        topic_str = topic.decode() if isinstance(topic, bytes) else topic
        msg_str = msg.decode() if isinstance(msg, bytes) else msg
        
        print(f"[MQTT] {topic_str} = {msg_str}")
        
        if self.cmd_callback:
            self.cmd_callback(topic_str, msg_str)
    
    def publish(self, topic, data, retain=False):
        if self.client and self.connected:
            try:
                if isinstance(data, (dict, list)):
                    data = ujson.dumps(data)
                self.client.publish(topic, str(data), retain=retain)
                return True
            except Exception as e:
                print(f"[MQTT Publish Error] {e}")
                self.connected = False
        return False
    
    def publish_sensor_data(self, sensor_data):
        if not self.connected:
            return False
        
        try:
            self.publish(MQTT_TOPIC_TEMP, sensor_data['temperature'])
            self.publish(MQTT_TOPIC_HUMIDITY, sensor_data['humidity'])
            self.publish(MQTT_TOPIC_CO2, sensor_data['co2'])
            self.publish(MQTT_TOPIC_SOIL, sensor_data['soil_moisture'])
            self.publish(MQTT_TOPIC_LIGHT, sensor_data['light'])
            return True
        except Exception as e:
            print(f"[MQTT Error] {e}")
            return False
    
    def publish_camera_status(self, camera_status):
        """Публикация статуса камеры"""
        if self.connected:
            self.publish(MQTT_TOPIC_CAMERA, camera_status)
    
    def check_msg(self):
        if self.client and self.connected:
            try:
                self.client.check_msg()
            except Exception as e:
                print(f"[MQTT Check Error] {e}")
                self.connected = False
    
    def reconnect(self):
        self._reconnect_attempts += 1
        print(f"[MQTT] Reconnecting (attempt {self._reconnect_attempts})...")
        self.disconnect()
        time.sleep(2)
        return self.connect()

# ============================================================
# КЛАСС: ВЕБ-СЕРВЕР (С ИНТЕГРИРОВАННОЙ СТРАНИЦЕЙ)
# ============================================================
class WebServer:
    def __init__(self, sensors, pump, vent, camera, mqtt):
        self.sensors = sensors
        self.pump = pump
        self.vent = vent
        self.camera = camera
        self.mqtt = mqtt
        self.start_time = time.time()
    
    async def start(self):
        print(f"[Web] Server starting on port {WEB_SERVER_PORT}...")
        server = await asyncio.start_server(
            self.handle_client, 
            "0.0.0.0", 
            WEB_SERVER_PORT
        )
        async with server:
            await server.serve_forever()
    
    async def handle_client(self, reader, writer):
        try:
            request = await reader.read(4096)
            req_str = request.decode('utf-8', errors='ignore')
            
            lines = req_str.split('\r\n')
            if not lines:
                await writer.aclose()
                return
            
            first_line = lines[0].split(' ')
            if len(first_line) < 2:
                await writer.aclose()
                return
            
            path = first_line[1]
            
            # Маршрутизация
            if path == '/' or path == '/index.html':
                response = self._page_index()
            elif path == '/api/data':
                response = self._api_data()
            elif path == '/api/status':
                response = self._api_status()
            elif path == '/pump/on':
                response = self._cmd_pump_on()
            elif path == '/pump/off':
                response = self._cmd_pump_off()
            elif path == '/pump/toggle':
                response = self._cmd_pump_toggle()
            elif path.startswith('/vent/'):
                response = self._cmd_vent(path)
            elif path == '/camera/capture':
                response = await self._cmd_camera_capture()
            elif path == '/camera/latest':
                response = await self._serve_latest_photo()
            elif path.startswith('/photos/'):
                response = await self._serve_photo(path)
            else:
                response = self._page_404()
            
            if isinstance(response, str):
                await writer.awrite(response.encode('utf-8'))
            else:
                await writer.awrite(response)
            
        except Exception as e:
            print(f"[Web Error] {e}")
        
        finally:
            await writer.aclose()
    
    def _redirect(self, location):
        return f"HTTP/1.1 302 Found\r\nLocation: {location}\r\n\r\n"
    
    def _ok(self, content, content_type="text/html"):
        return f"HTTP/1.1 200 OK\r\nContent-Type: {content_type}\r\n\r\n{content}"
    
    def _json(self, data):
        body = ujson.dumps(data)
        return f"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\n\r\n{body}"
    
    def _page_404(self):
        html = "<html><body><h1>404 Not Found</h1></body></html>"
        return f"HTTP/1.1 404 Not Found\r\nContent-Type: text/html\r\n\r\n{html}"
    
    # ============================================================
    # ГЛАВНАЯ СТРАНИЦА (ИНТЕГРИРОВАННАЯ)
    # ============================================================
    def _page_index(self):
        data = self.sensors.get_status()
        camera_status = self.camera.get_status()
        pump_status = "ON" if self.pump.is_active else "OFF"
        mqtt_status = "Connected" if self.mqtt.connected else "Disconnected"
        
        # Время обновления
        uptime = int(time.time() - self.start_time)
        last_update = int(time.time() - data['timestamp'])
        
        # Фото
        photo_url = "/camera/latest" if camera_status['latest_photo'] else ""
        has_photo = camera_status['photo_count'] > 0
        
        # Форматирование времени последнего фото
        if camera_status['last_capture']:
            last_photo_time = time.localtime(camera_status['last_capture'])
            last_photo_str = f"{last_photo_time[3]:02d}:{last_photo_time[4]:02d}:{last_photo_time[5]:02d}"
        else:
            last_photo_str = "Never"
        
        html = f"""<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <meta http-equiv="refresh" content="60">
    <title>Smart Greenhouse</title>
    <style>
        * {{ box-sizing: border-box; margin: 0; padding: 0; }}
        body {{ 
            font-family: 'Segoe UI', Arial, sans-serif;
            background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%);
            color: #eee;
            min-height: 100vh;
            padding: 20px;
        }}
        .header {{ 
            text-align: center;
            padding: 20px;
            margin-bottom: 30px;
        }}
        .header h1 {{ 
            color: #4ecca3;
            font-size: 2.5em;
            text-shadow: 0 0 10px rgba(78, 204, 163, 0.5);
            letter-spacing: 2px;
        }}
        .header p {{
            color: #666;
            margin-top: 5px;
            font-size: 0.9em;
        }}
        
        .grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
            gap: 15px;
            max-width: 1000px;
            margin: 0 auto 25px;
        }}
        
        .card {{
            background: rgba(255,255,255,0.05);
            border: 1px solid rgba(255,255,255,0.1);
            border-radius: 12px;
            padding: 20px 15px;
            text-align: center;
            transition: all 0.3s;
        }}
        .card:hover {{
            transform: translateY(-3px);
            box-shadow: 0 8px 25px rgba(0,0,0,0.3);
            border-color: rgba(78, 204, 163, 0.3);
        }}
        .card h3 {{
            color: #888;
            font-size: 0.8em;
            text-transform: uppercase;
            letter-spacing: 1px;
            margin-bottom: 10px;
        }}
        .card .value {{
            font-size: 2.2em;
            font-weight: bold;
            color: #4ecca3;
        }}
        .card .unit {{
            color: #666;
            font-size: 0.85em;
            margin-left: 2px;
        }}
        
        .temp .value {{ color: #ff6b6b; }}
        .humidity .value {{ color: #4ecdc4; }}
        .soil .value {{ color: #45b7d1; }}
        .light .value {{ color: #f9ca24; }}
        .co2 .value {{ color: #a29bfe; }}
        .vent .value {{ color: #fd79a8; }}
        
        .card-icon {{
            font-size: 1.5em;
            margin-bottom: 5px;
        }}
        
        /* СЕКЦИЯ КАМЕРЫ */
        .camera-section {{
            max-width: 1000px;
            margin: 0 auto 25px;
            background: rgba(255,255,255,0.05);
            border: 1px solid rgba(255,255,255,0.1);
            border-radius: 12px;
            padding: 20px;
        }}
        .camera-section h2 {{
            color: #4ecca3;
            margin-bottom: 15px;
            font-size: 1.3em;
        }}
        .camera-container {{
            position: relative;
            background: #0d0d1a;
            border-radius: 8px;
            overflow: hidden;
            min-height: 200px;
            display: flex;
            align-items: center;
            justify-content: center;
        }}
        .camera-container img {{
            max-width: 100%;
            max-height: 500px;
            display: block;
        }}
        .camera-placeholder {{
            color: #555;
            text-align: center;
            padding: 60px 20px;
        }}
        .camera-placeholder .icon {{
            font-size: 4em;
            margin-bottom: 15px;
        }}
        .camera-info {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-top: 15px;
            padding-top: 15px;
            border-top: 1px solid rgba(255,255,255,0.1);
            font-size: 0.85em;
            color: #888;
            flex-wrap: wrap;
            gap: 10px;
        }}
        .camera-info .btn-capture {{
            background: #4ecca3;
            color: #1a1a2e;
            padding: 10px 20px;
            border-radius: 6px;
            text-decoration: none;
            font-weight: bold;
            transition: all 0.3s;
        }}
        .camera-info .btn-capture:hover {{
            opacity: 0.9;
            transform: scale(1.05);
        }}
        
        /* УПРАВЛЕНИЕ */
        .controls {{
            max-width: 1000px;
            margin: 0 auto;
            background: rgba(255,255,255,0.05);
            border: 1px solid rgba(255,255,255,0.1);
            border-radius: 12px;
            padding: 20px;
        }}
        .controls h2 {{
            color: #4ecca3;
            margin-bottom: 20px;
            font-size: 1.3em;
        }}
        
        .control-group {{
            margin-bottom: 20px;
            padding-bottom: 15px;
            border-bottom: 1px solid rgba(255,255,255,0.05);
        }}
        .control-group:last-child {{
            border-bottom: none;
            margin-bottom: 0;
            padding-bottom: 0;
        }}
        .control-group h3 {{
            color: #888;
            font-size: 0.9em;
            margin-bottom: 12px;
            text-transform: uppercase;
            letter-spacing: 1px;
        }}
        
        .btn-group {{
            display: flex;
            flex-wrap: wrap;
            gap: 10px;
        }}
        
        .btn {{
            display: inline-block;
            padding: 12px 24px;
            border: none;
            border-radius: 6px;
            font-size: 0.95em;
            font-weight: 600;
            cursor: pointer;
            text-decoration: none;
            transition: all 0.3s;
        }}
        .btn-on {{ background: #4ecca3; color: #1a1a2e; }}
        .btn-off {{ background: #ff6b6b; color: #fff; }}
        .btn-neutral {{ background: #3498db; color: #fff; }}
        .btn:hover {{ opacity: 0.85; transform: translateY(-2px); }}
        
        /* СТАТУС */
        .status-bar {{
            max-width: 1000px;
            margin: 25px auto 0;
            padding: 15px 20px;
            background: rgba(255,255,255,0.03);
            border-radius: 8px;
            font-size: 0.85em;
            color: #666;
            display: flex;
            justify-content: center;
            flex-wrap: wrap;
            gap: 15px;
        }}
        .status-bar span {{
            display: flex;
            align-items: center;
            gap: 5px;
        }}
        .status-ok {{ color: #4ecca3; }}
        .status-warn {{ color: #f9ca24; }}
        .status-error {{ color: #ff6b6b; }}
        
        @media (max-width: 600px) {{
            .header h1 {{ font-size: 1.8em; }}
            .card .value {{ font-size: 1.8em; }}
            .btn {{ padding: 10px 18px; font-size: 0.9em; }}
        }}
    </style>
</head>
<body>
    <div class="header">
        <h1>🌱 Smart Greenhouse</h1>
        <p>Automated plant monitoring system</p>
    </div>
    
    <!-- ДАТЧИКИ -->
    <div class="grid">
        <div class="card temp">
            <div class="card-icon">🌡️</div>
            <h3>Temperature</h3>
            <div class="value">{data['temperature']:.1f}<span class="unit">°C</span></div>
        </div>
        <div class="card humidity">
            <div class="card-icon">💧</div>
            <h3>Humidity</h3>
            <div class="value">{data['humidity']:.0f}<span class="unit">%</span></div>
        </div>
        <div class="card soil">
            <div class="card-icon">🌱</div>
            <h3>Soil Moisture</h3>
            <div class="value">{data['soil_moisture']:.0f}<span class="unit">%</span></div>
        </div>
        <div class="card light">
            <div class="card-icon">☀️</div>
            <h3>Light Level</h3>
            <div class="value">{data['light']:.0f}<span class="unit">%</span></div>
        </div>
        <div class="card co2">
            <div class="card-icon">💨</div>
            <h3>CO2</h3>
            <div class="value">{data['co2']}<span class="unit">ppm</span></div>
        </div>
        <div class="card vent">
            <div class="card-icon">🌀</div>
            <h3>Ventilation</h3>
            <div class="value">{self.vent.position}<span class="unit">% open</span></div>
        </div>
    </div>
    
    <!-- КАМЕРА -->
    <div class="camera-section">
        <h2>📷 Camera Feed</h2>
        <div class="camera-container">
            {'<img src="' + photo_url + '" alt="Greenhouse photo">' if has_photo else '<div class="camera-placeholder"><div class="icon">📷</div><p>No photos yet</p><p style="font-size:0.8em;margin-top:10px;">Photos are taken every hour</p></div>'}
        </div>
        <div class="camera-info">
            <div>
                📸 Photos: <strong>{camera_status['photo_count']}</strong> | 
                Last: <strong>{last_photo_str}</strong>
            </div>
            <a href="/camera/capture" class="btn-capture">📸 Capture Now</a>
        </div>
    </div>
    
    <!-- УПРАВЛЕНИЕ -->
    <div class="controls">
        <h2>🎛️ Controls</h2>
        
        <div class="control-group">
            <h3>💧 Water Pump</h3>
            <div class="btn-group">
                <a href="/pump/on" class="btn btn-on">Turn ON</a>
                <a href="/pump/off" class="btn btn-off">Turn OFF</a>
                <a href="/pump/toggle" class="btn btn-neutral">Toggle</a>
            </div>
        </div>
        
        <div class="control-group">
            <h3>🌀 Ventilation</h3>
            <div class="btn-group">
                <a href="/vent/open" class="btn btn-on">Open 100%</a>
                <a href="/vent/50" class="btn btn-neutral">Set 50%</a>
                <a href="/vent/25" class="btn btn-neutral">Set 25%</a>
                <a href="/vent/close" class="btn btn-off">Close</a>
            </div>
        </div>
    </div>
    
    <!-- СТАТУС БАР -->
    <div class="status-bar">
        <span>Pump: <strong class="{'status-ok' if self.pump.is_active else ''}">{pump_status}</strong></span>
        <span>MQTT: <strong class="{'status-ok' if self.mqtt.connected else 'status-error'}">{mqtt_status}</strong></span>
        <span>Camera: <strong class="{'status-ok' if camera_status['initialized'] else 'status-error'}">{'OK' if camera_status['initialized'] else 'Error'}</strong></span>
        <span>Updated: <strong>{last_update}s ago</strong></span>
        <span>Uptime: <strong>{uptime // 3600}h {(uptime % 3600) // 60}m</strong></span>
    </div>
</body>
</html>"""
        
        return self._ok(html)
    
    # ============================================================
    # API ENDPOINTS
    # ============================================================
    def _api_data(self):
        data = self.sensors.get_status()
        data['vent_position'] = self.vent.position
        data['pump_active'] = self.pump.is_active
        return self._json(data)
    
    def _api_status(self):
        status = {
            'sensors': self.sensors.get_status(),
            'pump': self.pump.get_status(),
            'vent': self.vent.get_status(),
            'camera': self.camera.get_status(),
            'mqtt': {
                'connected': self.mqtt.connected
            },
            'uptime': int(time.time() - self.start_time)
        }
        return self._json(status)
    
    # ============================================================
    # КОМАНДЫ УПРАВЛЕНИЯ
    # ============================================================
    def _cmd_pump_on(self):
        self.pump.on()
        return self._redirect('/')
    
    def _cmd_pump_off(self):
        self.pump.off()
        return self._redirect('/')
    
    def _cmd_pump_toggle(self):
        self.pump.toggle()
        return self._redirect('/')
    
    def _cmd_vent(self, path):
        parts = path.split('/')
        if len(parts) >= 3:
            cmd = parts[2]
            if cmd == 'open':
                self.vent.open(100)
            elif cmd == 'close':
                self.vent.close()
            else:
                try:
                    percent = int(cmd)
                    self.vent.set_position(percent)
                except:
                    pass
        return self._redirect('/')
    
    async def _cmd_camera_capture(self):
        """Ручной захват фото"""
        success, result = self.camera.capture_photo()
        if success:
            print(f"[Web] Photo captured: {result}")
        else:
            print(f"[Web] Photo capture failed: {result}")
        return self._redirect('/')
    
    # ============================================================
    # ОБСЛУЖИВАНИЕ ФОТО
    # ============================================================
    async def _serve_latest_photo(self):
        """Отдача последнего фото"""
        photo_path = self.camera.get_latest_photo_path()
        
        if not photo_path:
            # Если фото нет - возвращаем заглушку
            html = '<html><body style="background:#1a1a2e;color:#888;text-align:center;padding:50px;"><h2>📷 No photo available</h2><p>Capture in progress or camera not initialized</p></body></html>'
            return f"HTTP/1.1 404 Not Found\r\nContent-Type: text/html\r\n\r\n{html}"
        
        try:
            with open(photo_path, 'rb') as f:
                # Читаем заголовок
                header = b"HTTP/1.1 200 OK\r\n"
                header += b"Content-Type: image/jpeg\r\n"
                header += b"Cache-Control: no-cache\r\n"
                header += b"\r\n"
                
                # Читаем и отправляем файл частями
                result = bytearray(header)
                while True:
                    chunk = f.read(1024)
                    if not chunk:
                        break
                    result.extend(chunk)
                
                return bytes(result)
                
        except Exception as e:
            print(f"[Web] Photo read error: {e}")
            html = f'<html><body style="background:#1a1a2e;color:#ff6b6b;text-align:center;padding:50px;"><h2>Error loading photo</h2><p>{e}</p></body></html>'
            return f"HTTP/1.1 500 Internal Error\r\nContent-Type: text/html\r\n\r\n{html}"
    
    async def _serve_photo(self, path):
        """Отдача конкретного фото по имени"""
        try:
            filename = path.split('/')[-1]
            photo_path = f"{CAMERA_PHOTO_DIR}/{filename}"
            
            with open(photo_path, 'rb') as f:
                header = b"HTTP/1.1 200 OK\r\n"
                header += b"Content-Type: image/jpeg\r\n"
                header += b"\r\n"
                
                result = bytearray(header)
                while True:
                    chunk = f.read(1024)
                    if not chunk:
                        break
                    result.extend(chunk)
                
                return bytes(result)
                
        except Exception as e:
            print(f"[Web] Photo serve error: {e}")
            return self._page_404()

# ============================================================
# ГЛАВНЫЙ КОНТРОЛЛЕР
# ============================================================
class GreenhouseController:
    def __init__(self):
        self.lcd = LCD_I2C()
        self.sensors = SensorsManager()
        self.pump = PumpController()
        self.vent = VentilationController()
        self.camera = ArduCamController()
        self.mqtt = MQTTManager(cmd_callback=self.handle_mqtt_command)
        self.web = WebServer(self.sensors, self.pump, self.vent, self.camera, self.mqtt)
        
        self.last_sensor_read = 0
        self.last_camera_capture = 0
        self.running = False
    
    def handle_mqtt_command(self, topic, message):
        """Обработка команд из MQTT"""
