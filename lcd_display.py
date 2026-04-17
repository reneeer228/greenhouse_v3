from machine import I2C, Pin
import time
from config import *

class LCD_I2C:
    """Класс для работы с LCD 1602/2004 через I2C"""
    
    def __init__(self, i2c_addr=LCD_I2C_ADDR, cols=16, rows=2):
        self.i2c = I2C(0, sda=Pin(PIN_LCD_SDA), scl=Pin(PIN_LCD_SCL), freq=100000)
        self.addr = i2c_addr
        self.cols = cols
        self.rows = rows
        
        # Команды HD44780
        self.CMD_CLEAR = 0x01
        self.CMD_HOME = 0x02
        self.CMD_ENTRY_MODE = 0x06
        self.CMD_DISPLAY_ON = 0x0C
        self.CMD_FUNCTION_SET = 0x28  # 4-bit, 2 lines
        
        self._backlight = 0x08
        self._init_lcd()
    
    def _init_lcd(self):
        """Инициализация LCD"""
        time.sleep_ms(50)
        self._write_cmd(0x03)
        time.sleep_ms(5)
        self._write_cmd(0x03)
        time.sleep_ms(5)
        self._write_cmd(0x03)
        time.sleep_ms(5)
        self._write_cmd(0x02)
        
        self._write_cmd(self.CMD_FUNCTION_SET)
        self._write_cmd(self.CMD_DISPLAY_ON)
        self._write_cmd(self.CMD_CLEAR)
        self._write_cmd(self.CMD_ENTRY_MODE)
        time.sleep_ms(2)
    
    def _write_cmd(self, cmd):
        """Запись команды"""
        self._write_byte(cmd & 0xF0, 0)
        self._write_byte((cmd << 4) & 0xF0, 0)
    
    def _write_data(self, data):
        """Запись данных"""
        self._write_byte(data & 0xF0, 1)
        self._write_byte((data << 4) & 0xF0, 1)
    
    def _write_byte(self, data, mode):
        """Запись байта в I2C"""
        byte = data | self._backlight | mode
        self.i2c.writeto(self.addr, bytes([byte]))
        self.i2c.writeto(self.addr, bytes([byte | 0x04]))  # Enable pulse
        self.i2c.writeto(self.addr, bytes([byte & ~0x04]))
    
    def clear(self):
        """Очистка дисплея"""
        self._write_cmd(self.CMD_CLEAR)
        time.sleep_ms(2)
    
    def home(self):
        """Курсор в начало"""
        self._write_cmd(self.CMD_HOME)
        time.sleep_ms(2)
    
    def set_cursor(self, col, row):
        """Установка курсора"""
        addr = col + (0x40 if row > 0 else 0)
        self._write_cmd(0x80 | addr)
    
    def print(self, text):
        """Вывод текста"""
        for char in text:
            self._write_data(ord(char))
    
    def display_data(self, temp, humidity, soil, light, co2):
        """Отображение данных с датчиков (для LCD 1602)"""
        self.clear()
        
        # Строка 1: Температура и влажность
        line1 = f"T:{temp:.1f}C H:{humidity:.0f}%"
        self.set_cursor(0, 0)
        self.print(line1.ljust(16))
        
        # Строка 2: Почва и свет
        line2 = f"S:{soil:.0f}% L:{light:.0f}%"
        self.set_cursor(0, 1)
        self.print(line2.ljust(16))
    
    def display_message(self, line1, line2=""):
        """Отображение сообщения"""
        self.clear()
        self.set_cursor(0, 0)
        self.print(line1.ljust(16)[:16])
        if line2 and self.rows > 1:
            self.set_cursor(0, 1)
            self.print(line2.ljust(16)[:16])
    
    def backlight_on(self):
        """Включить подсветку"""
        self._backlight = 0x08
        self._write_cmd(0)
    
    def backlight_off(self):
        """Выключить подсветку"""
        self._backlight = 0
        self._write_cmd(0)
