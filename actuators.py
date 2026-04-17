from machine import Pin
import time
from config import *

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
        print("Насос ВКЛ")
    
    def off(self):
        """Выключить насос"""
        self.relay.value(0)
        self.is_active = False
        print("Насос ВЫКЛ")
    
    def pump_for_duration(self, duration_sec):
        """Полив на определенное время"""
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


class VentilationController:
    """Контроллер вентиляции на шаговом двигателе"""
    
    def __init__(self, steps_per_rev=200, rpm=60):
        # Пины A4988/DRV8825 драйвера
        self.step_pin = Pin(PIN_VENT_STEP, Pin.OUT)
        self.dir_pin = Pin(PIN_VENT_DIR, Pin.OUT)
        self.en_pin = Pin(PIN_VENT_EN, Pin.OUT)
        
        self.en_pin.value(0)  # Включить драйвер
        
        self.steps_per_rev = steps_per_rev
        self.rpm = rpm
        self.step_delay = 60 / (rpm * steps_per_rev) / 2
        
        # Положение заслонки (0-100%)
        self.position = 0  # 0 = закрыто, 100 = открыто
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
    
    def open(self, percent=100):
        """Открыть вентиляцию"""
        target = min(100, max(0, percent))
        steps_needed = int((target - self.position) * self.steps_per_rev * 2 / 100)
        
        if steps_needed > 0:
            self.move_steps(steps_needed, 1)  # Направление открытия
        elif steps_needed < 0:
            self.move_steps(abs(steps_needed), 0)  # Направление закрытия
        
        self.position = target
        print(f"Вентиляция: {self.position}%")
    
    def close(self):
        """Закрыть вентиляцию"""
        self.open(0)
    
    def set_position(self, percent):
        """Установить позицию"""
        self.open(percent)
    
    def get_status(self):
        return {
            'position': self.position,
            'is_moving': self.is_moving
        }


class AutomationController:
    """Контроллер автоматизации"""
    
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
                actions.append('pump_on')
            elif soil > SOIL_MOISTURE_HIGH and self.pump.is_active:
                self.pump.off()
                actions.append('pump_off')
        
        # Автоматическая вентиляция
        temp = sensor_data.get('temperature', 25)
        if temp > TEMP_HIGH and self.vent.position < 100:
            self.vent.open(100)
            actions.append('vent_open')
        elif temp < TEMP_LOW and self.vent.position > 0:
            self.vent.close()
            actions.append('vent_close')
        
        return actions
