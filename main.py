"""
Умная теплица на Raspberry Pi Pico W
====================================
Основной файл запуска системы
"""

import network
import time
import uasyncio as asyncio
from config import *
from sensors import SensorsManager
from lcd_display import LCD_I2C
from actuators import PumpController, VentilationController, AutomationController
from camera import Arducam
from mqtt_client import MQTTManager
from web_server import WebServer

# Глобальные объекты
lcd = None
sensors = None
pump = None
vent = None
camera = None
mqtt = None
automation = None
web_server = None

def connect_wifi():
    """Подключение к WiFi"""
    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)
    wlan.connect(WIFI_SSID, WIFI_PASSWORD)
    
    print("Подключение к WiFi...")
    attempts = 0
    while not wlan.isconnected() and attempts < 20:
        time.sleep(1)
        attempts += 1
        print(".", end="")
    
    if wlan.isconnected():
        print(f"\nПодключено! IP: {wlan.ifconfig()[0]}")
        lcd.display_message("WiFi OK", wlan.ifconfig()[0])
        return wlan
    else:
        print("\nОшибка подключения WiFi")
        lcd.display_message("WiFi Error", "")
        return None

def mqtt_message_handler(topic, message):
    """Обработчик MQTT сообщений"""
    global pump, vent, camera, mqtt
    
    topic = topic.decode('utf-8') if isinstance(topic, bytes) else topic
    message = message.decode('utf-8') if isinstance(message, bytes) else message
    
    print(f"MQTT команда: {topic} -> {message}")
    
    try:
        if topic == MQTT_TOPIC_PUMP:
            if message.lower() == 'on':
                pump.on()
            elif message.lower() == 'off':
                pump.off()
            mqtt.publish(MQTT_TOPIC_PUMP + "/status", "on" if pump.is_active else "off")
        
        elif topic == MQTT_TOPIC_VENT:
            percent = int(message)
            vent.set_position(percent)
            mqtt.publish(MQTT_TOPIC_VENT + "/status", str(vent.position))
        
        elif topic == MQTT_TOPIC_CAMERA_CMD:
            if message.lower() == 'capture':
                image = camera.capture()
                if image:
                    mqtt.publish_image(image)
                    
    except Exception as e:
        print(f"Ошибка обработки MQTT: {e}")

async def sensor_task():
    """Асинхронная задача чтения датчиков"""
    global sensors, lcd, mqtt, automation
    
    while True:
        try:
            # Чтение всех датчиков
            data = sensors.read_all()
            print(f"Данные: T={data['temperature']}°C, H={data['humidity']}%, "
                  f"Soil={data['soil_moisture']}%, Light={data['light']}%, CO2={data['co2']}ppm")
            
            # Обновление LCD
            lcd.display_data(
                data['temperature'],
                data['humidity'],
                data['soil_moisture'],
                data['light'],
                data['co2']
            )
            
            # Публикация в MQTT
            if mqtt.connected:
                mqtt.publish_sensor_data(data)
            
            # Автоматизация
            automation.process(data)
            
        except Exception as e:
            print(f"Ошибка чтения датчиков: {e}")
        
        await asyncio.sleep(SENSOR_READ_INTERVAL)

async def mqtt_task():
    """Асинхронная задача MQTT"""
    global mqtt
    
    while True:
        try:
            if mqtt.connected:
                mqtt.check_msg()
            else:
                mqtt.reconnect()
        except Exception as e:
            print(f"Ошибка MQTT: {e}")
        
        await asyncio.sleep(1)  # Проверка каждую секунду

async def camera_task():
    """Асинхронная задача камеры (фото каждый час)"""
    global camera, mqtt
    
    while True:
        try:
            # Фото каждый час
            image = camera.capture()
            if image and mqtt.connected:
                mqtt.publish_image(image)
                print("Фото опубликовано")
        except Exception as e:
            print(f"Ошибка камеры: {e}")
        
        await asyncio.sleep(CAMERA_INTERVAL)

async def status_led_task():
    """Индикация статуса (мигание LED)"""
    from machine import Pin
    led = Pin('LED', Pin.OUT)
    
    while True:
        led.value(1)
        await asyncio.sleep(0.1)
        led.value(0)
        await asyncio.sleep(2)

def main():
    """Главная функция"""
    global lcd, sensors, pump, vent, camera, mqtt, automation, web_server
    
    print("=" * 50)
    print("  УМНАЯ ТЕПЛИЦА v1.0")
    print("  Raspberry Pi Pico W")
    print("=" * 50)
    
    # Инициализация LCD
    print("\n[1/7] Инициализация LCD...")
    lcd = LCD_I2C()
    lcd.display_message("Init...", "Please wait")
    
    # Инициализация датчиков
    print("[2/7] Инициализация датчиков...")
    sensors = SensorsManager()
    
    # Инициализация исполнительных устройств
    print("[3/7] Инициализация актуаторов...")
    pump = PumpController()
    vent = VentilationController()
    automation = AutomationController(pump, vent)
    
    # Инициализация камеры
    print("[4/7] Инициализация камеры...")
    camera = Arducam()
    
    # Подключение WiFi
    print("[5/7] Подключение WiFi...")
    wlan = connect_wifi()
    if not wlan:
        print("Проверьте настройки WiFi!")
        lcd.display_message("WiFi Failed!", "Check config")
        while True:
            time.sleep(10)
    
    # Подключение MQTT
    print("[6/7] Подключение MQTT...")
    mqtt = MQTTManager(mqtt_message_handler)
    mqtt.connect()
    
    # Запуск веб-сервера
    print("[7/7] Запуск веб-сервера...")
    web_server = WebServer(sensors, pump, vent, camera, mqtt)
    
    # Запуск асинхронных задач
    print("\nСистема запущена!")
    lcd.display_message("System Ready!", "Monitoring...")
    
    # Создание цикла событий
    loop = asyncio.get_event_loop()
    
    # Регистрация задач
    loop.create_task(sensor_task())
    loop.create_task(mqtt_task())
    loop.create_task(camera_task())
    loop.create_task(status_led_task())
    loop.create_task(web_server.start())
    
    # Запуск цикла
    loop.run_forever()

# Точка входа
if __name__ == "__main__":
    main()
