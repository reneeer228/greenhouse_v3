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

# ============================================================
# КОНФИГУРАЦИЯ
# ============================================================

# === Настройки WiFi ===
WIFI_SSID = "ВАШ_WIFI_SSID"          # <-- Измените на свои
WIFI_PASSWORD = "ВАШ_WIFI_PASSWORD"  # <-- Измените на свои

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


# === Распиновка GPIO ===
# Датчики
PIN_DHT = 0            # GP0 - DHT22
PIN_SOIL = 26          # GP26 (ADC0) - Влажность почвы
PIN_LIGHT = 27         # GP27 (ADC1) - Датчик света
PIN_CO2 = 28           # GP28 (ADC2) - Датчик CO2

# LCD дисплей I2C
PIN_LCD_SDA = 4        # GP4 - I2C SDA
PIN_LCD_SCL = 5        # GP5 - I2C SCL
LCD_I2C_ADDR = 0x27    # Адрес I2C (0x27 или 0x3F)

# Исполнительные устройства
PIN_PUMP = 6           # GP6 - Реле насоса
PIN_VENT_STEP = 7      # GP7 - Шаговый мотор STEP
PIN_VENT_DIR = 8       # GP8 - Шаговый мотор DIR
PIN_VENT_EN = 9        # GP9 - Шаговый мотор ENABLE



# === Пороги автоматизации ===
SOIL_MOISTURE_LOW = 30     # Влажность почвы < 30% -> полив ВКЛ
SOIL_MOISTURE_HIGH = 60    # Влажность почвы > 60% -> полив ВЫКЛ
TEMP_HIGH = 28             # Температура > 28C -> вентиляция ОТКРЫТЬ
TEMP_LOW = 22              # Температура < 22C -> вентиляция ЗАКРЫТЬ
# === Интервалы ===
SENSOR_READ_INTERVAL = 30   # секунд между чтением датчиков
WEB_SERVER_PORT = 80

# ============================================================
# КЛАСС: LCD ДИСПЛЕЙ I2C
# ============================================================
class LCD_I2C:
    """Драйвер LCD 1602/2004 через I2C (PCF8574)"""
    
    def __init__(self, addr=LCD_I2C_ADDR, cols=16, rows=2):
        self.i2c = I2C(0, sda=Pin(PIN_LCD_SDA), scl=Pin(PIN_LCD_SCL), freq=100000)
        self.addr = addr
        self.cols = cols
        self.rows = rows
        self._backlight = 0x08
        self._init_lcd()
    
    def _init_lcd(self):
        """Инициализация LCD в 4-bit режиме"""
        time.sleep_ms(50)
        self._write_cmd(0x03)
        time.sleep_ms(5)
        self._write_cmd(0x03)
        time.sleep_ms(5)
        self._write_cmd(0x03)
        time.sleep_ms(5)
        self._write_cmd(0x02)  # Переключение в 4-bit режим
        
        self._write_cmd(0x28)  # Function set: 4-bit, 2 lines
        self._write_cmd(0x0C)  # Display on, cursor off
        self._write_cmd(0x06)  # Entry mode: increment
        self._write_cmd(0x01)  # Clear display
        time.sleep_ms(5)
    
    def _write_byte(self, data, mode):
        """Запись байта в I2C с импульсом Enable"""
        byte = data | self._backlight | mode
        self.i2c.writeto(self.addr, bytes([byte]))
        self.i2c.writeto(self.addr, bytes([byte | 0x04]))  # Enable high
        self.i2c.writeto(self.addr, bytes([byte & ~0x04]))  # Enable low
        time.sleep_us(100)
    
    def _write_cmd(self, cmd):
        """Запись команды (4-bit)"""
        self._write_byte(cmd & 0xF0, 0)
        self._write_byte((cmd << 4) & 0xF0, 0)
    
    def _write_data(self, data):
        """Запись данных (4-bit)"""
        self._write_byte(data & 0xF0, 1)
        self._write_byte((data << 4) & 0xF0, 1)
    
    def clear(self):
        """Очистка дисплея"""
        self._write_cmd(0x01)
        time.sleep_ms(2)
    
    def set_cursor(self, col, row):
        """Установка позиции курсора"""
        addr = col + (0x40 if row > 0 else 0)
        self._write_cmd(0x80 | addr)
    
    def print(self, text):
        """Вывод текста"""
        for char in str(text):
            self._write_data(ord(char))
    
    def display_data(self, temp, humidity, soil, light, co2):
        """Отображение данных датчиков на LCD 1602"""
        self.clear()
        # Строка 1: Температура и влажность
        self.set_cursor(0, 0)
        line1 = f"T:{temp:.1f}C H:{humidity:.0f}%"
        self.print(line1.ljust(16)[:16])
        
        # Строка 2: Почва и свет
        self.set_cursor(0, 1)
        line2 = f"Soil:{soil:.0f}% L:{light:.0f}%"
        self.print(line2.ljust(16)[:16])
    
    def display_message(self, line1, line2=""):
        """Отображение сообщения"""
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
    """Менеджер всех датчиков системы"""
    
    def __init__(self):
        # DHT22 - температура и влажность воздуха
        self.dht_sensor = dht.DHT22(Pin(PIN_DHT))
        
        # Аналоговые датчики через ADC
        self.soil_adc = ADC(Pin(PIN_SOIL))
        self.light_adc = ADC(Pin(PIN_LIGHT))
        self.co2_adc = ADC(Pin(PIN_CO2))
        
        # Калибровочные значения (настройте под ваши датчики)
        self.soil_min = 0      # Сухая почва
        self.soil_max = 65535  # Мокрая почва
        
        # Кэш последних значений
        self.last_data = {
            'temperature': 0.0,
            'humidity': 0.0,
            'soil_moisture': 0.0,
            'light': 0.0,
            'co2': 400,
            'timestamp': 0
        }
    
    def read_dht(self):
        """Чтение DHT22"""
        try:
            self.dht_sensor.measure()
            temp = self.dht_sensor.temperature()
            hum = self.dht_sensor.humidity()
            return temp, hum
        except Exception as e:
            print(f"[DHT Error] {e}")
            return None, None
    
    def read_soil_moisture(self):
        """Чтение влажности почвы (%)"""
        raw = self.soil_adc.read_u16()
        # Для емкостных датчиков: больше значение = больше влажность
        percent = (raw - self.soil_min) / (self.soil_max - self.soil_min) * 100
        return max(0, min(100, round(percent, 1)))
    
    def read_light(self):
        """Чтение уровня освещенности (%)"""
        raw = self.light_adc.read_u16()
        percent = (raw / 65535) * 100
        return round(percent, 1)
    
    def read_co2(self):
        """Чтение уровня CO2 (ppm) - примерная конверсия"""
        raw = self.co2_adc.read_u16()
        voltage = raw * 3.3 / 65535
        # Примерная формула для MQ-135 (требует калибровки!)
        ppm = int(400 + (voltage / 3.3) * 1600)
        return max(400, min(2000, ppm))
    
    def read_all(self):
        """Чтение всех датчиков"""
        temp, hum = self.read_dht()
        soil = self.read_soil_moisture()
        light = self.read_light()
        co2 = self.read_co2()
        
        # Обновляем кэш (DHT может вернуть None при ошибке)
        if temp is not None:
            self.last_data['temperature'] = temp
            self.last_data['humidity'] = hum
        
        self.last_data['soil_moisture'] = soil
        self.last_data['light'] = light
        self.last_data['co2'] = co2
        self.last_data['timestamp'] = time.time()
        
        return self.last_data
    
    def get_status(self):
        """Получение текущего статуса"""
        return self.last_data

# ============================================================
# КЛАСС: НАСОС (РЕЛЕ)
# ============================================================
class PumpController:
    """Контроллер насоса для полива"""
    
    def __init__(self):
        self.relay = Pin(PIN_PUMP, Pin.OUT)
        self.relay.value(0)  # Выключен по умолчанию
        self.is_active = False
        self.auto_mode = True  # Автоматический режим
        self.last_activation = 0
    
    def on(self):
        """Включить насос"""
        self.relay.value(1)
        self.is_active = True
        self.last_activation = time.time()
        print("[Pump] ON")
    
    def off(self):
        """Выключить насос"""
        self.relay.value(0)
        self.is_active = False
        print("[Pump] OFF")
    
    def toggle(self):
        """Переключить состояние"""
        if self.is_active:
            self.off()
        else:
            self.on()
    
    def pump_for_duration(self, duration_sec):
        """Полив на заданное время"""
        self.on()
        time.sleep(duration_sec)
        self.off()
        return True
    
    def get_status(self):
        """Получить статус"""
        return {
            'is_active': self.is_active,
            'auto_mode': self.auto_mode,
            'last_activation': self.last_activation
        }

# ============================================================
# КЛАСС: ВЕНТИЛЯЦИЯ (ШАГОВЫЙ ДВИГАТЕЛЬ)
# ============================================================
class VentilationController:
    """Контроллер вентиляции на шаговом двигателе"""
    
    def __init__(self, steps_per_rev=200, rpm=60):
        # Пины драйвера A4988/DRV8825
        self.step_pin = Pin(PIN_VENT_STEP, Pin.OUT)
        self.dir_pin = Pin(PIN_VENT_DIR, Pin.OUT)
        self.en_pin = Pin(PIN_VENT_EN, Pin.OUT)
        
        # Включаем драйвер (ENABLE = 0 = активен)
        self.en_pin.value(0)
        
        self.steps_per_rev = steps_per_rev
        self.step_delay = 60 / (rpm * steps_per_rev) / 2
        
        # Позиция заслонки (0-100%)
        self.position = 0
        self.target_position = 0
        self.is_moving = False
    
    def _step(self, direction):
        """Выполнить один шаг"""
        self.dir_pin.value(direction)
        self.step_pin.value(1)
        time.sleep(self.step_delay)
        self.step_pin.value(0)
        time.sleep(self.step_delay)
    
    def move_steps(self, steps, direction):
        """Выполнить несколько шагов"""
        self.is_moving = True
        for _ in range(abs(steps)):
            self._step(direction)
        self.is_moving = False
    
    def set_position(self, target_percent):
        """Установить позицию заслонки (0-100%)"""
        target = min(100, max(0, target_percent))
        
        # Вычисляем разницу в шагах (примерно)
        diff = target - self.position
        steps_needed = int(diff * self.steps_per_rev * 2 / 100)
        
        if steps_needed > 0:
            # Открываем
            self.move_steps(steps_needed, 1)
        elif steps_needed < 0:
            # Закрываем
            self.move_steps(abs(steps_needed), 0)
        
        self.position = target
        self.target_position = target
        print(f"[Ventilation] Position: {self.position}%")
    
    def open(self, percent=100):
        """Открыть вентиляцию"""
        self.set_position(percent)
    
    def close(self):
        """Закрыть вентиляцию"""
        self.set_position(0)
    
    def get_status(self):
        """Получить статус"""
        return {
            'position': self.position,
            'target': self.target_position,
            'is_moving': self.is_moving
        }


# ============================================================
# КЛАСС: MQTT КЛИЕНТ
# ============================================================
class MQTTManager:
    """Менеджер MQTT соединения"""
    
    def __init__(self, cmd_callback=None):
        self.client = None
        self.connected = False
        self.cmd_callback = cmd_callback
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
            self.client.set_callback(self._on_message)
            self.client.connect()
            self.connected = True
            self._reconnect_attempts = 0
            
            print(f"[MQTT] Connected to {MQTT_BROKER}")
            
            # Подписка на топики управления
            self.client.subscribe(MQTT_TOPIC_PUMP)
            self.client.subscribe(MQTT_TOPIC_VENT)
        
            
            return True
            
        except Exception as e:
            print(f"[MQTT Error] {e}")
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
    
    def _on_message(self, topic, msg):
        """Обработка входящих сообщений"""
        topic_str = topic.decode() if isinstance(topic, bytes) else topic
        msg_str = msg.decode() if isinstance(msg, bytes) else msg
        
        print(f"[MQTT] {topic_str} = {msg_str}")
        
        if self.cmd_callback:
            self.cmd_callback(topic_str, msg_str)
    
    def publish(self, topic, data, retain=False):
        """Публикация данных"""
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
        """Публикация данных всех датчиков"""
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
    
    def check_msg(self):
        """Проверка входящих сообщений (неблокирующая)"""
        if self.client and self.connected:
            try:
                self.client.check_msg()
            except Exception as e:
                print(f"[MQTT Check Error] {e}")
                self.connected = False
    
    def reconnect(self):
        """Переподключение"""
        self._reconnect_attempts += 1
        print(f"[MQTT] Reconnecting (attempt {self._reconnect_attempts})...")
        self.disconnect()
        time.sleep(2)
        return self.connect()

# ============================================================
# КЛАСС: ВЕБ-СЕРВЕР
# ============================================================
class WebServer:
    """Асинхронный веб-сервер для управления системой"""
    
    def __init__(self, sensors, pump, vent, camera, mqtt):
        self.sensors = sensors
        self.pump = pump
        self.vent = vent
        self.mqtt = mqtt
    
    async def start(self):
        """Запуск сервера"""
        print(f"[Web] Server starting on port {WEB_SERVER_PORT}...")
        server = await asyncio.start_server(
            self.handle_client, 
            "0.0.0.0", 
            WEB_SERVER_PORT
        )
        async with server:
            await server.serve_forever()
    
    async def handle_client(self, reader, writer):
        """Обработка HTTP запросов"""
        try:
            request = await reader.read(1024)
            req_str = request.decode('utf-8', errors='ignore')
            
            # Парсинг пути
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
            else:
                response = self._page_404()
            
            await writer.awrite(response.encode('utf-8'))
            
        except Exception as e:
            print(f"[Web Error] {e}")
        
        finally:
            await writer.aclose()
    
    def _redirect(self, location):
        """HTTP редирект"""
        return f"HTTP/1.1 302 Found\r\nLocation: {location}\r\n\r\n"
    
    def _ok(self, content, content_type="text/html"):
        """HTTP 200 OK"""
        return f"HTTP/1.1 200 OK\r\nContent-Type: {content_type}\r\n\r\n{content}"
    
    def _json(self, data):
        """JSON ответ"""
        body = ujson.dumps(data)
        return f"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\n\r\n{body}"
    
    def _page_404(self):
        """Страница 404"""
        html = "<html><body><h1>404 Not Found</h1></body></html>"
        return f"HTTP/1.1 404 Not Found\r\nContent-Type: text/html\r\n\r\n{html}"
    
    def _page_index(self):
        """Главная страница"""
        data = self.sensors.get_status()
        pump_status = "ON" if self.pump.is_active else "OFF"
        pump_class = "btn-on" if self.pump.is_active else "btn-off"
        
        html = f"""<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
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
        }}
        .grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
            gap: 20px;
            max-width: 900px;
            margin: 0 auto 30px;
        }}
        .card {{
            background: rgba(255,255,255,0.05);
            border: 1px solid rgba(255,255,255,0.1);
            border-radius: 15px;
            padding: 20px;
            text-align: center;
            transition: transform 0.3s, box-shadow 0.3s;
        }}
        .card:hover {{
            transform: translateY(-5px);
            box-shadow: 0 10px 30px rgba(0,0,0,0.3);
        }}
        .card h3 {{
            color: #888;
            font-size: 0.9em;
            margin-bottom: 10px;
        }}
        .card .value {{
            color: #4ecca3;
            font-size: 2.5em;
            font-weight: bold;
        }}
        .card .unit {{
            color: #666;
            font-size: 0.9em;
        }}
        .temp .value {{ color: #ff6b6b; }}
        .humidity .value {{ color: #4ecdc4; }}
        .soil .value {{ color: #45b7d1; }}
        .light .value {{ color: #f9ca24; }}
        .co2 .value {{ color: #a29bfe; }}
        .vent .value {{ color: #fd79a8; }}
        
        .controls {{
            text-align: center;
            max-width: 600px;
            margin: 0 auto;
            padding: 20px;
            background: rgba(255,255,255,0.05);
            border-radius: 15px;
        }}
        .controls h2 {{
            color: #4ecca3;
            margin-bottom: 20px;
        }}
        .btn {{
            display: inline-block;
            padding: 15px 30px;
            margin: 10px;
            border: none;
            border-radius: 8px;
            font-size: 1em;
            font-weight: bold;
            cursor: pointer;
            text-decoration: none;
            transition: all 0.3s;
        }}
        .btn-on {{ background: #4ecca3; color: #1a1a2e; }}
        .btn-off {{ background: #ff6b6b; color: #fff; }}
        .btn-neutral {{ background: #3498db; color: #fff; }}
        .btn:hover {{ opacity: 0.8; transform: scale(1.05); }}
        
        .status {{
            text-align: center;
            margin-top: 20px;
            padding: 10px;
            color: #666;
            font-size: 0.9em;
        }}
    </style>
</head>
<body>
    <div class="header">
        <h1>Smart Greenhouse</h1>
    </div>
    
    <div class="grid">
        <div class="card temp">
            <h3>Temperature</h3>
            <div class="value">{data['temperature']:.1f}</div>
            <div class="unit">°C</div>
        </div>
        <div class="card humidity">
            <h3>Humidity</h3>
            <div class="value">{data['humidity']:.0f}</div>
            <div class="unit">%</div>
        </div>
        <div class="card soil">
            <h3>Soil Moisture</h3>
            <div class="value">{data['soil_moisture']:.0f}</div>
            <div class="unit">%</div>
        </div>
        <div class="card light">
            <h3>Light Level</h3>
            <div class="value">{data['light']:.0f}</div>
            <div class="unit">%</div>
        </div>
        <div class="card co2">
            <h3>CO2 Level</h3>
            <div class="value">{data['co2']}</div>
            <div class="unit">ppm</div>
        </div>
        <div class="card vent">
            <h3>Ventilation</h3>
            <div class="value">{self.vent.position}</div>
            <div class="unit">% open</div>
        </div>
    </div>
    
    <div class="controls">
        <h2>Controls</h2>
        
        <h3 style="margin: 20px 0 10px; color: #888;">Water Pump</h3>
        <a href="/pump/on" class="btn btn-on">Turn ON</a>
        <a href="/pump/off" class="btn btn-off">Turn OFF</a>
        <a href="/pump/toggle" class="btn btn-neutral">Toggle</a>
        
        <h3 style="margin: 20px 0 10px; color: #888;">Ventilation</h3>
        <a href="/vent/open" class="btn btn-on">Open 100%</a>
        <a href="/vent/close" class="btn btn-off">Close</a>
        <a href="/vent/50" class="btn btn-neutral">Set 50%</a>
        
        <h3 style="margin: 20px 0 10px; color: #888;">Camera</h3>
        <a href="/camera/capture" class="btn btn-neutral">Capture Photo</a>
        
        <div class="status">
            Pump: {pump_status} | 
            MQTT: {'Connected' if self.mqtt.connected else 'Disconnected'} |
            Auto-mode: {'ON' if self.pump.auto_mode else 'OFF'}
        </div>
    </div>
</body>
</html>"""
        return self._ok(html)
    
    def _api_data(self):
        """API: данные датчиков"""
        return self._json(self.sensors.get_status())
    
    def _api_status(self):
        """API: полный статус системы"""
        status = {
            'sensors': self.sensors.get_status(),
            'pump': self.pump.get_status(),
            'vent': self.vent.get_status(),
            'mqtt': {'connected': self.mqtt.connected}
        }
        return self._json(status)
    
    def _cmd_pump_on(self):
        """Команда: включить насос"""
        self.pump.on()
        return self._redirect('/')
    
    def _cmd_pump_off(self):
        """Команда: выключить насос"""
        self.pump.off()
        return self._redirect('/')
    
    def _cmd_pump_toggle(self):
        """Команда: переключить насос"""
        self.pump.toggle()
        return self._redirect('/')
    
    def _cmd_vent(self, path):
        """Команда: управление вентиляцией"""
        if path == '/vent/open':
            self.vent.open(100)
        elif path == '/vent/close':
            self.vent.close()
        else:
            # Попытка извлечь число: /vent/50
            try:
                percent = int(path.split('/')[-1])
                self.vent.set_position(percent)
            except:
                pass
        return self._redirect('/')
    


# ============================================================
# КЛАСС: АВТОМАТИЗАЦИЯ
# ============================================================
class AutomationController:
    """Контроллер автоматизации на основе порогов"""
    
    def __init__(self, pump, vent):
        self.pump = pump
        self.vent = vent
    
    def process(self, sensor_data):
        """Принятие решений на основе данных датчиков"""
        actions = []
        
        # Автоматический полив
        if self.pump.auto_mode:
            soil = sensor_data.get('soil_moisture', 50)
            
            if soil < SOIL_MOISTURE_LOW and not self.pump.is_active:
                self.pump.on()
                actions.append('pump_on_auto')
            
            elif soil > SOIL_MOISTURE_HIGH and self.pump.is_active:
                self.pump.off()
                actions.append('pump_off_auto')
        
        # Автоматическая вентиляция
        temp = sensor_data.get('temperature', 25)
        
        if temp > TEMP_HIGH and self.vent.position < 100:
            self.vent.open(100)
            actions.append('vent_open_auto')
        
        elif temp < TEMP_LOW and self.vent.position > 0:
            self.vent.close()
            actions.append('vent_close_auto')
        
        return actions

# ============================================================
# ФУНКЦИИ СИСТЕМЫ
# ============================================================

def connect_wifi():
    """Подключение к WiFi"""
    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)
    
    if wlan.isconnected():
        print(f"[WiFi] Already connected: {wlan.ifconfig()[0]}")
        return wlan
    
    print(f"[WiFi] Connecting to {WIFI_SSID}...")
    wlan.connect(WIFI_SSID, WIFI_PASSWORD)
    
    # Ожидание подключения
    for i in range(30):
        if wlan.isconnected():
            ip = wlan.ifconfig()[0]
            print(f"[WiFi] Connected! IP: {ip}")
            return wlan
        time.sleep(0.5)
    
    print("[WiFi] Connection failed!")
    return None


def mqtt_command_handler(topic, msg):
    """Обработчик MQTT команд"""
    topic = topic.lower()
    msg = msg.lower().strip()
    
    print(f"[CMD] {topic} -> {msg}")
    
    # Управление насосом
    if 'pump' in topic:
        if msg in ['on', '1', 'true']:
            pump.on()
        elif msg in ['off', '0', 'false']:
            pump.off()
    
    # Управление вентиляцией
    elif 'vent' in topic:
        if msg in ['open', 'on', '100']:
            vent.open(100)
        elif msg in ['close', 'off', '0']:
            vent.close()
        else:
            try:
                percent = int(msg)
                vent.set_position(percent)
            except:
                pass
    
    # Управление камерой

# ============================================================
# ГЛОБАЛЬНЫЕ ПЕРЕМЕННЫЕ
# ============================================================
lcd = None
sensors = None
pump = None
vent = None
mqtt = None
web = None
wlan = None

# ============================================================
# АСИНХРОННЫЕ ЗАДАЧИ
# ============================================================

async def sensor_loop():
    """Задача: периодическое чтение датчиков"""
    global sensors, lcd, pump, vent, mqtt
    
    print("[Task] Sensor loop started")
    
    while True:
        try:
            # Чтение датчиков
            data = sensors.read_all()
            
            # Обновление LCD
            lcd.display_data(
                data['temperature'],
                data['humidity'],
                data['soil_moisture'],
                data['light'],
                data['co2']
            )
            
            # Автоматизация
            auto = AutomationController(pump, vent)
            actions = auto.process(data)
            
            if actions:
                print(f"[Auto] Actions: {actions}")
            
            # Публикация в MQTT
            if mqtt and mqtt.connected:
                mqtt.publish_sensor_data(data)
            
        except Exception as e:
            print(f"[Sensor Loop Error] {e}")
        
        await asyncio.sleep(SENSOR_READ_INTERVAL)


async def mqtt_loop():
    """Задача: поддержание MQTT соединения"""
    global mqtt
    
    print("[Task] MQTT loop started")
    
    while True:
        try:
            if mqtt:
                if mqtt.connected:
                    mqtt.check_msg()
                else:
                    # Попытка переподключения каждые 30 сек
                    mqtt.reconnect()
                    await asyncio.sleep(5)
        except Exception as e:
            print(f"[MQTT Loop Error] {e}")
        
        await asyncio.sleep(1)


async def web_loop():
    """Задача: веб-сервер"""
    global web
    
    print("[Task] Web server starting...")
    
    try:
        await web.start()
    except Exception as e:
        print(f"[Web Loop Error] {e}")

# ============================================================
# ГЛАВНАЯ ФУНКЦИЯ
# ============================================================

async def main():
    """Главная функция запуска системы"""
    global lcd, sensors, pump, vent, mqtt, web, wlan
    
    print("=" * 50)
    print("SMART GREENHOUSE SYSTEM v1.0")
    print("=" * 50)
    
    # Инициализация LCD
    print("[Init] LCD...")
    lcd = LCD_I2C()
    lcd.display_message("Initializing...", "Please wait...")
    
    # Инициализация датчиков
    print("[Init] Sensors...")
    sensors = SensorsManager()
    
    # Инициализация исполнительных устройств
    print("[Init] Actuators...")
    pump = PumpController()
    vent = VentilationController()
    
    # Инициализация камеры
    
    # Подключение WiFi
    lcd.display_message("Connecting WiFi", WIFI_SSID)
    wlan = connect_wifi()
    
    if not wlan:
        lcd.display_message("WiFi Error!", "Check settings")
        print("[Error] WiFi connection failed!")
        return
    
    # Получаем IP
    ip = wlan.ifconfig()[0]
    lcd.display_message("WiFi Connected", ip)
    time.sleep(2)
    
    # Инициализация MQTT
    print("[Init] MQTT...")
    mqtt = MQTTManager(mqtt_command_handler)
    mqtt.connect()
    
    # Инициализация веб-сервера
    print("[Init] Web Server...")
    web = WebServer(sensors, pump, vent, camera, mqtt)
    
    # Готово
    lcd.display_message("System Ready!", ip)
    print("=" * 50)
    print(f"Open in browser: http://{ip}")
    print("=" * 50)
    
    # Запуск задач
    loop = asyncio.get_event_loop()
    
    # Создаем задачи
    loop.create_task(sensor_loop())
    loop.create_task(mqtt_loop())
    loop.create_task(web_loop())
    
    # Бесконечный цикл
    while True:
        await asyncio.sleep(3600)  # Спим час

# ============================================================
# ЗАПУСК
# ============================================================

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n[System] Shutdown...")
    except Exception as e:
        print(f"[System Crash] {e}")
        # Пытаемся перезапустить
        import machine
        machine.reset()
