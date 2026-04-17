from machine import Pin, ADC
import dht
import time
from config import *

class SensorsManager:
    """Класс для управления всеми датчиками"""
    
    def __init__(self):
        # Инициализация DHT22
        self.dht_sensor = dht.DHT22(Pin(PIN_DHT))
        
        # Инициализация аналоговых датчиков
        self.soil_adc = ADC(Pin(PIN_SOIL))
        self.light_adc = ADC(Pin(PIN_LIGHT))
        self.co2_adc = ADC(Pin(PIN_CO2))
        
        # Калибровочные значения (настройте под ваши датчики)
        self.soil_min = 0      # сухая почва
        self.soil_max = 65535  # мокрая почва
        self.light_min = 0
        self.light_max = 65535
        self.co2_min = 0
        self.co2_max = 65535
        
        # Кэш последних значений
        self.last_data = {
            'temperature': 0,
            'humidity': 0,
            'soil_moisture': 0,
            'light': 0,
            'co2': 0,
            'timestamp': 0
        }
    
    def read_dht(self):
        """Чтение температуры и влажности DHT22"""
        try:
            self.dht_sensor.measure()
            temp = self.dht_sensor.temperature()
            hum = self.dht_sensor.humidity()
            return temp, hum
        except Exception as e:
            print(f"Ошибка чтения DHT22: {e}")
            return None, None
    
    def read_soil_moisture(self):
        """Чтение влажности почвы (%)
        Возвращает 0-100%, где 100% = полностью мокро"""
        raw = self.soil_adc.read_u16()
        # Инвертируем, так как обычно больше значение = суше
        percent = 100 - ((raw - self.soil_min) / (self.soil_max - self.soil_min) * 100)
        percent = max(0, min(100, percent))  # Ограничиваем 0-100
        return round(percent, 1)
    
    def read_light(self):
        """Чтение уровня освещенности (люксы или %)"""
        raw = self.light_adc.read_u16()
        # Преобразование в проценты
        percent = (raw - self.light_min) / (self.light_max - self.light_min) * 100
        percent = max(0, min(100, percent))
        return round(percent, 1)
    
    def read_co2(self):
        """Чтение уровня CO2 (ppm)"""
        raw = self.co2_adc.read_u16()
        # Для MQ-135 или аналогичного датчика
        # Это приблизительная формула, нужна калибровка!
        voltage = raw * 3.3 / 65535
        # Предполагаем диапазон 400-2000 ppm
        co2_ppm = int(400 + (voltage / 3.3) * 1600)
        return max(400, min(2000, co2_ppm))
    
    def read_all(self):
        """Чтение всех датчиков"""
        temp, hum = self.read_dht()
        soil = self.read_soil_moisture()
        light = self.read_light()
        co2 = self.read_co2()
        
        self.last_data = {
            'temperature': temp if temp else self.last_data['temperature'],
            'humidity': hum if hum else self.last_data['humidity'],
            'soil_moisture': soil,
            'light': light,
            'co2': co2,
            'timestamp': time.time()
        }
        
        return self.last_data
    
    def get_status(self):
        """Получить статус всех датчиков"""
        return self.last_data
