# main.py
# Система умной теплицы для Raspberry Pi Pico W
# Версия 1.1 - Brat Style UI

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
WIFI_SSID = "ВАШ_WIFI_SSID"
WIFI_PASSWORD = "ВАШ_WIFI_PASSWORD"

# === Настройки MQTT ===
MQTT_BROKER = "broker.hivemq.com"
MQTT_PORT = 1883
MQTT_CLIENT_ID = "pico_greenhouse_01"
MQTT_USER = ""
MQTT_PASSWORD = ""

MQTT_TOPIC_TEMP = "greenhouse/temperature"
MQTT_TOPIC_HUMIDITY = "greenhouse/humidity"
MQTT_TOPIC_CO2 = "greenhouse/co2"
MQTT_TOPIC_SOIL = "greenhouse/soil_moisture"
MQTT_TOPIC_LIGHT = "greenhouse/light"
MQTT_TOPIC_PUMP = "greenhouse/pump/cmd"
MQTT_TOPIC_VENT = "greenhouse/vent/cmd"
MQTT_TOPIC_CAMERA_CMD = "greenhouse/camera/cmd"

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
PIN_CAM_CS = 13

# === Пороги ===
SOIL_MOISTURE_LOW = 30
SOIL_MOISTURE_HIGH = 60
TEMP_HIGH = 28
TEMP_LOW = 22
SENSOR_READ_INTERVAL = 30
WEB_SERVER_PORT = 80

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
        self._write_cmd(0x03); time.sleep_ms(5)
        self._write_cmd(0x03); time.sleep_ms(5)
        self._write_cmd(0x03); time.sleep_ms(5)
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
        self.print(f"T:{temp:.1f}C H:{humidity:.0f}%")
        self.set_cursor(0, 1)
        self.print(f"Soil:{soil:.0f}% L:{light:.0f}%")
    
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
        self.last_data = {'temperature': 0.0, 'humidity': 0.0, 'soil_moisture': 0.0, 'light': 0.0, 'co2': 400, 'timestamp': 0}
    
    def read_dht(self):
        try:
            self.dht_sensor.measure()
            return self.dht_sensor.temperature(), self.dht_sensor.humidity()
        except:
            return None, None
    
    def read_soil_moisture(self):
        raw = self.soil_adc.read_u16()
        percent = (raw - self.soil_min) / (self.soil_max - self.soil_min) * 100
        return max(0, min(100, round(percent, 1)))
    
    def read_light(self):
        raw = self.light_adc.read_u16()
        return round((raw / 65535) * 100, 1)
    
    def read_co2(self):
        raw = self.co2_adc.read_u16()
        voltage = raw * 3.3 / 65535
        return max(400, min(2000, int(400 + (voltage / 3.3) * 1600)))
    
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
    
    def on(self):
        self.relay.value(1)
        self.is_active = True
        print("[pump] on")
    
    def off(self):
        self.relay.value(0)
        self.is_active = False
        print("[pump] off")
    
    def toggle(self):
        self.off() if self.is_active else self.on()
    
    def get_status(self):
        return {'is_active': self.is_active, 'auto_mode': self.auto_mode}

# ============================================================
# КЛАСС: ВЕНТИЛЯЦИЯ
# ============================================================
class VentilationController:
    def __init__(self):
        self.step_pin = Pin(PIN_VENT_STEP, Pin.OUT)
        self.dir_pin = Pin(PIN_VENT_DIR, Pin.OUT)
        self.en_pin = Pin(PIN_VENT_EN, Pin.OUT)
        self.en_pin.value(0)
        self.position = 0
        self.step_delay = 0.001
    
    def _step(self, direction):
        self.dir_pin.value(direction)
        self.step_pin.value(1)
        time.sleep(self.step_delay)
        self.step_pin.value(0)
        time.sleep(self.step_delay)
    
    def set_position(self, target_percent):
        target = min(100, max(0, target_percent))
        steps_needed = int((target - self.position) * 2)
        if steps_needed > 0:
            for _ in range(steps_needed): self._step(1)
        elif steps_needed < 0:
            for _ in range(abs(steps_needed)): self._step(0)
        self.position = target
        print(f"[vent] {self.position}%")
    
    def open(self, percent=100):
        self.set_position(percent)
    
    def close(self):
        self.set_position(0)
    
    def get_status(self):
        return {'position': self.position}

# ============================================================
# КЛАСС: КАМЕРА
# ============================================================
class ArducamController:
    def __init__(self):
        self.spi = SPI(0, baudrate=8000000)
        self.cs = Pin(PIN_CAM_CS, Pin.OUT)
        self.cs.value(1)
        self.last_image = None
    
    def capture(self):
        print("[cam] capture")
        self.last_image = b"img"
        return self.last_image
    
    def get_status(self):
        return {'has_image': self.last_image is not None}

# ============================================================
# КЛАСС: MQTT
# ============================================================
class MQTTManager:
    def __init__(self, cmd_callback=None):
        self.client = None
        self.connected = False
        self.cmd_callback = cmd_callback
    
    def connect(self):
        try:
            self.client = MQTTClient(MQTT_CLIENT_ID, MQTT_BROKER, port=MQTT_PORT)
            self.client.set_callback(self._on_message)
            self.client.connect()
            self.connected = True
            self.client.subscribe(MQTT_TOPIC_PUMP)
            self.client.subscribe(MQTT_TOPIC_VENT)
            print("[mqtt] connected")
            return True
        except Exception as e:
            print(f"[mqtt] error: {e}")
            return False
    
    def _on_message(self, topic, msg):
        if self.cmd_callback:
            self.cmd_callback(topic.decode(), msg.decode())
    
    def publish_sensor_data(self, data):
        if self.connected:
            try:
                self.client.publish(MQTT_TOPIC_TEMP, str(data['temperature']))
                self.client.publish(MQTT_TOPIC_HUMIDITY, str(data['humidity']))
            except:
                self.connected = False
    
    def check_msg(self):
        if self.connected:
            try: self.client.check_msg()
            except: self.connected = False
    
    def reconnect(self):
        self.connected = False
        self.connect()

# ============================================================
# КЛАСС: ВЕБ-СЕРВЕР (BRAT STYLE)
# ============================================================
class WebServer:
    """Brat style web interface"""
    
    def __init__(self, sensors, pump, vent, camera, mqtt):
        self.sensors = sensors
        self.pump = pump
        self.vent = vent
        self.camera = camera
        self.mqtt = mqtt
    
    async def start(self):
        print(f"[web] port {WEB_SERVER_PORT}")
        server = await asyncio.start_server(self.handle_client, "0.0.0.0", WEB_SERVER_PORT)
        async with server:
            await server.serve_forever()
    
    async def handle_client(self, reader, writer):
        try:
            request = await reader.read(1024)
            path = request.decode().split('\r\n')[0].split(' ')[1] if request else '/'
            
            if path == '/': response = self._page()
            elif path == '/api': response = self._json(self.sensors.get_status())
            elif path == '/pump/on': self.pump.on(); response = self._redirect('/')
            elif path == '/pump/off': self.pump.off(); response = self._redirect('/')
            elif path == '/pump/toggle': self.pump.toggle(); response = self._redirect('/')
            elif path == '/vent/open': self.vent.open(); response = self._redirect('/')
            elif path == '/vent/close': self.vent.close(); response = self._redirect('/')
            elif path.startswith('/vent/'):
                try: self.vent.set_position(int(path.split('/')[-1]))
                except: pass
                response = self._redirect('/')
            else: response = self._404()
            
            await writer.awrite(response.encode())
        except: pass
        await writer.aclose()
    
    def _redirect(self, loc): return f"HTTP/1.1 302\r\nLocation: {loc}\r\n\r\n"
    def _json(self, d): return f"HTTP/1.1 200\r\nContent-Type: application/json\r\n\r\n{ujson.dumps(d)}"
    def _404(self): return "HTTP/1.1 404\r\n\r\nnot found"
    
    def _page(self):
        """Brat-style UI"""
        d = self.sensors.get_status()
        pump_state = "on" if self.pump.is_active else "off"
        
        # Brat aesthetic: Arial, lowercase, raw borders, white bg
        html = f"""<!DOCTYPE html>
<html>
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>smart greenhouse</title>
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;700;900&display=swap');

* {{
  margin: 0;
  padding: 0;
  box-sizing: border-box;
}}

body {{
  background-color: #FFFFFF;
  color: #000000;
  font-family: 'Arial Narrow', 'Inter', Arial, sans-serif;
  min-height: 100vh;
  padding: 40px 20px;
  text-transform: lowercase;
}}

.container {{
  max-width: 800px;
  margin: 0 auto;
}}

h1 {{
  font-size: clamp(3rem, 12vw, 8rem);
  font-weight: 900;
  line-height: 0.9;
  margin-bottom: 60px;
  letter-spacing: -0.03em;
  /* Signature Brat blur */
  filter: blur(0.5px);
  -webkit-filter: blur(0.5px);
}}

.grid {{
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
  gap: 12px;
  margin-bottom: 60px;
}}

.card {{
  border: 2px solid #000;
  padding: 15px;
  background: transparent;
  transition: all 0.2s;
}}

.card:hover {{
  background: #f0f0f0;
  transform: translateY(-2px);
}}

.card-label {{
  font-size: 0.7rem;
  opacity: 0.6;
  margin-bottom: 5px;
  font-weight: 400;
}}

.card-value {{
  font-size: 2.2rem;
  font-weight: 900;
  line-height: 1;
}}

.card-unit {{
  font-size: 0.9rem;
  opacity: 0.5;
}}

.section-title {{
  font-size: 1.2rem;
  margin-bottom: 20px;
  opacity: 0.6;
  border-top: 1px solid #000;
  padding-top: 20px;
}}

.btn-group {{
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  margin-bottom: 40px;
}}

.btn {{
  background: #000;
  color: #FFF;
  border: 2px solid #000;
  padding: 12px 24px;
  font-size: 0.9rem;
  font-weight: 700;
  text-decoration: none;
  text-transform: lowercase;
  cursor: pointer;
  transition: all 0.15s;
  font-family: inherit;
}}

.btn:hover {{
  background: #333;
  border-color: #333;
}}

.btn-outline {{
  background: transparent;
  color: #000;
}}

.btn-outline:hover {{
  background: #000;
  color: #FFF;
}}

.status {{
  font-size: 0.8rem;
  opacity: 0.4;
  margin-top: 60px;
  font-family: monospace;
}}

.highlight {{
  background: #000;
  color: #FFF;
  padding: 2px 6px;
  display: inline-block;
}}
</style>
</head>
<body>
<div class="container">
  <h1>smart<br>greenhouse</h1>
  
  <div class="grid">
    <div class="card">
      <div class="card-label">temperature</div>
      <div class="card-value">{d['temperature']:.1f}</div>
      <div class="card-unit">°c</div>
    </div>
    <div class="card">
      <div class="card-label">humidity</div>
      <div class="card-value">{d['humidity']:.0f}</div>
      <div class="card-unit">%</div>
    </div>
    <div class="card">
      <div class="card-label">soil moisture</div>
      <div class="card-value">{d['soil_moisture']:.0f}</div>
      <div class="card-unit">%</div>
    </div>
    <div class="card">
      <div class="card-label">light level</div>
      <div class="card-value">{d['light']:.0f}</div>
      <div class="card-unit">%</div>
    </div>
    <div class="card">
      <div class="card-label">co2</div>
      <div class="card-value">{d['co2']}</div>
      <div class="card-unit">ppm</div>
    </div>
    <div class="card">
      <div class="card-label">ventilation</div>
      <div class="card-value">{self.vent.position}</div>
      <div class="card-unit">% open</div>
    </div>
  </div>
  
  <div class="section-title">controls</div>
  
  <div class="btn-group">
    <a href="/pump/toggle" class="btn">pump toggle</a>
    <a href="/pump/on" class="btn">pump on</a>
    <a href="/pump/off" class="btn btn-outline">pump off</a>
  </div>
  
  <div class="btn-group">
    <a href="/vent/open" class="btn">vent open</a>
    <a href="/vent/50" class="btn btn-outline">vent 50%</a>
    <a href="/vent/close" class="btn btn-outline">vent close</a>
  </div>
  
  <div class="status">
    pump: <span class="highlight">{pump_state}</span> | 
    mqtt: {'connected' if self.mqtt.connected else 'offline'} |
    updated: {time.ticks_ms()//1000}s ago
  </div>
</div>
</body>
</html>"""
        return f"HTTP/1.1 200\r\nContent-Type: text/html\r\n\r\n{html}"

# ============================================================
# АВТОМАТИЗАЦИЯ
# ============================================================
class AutomationController:
    def __init__(self, pump, vent):
        self.pump = pump
        self.vent = vent
    
    def process(self, data):
        if self.pump.auto_mode:
            if data['soil_moisture'] < SOIL_MOISTURE_LOW and not self.pump.is_active:
                self.pump.on()
            elif data['soil_moisture'] > SOIL_MOISTURE_HIGH and self.pump.is_active:
                self.pump.off()
        
        if data['temperature'] > TEMP_HIGH:
            self.vent.open()
        elif data['temperature'] < TEMP_LOW:
            self.vent.close()

# ============================================================
# ГЛОБАЛЬНЫЕ ПЕРЕМЕННЫЕ
# ============================================================
lcd = sensors = pump = vent = camera = mqtt = web = wlan = None

def connect_wifi():
    global wlan
    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)
    wlan.connect(WIFI_SSID, WIFI_PASSWORD)
    for _ in range(30):
        if wlan.isconnected(): return wlan.ifconfig()[0]
        time.sleep(0.5)
    return None

def mqtt_cmd_handler(topic, msg):
    if 'pump' in topic:
        if 'on' in msg: pump.on()
        elif 'off' in msg: pump.off()
    elif 'vent' in topic:
        try: vent.set_position(int(msg))
        except: pass

# ============================================================
# ЗАДАЧИ
# ============================================================
async def sensor_loop():
    while True:
        data = sensors.read_all()
        lcd.display_data(data['temperature'], data['humidity'], data['soil_moisture'], data['light'], data['co2'])
        AutomationController(pump, vent).process(data)
        if mqtt.connected: mqtt.publish_sensor_data(data)
        await asyncio.sleep(SENSOR_READ_INTERVAL)

async def mqtt_loop():
    while True:
        if mqtt.connected:
            mqtt.check_msg()
        else:
            mqtt.reconnect()
            await asyncio.sleep(5)
        await asyncio.sleep(1)

async def web_loop():
    await web.start()

# ============================================================
# MAIN
# ============================================================
async def main():
    global lcd, sensors, pump, vent, camera, mqtt, web
    
    print("=" * 40)
    print("smart greenhouse v1.1 (brat edition)")
    print("=" * 40)
    
    lcd = LCD_I2C()
    lcd.display_message("booting...", "brat mode")
    
    sensors = SensorsManager()
    pump = PumpController()
    vent = VentilationController()
    camera = ArducamController()
    
    lcd.display_message("wifi connect", WIFI_SSID)
    ip = connect_wifi()
    
    if not ip:
        lcd.display_message("wifi error", ":(")
        return
    
    lcd.display_message("connected!", ip)
    time.sleep(2)
    
    mqtt = MQTTManager(mqtt_cmd_handler)
    mqtt.connect()
    
    web = WebServer(sensors, pump, vent, camera, mqtt)
    
    lcd.display_message("ready", ip)
    print(f"open http://{ip}")
    
    loop = asyncio.get_event_loop()
    loop.create_task(sensor_loop())
    loop.create_task(mqtt_loop())
    loop.create_task(web_loop())
    
    while True:
        await asyncio.sleep(3600)

# ============================================================
# RUN
# ============================================================
if __name__ == "__main__":
    try:
        asyncio.run(main())
    except:
        import machine
        machine.reset()
