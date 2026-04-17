import uasyncio as asyncio
from machine import Pin
import ujson
import time
from config import *

class WebServer:
    """Асинхронный веб-сервер"""
    
    def __init__(self, sensors, pump, vent, camera, mqtt):
        self.sensors = sensors
        self.pump = pump
        self.vent = vent
        self.camera = camera
        self.mqtt = mqtt
        self.running = False
    
    async def start(self, port=WEB_SERVER_PORT):
        """Запуск сервера"""
        self.running = True
        print(f"Веб-сервер запущен на порту {port}")
        
        server = await asyncio.start_server(
            self.handle_client,
            '0.0.0.0',
            port
        )
        
        async with server:
            await server.serve_forever()
    
    async def handle_client(self, reader, writer):
        """Обработка запроса клиента"""
        try:
            # Чтение запроса
            request = await reader.read(1024)
            request = request.decode('utf-8')
            
            # Парсинг пути
            lines = request.split('\r\n')
            if lines:
                first_line = lines[0].split(' ')
                if len(first_line) >= 2:
                    method = first_line[0]
                    path = first_line[1]
                else:
                    method = 'GET'
                    path = '/'
            else:
                method = 'GET'
                path = '/'
            
            # Маршрутизация
            if path == '/' or path == '/index.html':
                response = self.get_index_page()
            elif path == '/api/sensors':
                response = self.get_sensor_api()
            elif path == '/api/status':
                response = self.get_status_api()
            elif path == '/api/pump/on':
                response = self.pump_control('on')
            elif path == '/api/pump/off':
                response = self.pump_control('off')
            elif path.startswith('/api/vent/'):
                percent = int(path.split('/')[-1])
                response = self.vent_control(percent)
            elif path == '/api/camera/capture':
                response = self.camera_capture()
            elif path == '/api/camera/last':
                response = self.get_camera_image()
            elif path == '/style.css':
                response = self.get_css()
            else:
                response = self.get_404()
            
            # Отправка ответа
            await writer.awrite(response)
            
        except Exception as e:
            print(f"Ошибка обработки запроса: {e}")
        finally:
            await writer.aclose()
    
    def send_response(self, content, content_type='text/html', status='200 OK'):
        """Формирование HTTP ответа"""
        headers = (
            f"HTTP/1.1 {status}\r\n"
            f"Content-Type: {content_type}\r\n"
            f"Connection: close\r\n"
            f"\r\n"
        )
        return headers + content
    
    def get_index_page(self):
        """Главная страница с дашбордом"""
        data = self.sensors.get_status()
        
        html = """<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Умная теплица</title>
    <link rel="stylesheet" href="/style.css">
</head>
<body>
    <div class="container">
        <h1>🌱 Умная теплица</h1>
        
        <div class="sensors-grid">
            <div class="sensor-card">
                <h3>🌡️ Температура</h3>
                <div class="value">""" + str(data['temperature']) + """°C</div>
            </div>
            <div class="sensor-card">
                <h3>💧 Влажность</h3>
                <div class="value">""" + str(data['humidity']) + """%</div>
            </div>
            <div class="sensor-card">
                <h3>🌿 Почва</h3>
                <div class="value">""" + str(data['soil_moisture']) + """%</div>
            </div>
            <div class="sensor-card">
                <h3>☀️ Свет</h3>
                <div class="value">""" + str(data['light']) + """%</div>
            </div>
            <div class="sensor-card">
                <h3>💨 CO2</h3>
                <div class="value">""" + str(data['co2']) + """ ppm</div>
            </div>
        </div>
        
        <div class="controls">
            <h2>Управление</h2>
            <div class="control-group">
                <h3>Насос полива</h3>
                <button onclick="pumpOn()" class="btn btn-green">ВКЛ</button>
                <button onclick="pumpOff()" class="btn btn-red">ВЫКЛ</button>
                <span id="pump-status">""" + ("Включен" if self.pump.is_active else "Выключен") + """</span>
            </div>
            
            <div class="control-group">
                <h3>Вентиляция</h3>
                <button onclick="setVent(0)" class="btn">Закрыть</button>
                <button onclick="setVent(50)" class="btn">50%</button>
                <button onclick="setVent(100)" class="btn">Открыть</button>
                <span id="vent-status">""" + str(self.vent.position) + """%</span>
            </div>
            
            <div class="control-group">
                <h3>Камера</h3>
                <button onclick="capturePhoto()" class="btn">📷 Снять фото</button>
            </div>
        </div>
        
        <div id="last-photo"></div>
        
        <script>
            function pumpOn() {
                fetch('/api/pump/on').then(r => r.text()).then(updateStatus);
            }
            function pumpOff() {
                fetch('/api/pump/off').then(r => r.text()).then(updateStatus);
            }
            function setVent(percent) {
                fetch('/api/vent/' + percent).then(r => r.text()).then(updateStatus);
            }
            function capturePhoto() {
                fetch('/api/camera/capture');
                alert('Фото будет сделано!');
            }
            function updateStatus() {
                location.reload();
            }
            setInterval(() => location.reload(), 30000);
        </script>
    </div>
</body>
</html>"""
        return self.send_response(html)
    
    def get_css(self):
        """CSS стили"""
        css = """
* { box-sizing: border-box; margin: 0; padding: 0; }
body { font-family: Arial, sans-serif; background: #1a1a2e; color: #eee; padding: 20px; }
.container { max-width: 800px; margin: 0 auto; }
h1 { text-align: center; margin-bottom: 30px; color: #4ecca3; }
h2 { margin: 20px 0 10px; color: #4ecca3; }
h3 { margin-bottom: 10px; }
.sensors-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 15px; margin-bottom: 30px; }
.sensor-card { background: #16213e; border-radius: 10px; padding: 20px; text-align: center; }
.value { font-size: 2em; font-weight: bold; color: #4ecca3; }
.controls { background: #16213e; border-radius: 10px; padding: 20px; margin-bottom: 20px; }
.control-group { margin: 20px 0; padding: 15px 0; border-bottom: 1px solid #333; }
.btn { padding: 10px 20px; margin: 5px; border: none; border-radius: 5px; cursor: pointer; font-size: 1em; background: #4ecca3; color: #1a1a2e; }
.btn:hover { opacity: 0.8; }
.btn-green { background: #4ecca3; }
.btn-red { background: #e94560; color: white; }
"""
        return self.send_response(css, 'text/css')
    
    def get_sensor_api(self):
        """API датчиков (JSON)"""
        data = self.sensors.get_status()
        data['timestamp'] = time.time()
        return self.send_response(ujson.dumps(data), 'application/json')
    
    def get_status_api(self):
        """Полный статус системы"""
        status = {
            'sensors': self.sensors.get_status(),
            'pump': self.pump.get_status(),
            'ventilation': self.vent.get_status(),
            'camera': self.camera.get_status(),
            'mqtt': {'connected': self.mqtt.connected}
        }
        return self.send_response(ujson.dumps(status), 'application/json')
    
    def pump_control(self, action):
        """Управление насосом"""
        if action == 'on':
            self.pump.on()
        else:
            self.pump.off()
        return self.send_response(ujson.dumps({'status': 'ok', 'pump': action}))
    
    def vent_control(self, percent):
        """Управление вентиляцией"""
        self.vent.set_position(percent)
        return self.send_response(ujson.dumps({'status': 'ok', 'position': percent}))
    
    def camera_capture(self):
        """Захват фото"""
        image = self.camera.capture()
        if image:
            self.mqtt.publish_image(image)
            return self.send_response(ujson.dumps({'status': 'captured'}))
        return self.send_response(ujson.dumps({'status': 'error'}), status='500 Error')
    
    def get_camera_image(self):
        """Получить последнее фото"""
        image = self.camera.get_last_image()
        if image:
            return self.send_response(image, 'image/jpeg')
        return self.send_response('No image', status='404 Not Found')
    
    def get_404(self):
        """Страница 404"""
        return self.send_response('<h1>404 Not Found</h1>', status='404 Not Found')
