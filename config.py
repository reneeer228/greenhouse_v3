# WiFi настройки
WIFI_SSID = "ВАШ_WIFI_SSID"
WIFI_PASSWORD = "ВАШ_WIFI_PASSWORD"

# MQTT настройки
MQTT_BROKER = "broker.hivemq.com"  # или свой сервер
MQTT_PORT = 1883
MQTT_CLIENT_ID = "pico_greenhouse"
MQTT_USER = ""  # если нужен
MQTT_PASSWORD = ""  # если нужен

# Топики MQTT
MQTT_TOPIC_TEMP = "greenhouse/temperature"
MQTT_TOPIC_HUMIDITY = "greenhouse/humidity"
MQTT_TOPIC_CO2 = "greenhouse/co2"
MQTT_TOPIC_SOIL = "greenhouse/soil_moisture"
MQTT_TOPIC_LIGHT = "greenhouse/light"
MQTT_TOPIC_CAMERA = "greenhouse/camera"
MQTT_TOPIC_PUMP = "greenhouse/pump"
MQTT_TOPIC_VENT = "greenhouse/vent"
MQTT_TOPIC_CAMERA_CMD = "greenhouse/camera/command"

# Пины GPIO
PIN_DHT = 15           # DHT22
PIN_SOIL = 26          # Аналоговый датчик влажности почвы (ADC0)
PIN_LIGHT = 27         # Аналоговый датчик света (ADC1)
PIN_CO2 = 28           # Аналоговый CO2 датчик (ADC2)
PIN_PUMP = 16          # Реле насоса
PIN_VENT_STEP = 17     # Шаговый мотор - STEP
PIN_VENT_DIR = 18      # Шаговый мотор - DIR
PIN_VENT_EN = 19       # Шаговый мотор - ENABLE
PIN_LCD_SDA = 20       # I2C SDA для LCD
PIN_LCD_SCL = 21       # I2C SCL для LCD

# I2C адрес LCD (обычно 0x27 или 0x3F)
LCD_I2C_ADDR = 0x27

# Пороги автоматизации
SOIL_MOISTURE_LOW = 30      # % - включить полив
SOIL_MOISTURE_HIGH = 60     # % - выключить полив
TEMP_HIGH = 28             # °C - открыть вентиляцию
TEMP_LOW = 22              # °C - закрыть вентиляцию

# Интервалы
SENSOR_READ_INTERVAL = 30  # секунды между чтением датчиков
CAMERA_INTERVAL = 3600     # секунды между фото (1 час)
WEB_SERVER_PORT = 80
