from flask import Flask, render_template_string, request, jsonify, session
import folium
from geopy.geocoders import Nominatim
import ssl
import certifi
from functools import lru_cache
import requests
from requests import Session
from bs4 import BeautifulSoup
import re
from datetime import datetime
import json
import os
from urllib.parse import urljoin
import time

app = Flask(__name__)
app.secret_key = 'your_secret_key'  # Замените на ваш секретный ключ

# Фикс SSL проблем для geopy
ssl_context = ssl.create_default_context(cafile=certifi.where())

# Кешируем геокодирование для уменьшения запросов к API
@lru_cache(maxsize=100)
def search_locations(query):
    geolocator = Nominatim(
        user_agent="map_application",
        ssl_context=ssl_context,
        timeout=20
    )
    try:
        locations = geolocator.geocode(query, country_codes='RU', exactly_one=False)
        return locations if locations else []
    except Exception as e:
        print(f"Geocoding error: {e}")
        return []

def create_map(lat, lon, points=None, routes=None, zoom_start=15, map_layer='satellite', old_map=False):
    tile_urls = {
        'satellite': 'https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}',
        'topographic': 'https://{s}.tile.opentopomap.org/{z}/{x}/{y}.png',
        'street': 'https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png'
    }

    m = folium.Map(
        location=[lat, lon],
        zoom_start=zoom_start,
        tiles=tile_urls[map_layer],
        attr='Map data'
    )

    # Добавляем исторические карты если включены
    if old_map:
        folium.TileLayer(
            tiles='https://maps.etomesto.ru/tiles/1880/{z}/{x}/{y}.png',
            attr='Историческая карта 1880 года',
            name='Историческая карта',
            overlay=True,
            control=True
        ).add_to(m)

    if points:
        for point in points:
            folium.Marker(
                location=[point[0], point[1]],
                popup=f"Point: {point[0]}, {point[1]}",
                icon=folium.Icon(color='red', icon='treasure-sign', prefix='fa')
            ).add_to(m)

    if routes:
        folium.PolyLine(routes, color="blue", weight=2.5, opacity=1).add_to(m)

    # Добавляем контроль слоев
    folium.LayerControl().add_to(m)

    return m

def get_weather(lat, lon):
    """Получаем текущую температуру в пиратском стиле"""
    try:
        url = f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}&current_weather=true"
        response = requests.get(url, timeout=20)
        data = response.json()

        # Проверяем, что данные содержат нужные поля
        if 'current_weather' not in data:
            return None

        temp = data['current_weather'].get('temperature')
        if temp is None:
            return None

        # Пиратские описания температуры
        if temp < -10:
            description = "Лютый холод! Даже черти в аду кутаются!"
        elif -10 <= temp < 0:
            description = "Морозец, но для настоящего пиратского рома в самый раз!"
        elif 0 <= temp < 10:
            description = "Прохладно, как в трюме после шторма"
        elif 10 <= temp < 20:
            description = "Отличная погода для поиска сокровищ!"
        elif 20 <= temp < 30:
            description = "Жара, но для кладоискателя это не помеха!"
        else:
            description = "Адская жара! Где мой ром?!"

        return {
            'temp': temp,
            'description': description,
            'time': datetime.now().strftime("%d.%m.%Y %H:%M")
        }
    except Exception as e:
        print(f"Weather API error: {e}")
        return None

def parse_clad_sites(location_name):
    """Парсим тематические сайты о кладах в указанном регионе"""
    sites = [
        ("http://samara-clad.ru/", "div.post-content"),
        ("https://samarafishing.ru/board/index.php?topic=40553.0", "div.post"),
        ("https://mdrussia.ru/topic/89888-samarskaja-oblast/", "div.msg")
    ]

    results = []

    for url, selector in sites:
        try:
            response = requests.get(url, timeout=20)
            soup = BeautifulSoup(response.text, 'html.parser')
            posts = soup.select(selector)

            for post in posts[:3]:  # Берем первые 3 записи
                text = post.get_text(separator=' ', strip=True)
                if location_name.lower() in text.lower():
                    # Очищаем текст от лишних пробелов и переносов
                    text = ' '.join(text.split())
                    results.append({
                        'source': url,
                        'text': text[:500] + '...' if len(text) > 500 else text
                    })
                    if len(results) >= 3:  # Ограничиваемся 3 результатами
                        break
        except Exception as e:
            print(f"Error parsing {url}: {e}")
            continue

    return results

def get_treasure_info(lat, lon, radius=5):
    """Получаем информацию о возможных кладах в регионе через нейросеть"""
    API_KEY = "_____"
    MODEL = "deepseek/deepseek-r1:free"

    # Сначала получаем название местности
    geolocator = Nominatim(user_agent="treasure_app", ssl_context=ssl_context)
    location = geolocator.reverse(f"{lat}, {lon}", language='ru')
    location_name = location.address if location else "этом районе"

    # Парсим сайты
    parsed_info = parse_clad_sites(location_name.split(',')[0])

    prompt = f"""
    Ты — кладоискатель со стажем! Отвечай только на вопросы, связанные с кладоискательством.
    Проанализируй регион {location_name} (координаты: {lat}, {lon}, радиус {radius} км) как эксперт:

    1. Историческая справка (коротко, только факты):
       - Какие народы здесь жили?
       - Были ли значимые события (войны, переселения)?
       - Где могли прятать ценности?

    2. Анализ местности для поиска кладов (3-4 конкретных совета):
       - Где искать (старые деревни, дороги, берега рек)?
       - На что обратить внимание (аномалии рельефа, старые карты)?

    3. Парсинг с тематических сайтов (уже выполнено, используй эту информацию):
       {parsed_info if parsed_info else "Нет данных с тематических сайтов"}

    Ответ дай в формате HTML, без лишних вступлений. Будь конкретным и критичным.
    Если данных действительно нет, скажи честно — не придумывай.
    """

    headers = {
        "Authorization": f"Bearer {API_KEY}",
        "Content-Type": "application/json"
    }

    data = {
        "model": MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.8
    }

    try:
        with Session() as session:
            response = session.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers=headers,
                json=data,
                timeout=30
            )
            response.raise_for_status()
            result = response.json()
            return result['choices'][0]['message']['content']
    except Exception as e:
        print(f"AI API error: {e}")
        return "Не удалось получить информацию. Попробуйте позже."

def get_historical_data(lat, lon):
    """Получаем исторические данные о местности"""
    # Получаем название местности
    geolocator = Nominatim(user_agent="treasure_app", ssl_context=ssl_context)
    location = geolocator.reverse(f"{lat}, {lon}", language='ru')
    location_name = location.address.split(',')[0] if location else "этом районе"

    # Получаем данные из разных источников
    wikipedia_text = get_wikipedia_data(location_name)
    privolge_text = get_privolge_data(location_name)
    etomesto_text = get_etomesto_data(location_name)

    # Объединяем информацию
    combined_text = f"""
    Данные по региону {location_name}:

    Википедия:
    {wikipedia_text if wikipedia_text else "Нет данных из Википедии"}

    Privolge (исчезнувшие деревни):
    {privolge_text if privolge_text else "Нет данных с Privolge"}

    Etomesto (исторические карты):
    {etomesto_text if etomesto_text else "Нет данных с Etomesto"}
    """

    # Анализируем информацию с помощью нейросети
    analysis = analyze_with_ai(combined_text)

    return analysis

def get_wikipedia_data(location_name):
    """Получаем данные с Википедии по всем регионам"""
    try:
        base_url = "https://ru.wikipedia.org"
        search_url = f"{base_url}/w/index.php?search={location_name}"

        response = requests.get(search_url, timeout=20)
        soup = BeautifulSoup(response.text, 'html.parser')

        # Ищем все ссылки на статьи, связанные с этим регионом
        links = []
        for link in soup.select('div.mw-search-result-heading a'):
            href = link.get('href')
            if href and not href.startswith('#'):
                links.append(urljoin(base_url, href))

        # Также проверяем категории
        for cat in soup.select('div.mw-search-results li a[href^="/wiki/Category:"]'):
            href = cat.get('href')
            if href:
                links.append(urljoin(base_url, href))

        # Убираем дубликаты
        links = list(set(links))

        # Собираем текст со всех найденных страниц
        all_text = []
        for link in links[:5]:  # Ограничиваемся 5 страницами для скорости
            try:
                time.sleep(1)  # Задержка между запросами
                page_response = requests.get(link, timeout=20)
                page_soup = BeautifulSoup(page_response.text, 'html.parser')

                # Получаем основной текст статьи
                content = page_soup.find('div', {'id': 'mw-content-text'})
                if content:
                    # Удаляем таблицы и боковые панели
                    for element in content(['table', 'div.infobox', 'div.thumb']):
                        element.decompose()

                    text = content.get_text(separator=' ', strip=True)
                    text = ' '.join(text.split())  # Удаляем лишние пробелы
                    all_text.append(text[:2000])  # Ограничиваем длину текста
            except Exception as e:
                print(f"Error parsing Wikipedia page {link}: {e}")
                continue

        return ' '.join(all_text)
    except Exception as e:
        print(f"Error getting Wikipedia data: {e}")
        return ""

def get_privolge_data(location_name):
    """Получаем данные с сайта Privolge"""
    try:
        url = "https://privolge.ru/ischeznuvshie-derevni/"
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/58.0.3029.110 Safari/537.3'
        }
        response = requests.get(url, headers=headers, timeout=20)
        soup = BeautifulSoup(response.text, 'html.parser')

        # Ищем все статьи, связанные с этим регионом
        articles = []
        for article in soup.find_all('article'):
            if location_name.lower() in article.get_text().lower():
                # Удаляем ненужные элементы
                for element in article(['script', 'style', 'iframe', 'img']):
                    element.decompose()

                text = article.get_text(separator=' ', strip=True)
                text = ' '.join(text.split())
                articles.append(text[:2000])  # Ограничиваем длину текста

        return ' '.join(articles)
    except Exception as e:
        print(f"Error getting Privolge data: {e}")
        return ""

def get_etomesto_data(location_name):
    """Получаем данные с сайта etomesto.ru"""
    try:
        url = f"https://www.etomesto.ru/search/?query={location_name}"
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/58.0.3029.110 Safari/537.3'
        }
        response = requests.get(url, headers=headers, timeout=20)
        soup = BeautifulSoup(response.text, 'html.parser')

        # Ищем информацию о картах
        maps_info = []
        for item in soup.select('div.search-item'):
            title = item.select_one('h3 a')
            if title and location_name.lower() in title.get_text().lower():
                desc = item.select_one('div.search-item-desc')
                if desc:
                    text = desc.get_text(separator=' ', strip=True)
                    text = ' '.join(text.split())
                    maps_info.append(text[:1000])  # Ограничиваем длину текста

        return ' '.join(maps_info)
    except Exception as e:
        print(f"Error getting etomesto data: {e}")
        return ""

def analyze_with_ai(text):
    """Анализируем текст с помощью нейросети"""
    API_KEY = "________"
    MODEL = "deepseek/deepseek-r1:free"

    prompt = f"""
    Ты — кладоискатель со стажем! Проанализируй следующие данные и выдели важную информацию о возможных местах для поиска кладов:

    {text}

    Ответ дай в формате HTML, без лишних вступлений. Будь конкретным и критичным.
    Если данных действительно нет, скажи честно — не придумывай.
    """

    headers = {
        "Authorization": f"Bearer {API_KEY}",
        "Content-Type": "application/json"
    }

    data = {
        "model": MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.8
    }

    try:
        with Session() as session:
            response = session.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers=headers,
                json=data,
                timeout=30
            )
            response.raise_for_status()
            result = response.json()
            return result['choices'][0]['message']['content']
    except Exception as e:
        print(f"AI API error: {e}")
        return "Не удалось получить информацию. Попробуйте позже."

HTML_TEMPLATE = '''
<!DOCTYPE html>
<html>
<head>
    <title>Карта старого копателя</title>
    <meta charset="utf-8">
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.0.0/css/all.min.css">
    <style>
        body {
            display: flex;
            margin: 0;
            padding: 0;
            font-family: 'Georgia', serif;
            background-color: #f5f5f5;
        }
        #map {
            width: 70%;
            height: 100vh;
            border-right: 3px solid #8B4513;
        }
        #sidebar {
            width: 30%;
            height: 100vh;
            background-color: #2E2E2E;
            color: #D2B48C;
            padding: 15px;
            overflow-y: auto;
            box-shadow: -2px 0 5px rgba(0,0,0,0.5);
        }
        .form-group {
            margin-bottom: 15px;
        }
        .form-group label {
            display: block;
            margin-bottom: 5px;
            font-weight: bold;
            color: #F4A460;
        }
        .form-group input {
            width: 100%;
            padding: 8px;
            background: #3E3E3E;
            border: 1px solid #8B4513;
            color: #D2B48C;
        }
        button {
            width: 100%;
            padding: 10px;
            margin-top: 10px;
            background: #8B4513;
            color: white;
            border: none;
            cursor: pointer;
            font-weight: bold;
            transition: background 0.3s;
        }
        button:hover {
            background: #A0522D;
        }
        .error {
            color: #FF6347;
            margin-top: 10px;
            padding: 5px;
            border-left: 3px solid #FF6347;
        }
        .location-list {
            margin-top: 15px;
            display: none;
            border: 1px solid #8B4513;
            border-radius: 5px;
        }
        .location-item {
            padding: 10px;
            border-bottom: 1px solid #8B4513;
            cursor: pointer;
            transition: background 0.2s;
        }
        .location-item:hover {
            background-color: #3E3E3E;
        }
        .treasure-info {
            margin-top: 20px;
            background: #3E3E3E;
            padding: 15px;
            border-radius: 5px;
            border: 1px solid #8B4513;
        }
        .treasure-info h3 {
            color: #F4A460;
            border-bottom: 1px dashed #8B4513;
            padding-bottom: 5px;
        }
        .expert-advice {
            font-size: 14px;
            line-height: 1.6;
        }
        .expert-advice h3 {
            color: #F4A460;
            margin-top: 10px;
        }
        .expert-advice p {
            margin: 8px 0;
            padding-left: 10px;
            border-left: 2px solid #8B4513;
        }
        .chat-message {
            margin: 10px 0;
            padding: 8px 12px;
            border-radius: 5px;
            max-width: 80%;
        }
        .user-message {
            background: #8B4513;
            margin-left: auto;
            color: white;
        }
        .bot-message {
            background: #3E3E3E;
            margin-right: auto;
            border: 1px solid #8B4513;
        }
        #chat-container {
            height: 200px;
            overflow-y: auto;
            margin-top: 15px;
            padding: 10px;
            background: #2E2E2E;
            border: 1px solid #8B4513;
            border-radius: 5px;
        }
        #chat-input {
            width: calc(100% - 70px);
            padding: 8px;
            background: #3E3E3E;
            border: 1px solid #8B4513;
            color: #D2B48C;
        }
        #send-btn {
            width: 60px;
            padding: 8px;
            margin-left: 5px;
        }
        .weather-info {
            margin-top: 15px;
            padding: 10px;
            background: #3E3E3E;
            border: 1px solid #8B4513;
            border-radius: 5px;
        }
        .weather-info h3 {
            color: #F4A460;
            margin-top: 0;
            border-bottom: 1px dashed #8B4513;
            padding-bottom: 5px;
        }
        .weather-temp {
            font-size: 24px;
            font-weight: bold;
            color: #F4A460;
            margin: 5px 0;
        }
        .weather-desc {
            font-style: italic;
            margin-bottom: 5px;
        }
        .weather-time {
            font-size: 12px;
            color: #A0A0A0;
            text-align: right;
        }
        .route-actions {
            margin-top: 15px;
            display: flex;
            justify-content: space-between;
        }
        .route-actions button {
            width: 48%;
            padding: 8px;
            background: #8B4513;
            color: white;
            border: none;
            cursor: pointer;
            font-weight: bold;
            transition: background 0.3s;
        }
        .route-actions button:hover {
            background: #A0522D;
        }
        .historical-data {
            margin-top: 15px;
            padding: 10px;
            background: #3E3E3E;
            border: 1px solid #8B4513;
            border-radius: 5px;
        }
        .historical-data h3 {
            color: #F4A460;
            margin-top: 0;
            border-bottom: 1px dashed #8B4513;
            padding-bottom: 5px;
        }
        .historical-data p {
            margin: 5px 0;
        }
        .social-share {
            margin-top: 15px;
            display: flex;
            justify-content: space-between;
        }
        .social-share button {
            width: 48%;
            padding: 8px;
            background: #8B4513;
            color: white;
            border: none;
            cursor: pointer;
            font-weight: bold;
            transition: background 0.3s;
        }
        .social-share button:hover {
            background: #A0522D;
        }
        .map-layer-selector {
            margin-top: 15px;
            padding: 10px;
            background: #3E3E3E;
            border: 1px solid #8B4513;
            border-radius: 5px;
        }
        .map-layer-selector h3 {
            color: #F4A460;
            margin-top: 0;
            border-bottom: 1px dashed #8B4513;
            padding-bottom: 5px;
        }
        .map-layer-selector select {
            width: 100%;
            padding: 8px;
            background: #3E3E3E;
            border: 1px solid #8B4513;
            color: #D2B48C;
        }
        .map-layer-selector button {
            width: 100%;
            padding: 8px;
            background: #8B4513;
            color: white;
            border: none;
            cursor: pointer;
            font-weight: bold;
            transition: background 0.3s;
        }
        .map-layer-selector button:hover {
            background: #A0522D;
        }
        .historical-map {
            margin-top: 15px;
            padding: 10px;
            background: #3E3E3E;
            border: 1px solid #8B4513;
            border-radius: 5px;
        }
        .historical-map h3 {
            color: #F4A460;
            margin-top: 0;
            border-bottom: 1px dashed #8B4513;
            padding-bottom: 5px;
        }
        .historical-map iframe {
            width: 100%;
            height: 500px;
            border: none;
        }
    </style>
    <script>
        let selectedPoints = [];
        let selectedRoutes = [];

        function selectLocation(lat, lon) {
            selectedPoints.push([lat, lon]);
            fetch('/select_location', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/x-www-form-urlencoded',
                },
                body: `lat=${lat}&lon=${lon}`
            }).then(response => {
                if (response.ok) {
                    window.location.href = `/center_map?lat=${lat}&lon=${lon}`;
                }
            });
        }

        function toggleLocationList() {
            const locationList = document.querySelector('.location-list');
            if (locationList.style.display === 'none' || !locationList.style.display) {
                locationList.style.display = 'block';
            } else {
                locationList.style.display = 'none';
            }
        }

        function sendMessage() {
            const input = document.getElementById('chat-input');
            const message = input.value.trim();
            if (!message) return;

            const chatContainer = document.getElementById('chat-container');

            // Добавляем сообщение пользователя
            const userDiv = document.createElement('div');
            userDiv.className = 'chat-message user-message';
            userDiv.textContent = message;
            chatContainer.appendChild(userDiv);

            // Очищаем поле ввода
            input.value = '';

            // Прокручиваем чат вниз
            chatContainer.scrollTop = chatContainer.scrollHeight;

            // Отправляем запрос к серверу
            fetch('/chat', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/x-www-form-urlencoded',
                },
                body: `message=${encodeURIComponent(message)}`
            })
            .then(response => response.json())
            .then(data => {
                // Добавляем ответ бота
                const botDiv = document.createElement('div');
                botDiv.className = 'chat-message bot-message';
                botDiv.innerHTML = data.response;
                chatContainer.appendChild(botDiv);

                // Прокручиваем чат вниз
                chatContainer.scrollTop = chatContainer.scrollHeight;
            });
        }

        function saveRoute() {
            fetch('/save_route', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/x-www-form-urlencoded',
                },
                body: `route=${encodeURIComponent(JSON.stringify(selectedPoints))}`
            }).then(response => {
                if (response.ok) {
                    alert('Маршрут сохранен!');
                }
            });
        }

        function loadRoute() {
            fetch('/load_route')
            .then(response => response.json())
            .then(data => {
                if (data.route) {
                    selectedPoints = data.route;
                    alert('Маршрут загружен!');
                    // Обновляем карту с загруженным маршрутом
                    window.location.reload();
                }
            });
        }

        function shareOnTelegram() {
            const message = encodeURIComponent("Посмотрите мой маршрут поиска кладов!");
            window.open(`https://t.me/share/url?url=${encodeURIComponent(window.location.href)}&text=${message}`, '_blank');
        }

        function shareOnVK() {
            const message = encodeURIComponent("Посмотрите мой маршрут поиска кладов!");
            window.open(`https://vk.com/share.php?url=${encodeURIComponent(window.location.href)}&title=${message}`, '_blank');
        }

        function changeMapLayer() {
            const layer = document.getElementById('map-layer').value;
            fetch('/change_map_layer', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/x-www-form-urlencoded',
                },
                body: `layer=${encodeURIComponent(layer)}`
            }).then(response => {
                if (response.ok) {
                    alert(`Слой карты изменен на: ${layer}`);
                    window.location.reload();
                }
            });
        }

        function toggleOldMap() {
            const oldMap = document.getElementById('old-map-toggle').checked;
            fetch('/toggle_old_map', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/x-www-form-urlencoded',
                },
                body: `old_map=${oldMap}`
            }).then(response => {
                if (response.ok) {
                    window.location.reload();
                }
            });
        }

        document.addEventListener('DOMContentLoaded', function() {
            const locationList = document.querySelector('.location-list');
            if (locationList && locationList.children.length > 1) {
                locationList.style.display = 'block';
            }

            // Обработка нажатия Enter в чате
            document.getElementById('chat-input').addEventListener('keypress', function(e) {
                if (e.key === 'Enter') {
                    sendMessage();
                }
            });
        });

        document.addEventListener('click', function(event) {
            const locationList = document.querySelector('.location-list');
            const searchForm = document.querySelector('form');
            if (locationList && !locationList.contains(event.target) && !searchForm.contains(event.target)) {
                locationList.style.display = 'none';
            }
        });
    </script>
</head>
<body>
    <div id="map">
        {{ m._repr_html_()|safe }}
    </div>
    <div id="sidebar">
        <h2><i class="fas fa-skull-crossbones"></i> Карта старого копателя</h2>
        <form method="post" action="/search_location">
            <div class="form-group">
                <label for="query"><i class="fas fa-search"></i> Где будем копать?</label>
                <input type="text" id="query" name="query" required value="{{ query|default('', true) }}" placeholder="Введи название места...">
            </div>
            <button type="submit"><i class="fas fa-shovel"></i> Найти место</button>
        </form>

        {% if error %}
        <div class="error"><i class="fas fa-exclamation-triangle"></i> {{ error }}</div>
        {% endif %}

        {% if locations %}
        <div class="location-list">
            <h3><i class="fas fa-map-marked-alt"></i> Здесь может быть зарыт клад:</h3>
            {% for location in locations %}
            <div class="location-item" onclick="selectLocation({{ location.latitude }}, {{ location.longitude }})">
                <i class="fas fa-map-pin"></i> {{ location.address }}
            </div>
            {% endfor %}
        </div>
        {% endif %}

        {% if weather %}
        <div class="weather-info">
            <h3><i class="fas fa-thermometer-half"></i> Пиратский прогноз</h3>
            <div class="weather-temp">{{ weather.temp }}°C</div>
            <div class="weather-desc">{{ weather.description }}</div>
            <div class="weather-time">Обновлено: {{ weather.time }}</div>
        </div>
        {% endif %}

        {% if treasure_info %}
        <div class="treasure-info">
            <h3><i class="fas fa-coins"></i> Совет от копателя:</h3>
            <div class="expert-advice">
                {{ treasure_info|safe }}
            </div>
        </div>
        {% endif %}

        <div class="route-actions">
            <button onclick="saveRoute()"><i class="fas fa-save"></i> Сохранить маршрут</button>
            <button onclick="loadRoute()"><i class="fas fa-folder-open"></i> Загрузить маршрут</button>
        </div>

        <div class="historical-data">
            <h3><i class="fas fa-history"></i> Исторические данные</h3>
            <p>{{ historical_data }}</p>
        </div>

        <div class="social-share">
            <button onclick="shareOnTelegram()"><i class="fab fa-telegram"></i> Поделиться в Telegram</button>
            <button onclick="shareOnVK()"><i class="fab fa-vk"></i> Поделиться в VK</button>
        </div>

        <div class="map-layer-selector">
            <h3><i class="fas fa-layer-group"></i> Слои карты</h3>
            <select id="map-layer">
                <option value="satellite" {% if map_layer == 'satellite' %}selected{% endif %}>Спутник</option>
                <option value="topographic" {% if map_layer == 'topographic' %}selected{% endif %}>Топографическая</option>
                <option value="street" {% if map_layer == 'street' %}selected{% endif %}>Уличная</option>
            </select>
            <button onclick="changeMapLayer()"><i class="fas fa-sync-alt"></i> Изменить слой</button>

            <label>
                <input type="checkbox" id="old-map-toggle" onchange="toggleOldMap()" {% if old_map %}checked{% endif %}>
                Показать историческую карту
            </label>
        </div>

        <div class="historical-map">
            <h3><i class="fas fa-map"></i> Историческая карта</h3>
            <iframe
                width="100%"
                height="500px"
                frameborder="0"
                src="https://www.oldmapsonline.org/embed?bbox=45.6667,53.1959,50.1002,54.1959&zoom=12"
                allowfullscreen>
            </iframe>
        </div>

        <div id="chat-container"></div>
        <div style="display: flex; margin-top: 10px;">
            <input type="text" id="chat-input" placeholder="Спроси копателя о кладах...">
            <button id="send-btn" onclick="sendMessage()"><i class="fas fa-paper-plane"></i></button>
        </div>
    </div>
</body>
</html>
'''

# Глобальная переменная для хранения точек (в реальном приложении используйте БД)
selected_points = []
selected_routes = []

@app.route('/', methods=['GET', 'POST'])
def index():
    lat, lon = 53.1959, 50.1002  # Координаты по умолчанию (Самара)
    map_layer = session.get('map_layer', 'satellite')
    old_map = session.get('old_map', False)
    return render_template_string(
        HTML_TEMPLATE,
        m=create_map(lat, lon, selected_points, selected_routes, map_layer=map_layer, old_map=old_map),
        query=request.form.get('query', ''),
        map_layer=map_layer,
        old_map=old_map
    )

@app.route('/search_location', methods=['POST'])
def search_location_route():
    query = request.form.get('query', '').strip()
    map_layer = session.get('map_layer', 'satellite')
    old_map = session.get('old_map', False)

    if not query:
        return render_template_string(
            HTML_TEMPLATE,
            m=create_map(53.1959, 50.1002, selected_points, selected_routes, map_layer=map_layer, old_map=old_map),
            error="Эй, где будем искать-то? Введи название места!",
            query=query,
            map_layer=map_layer,
            old_map=old_map
        )

    locations = search_locations(query)
    if locations:
        return render_template_string(
            HTML_TEMPLATE,
            m=create_map(53.1959, 50.1002, selected_points, selected_routes, map_layer=map_layer, old_map=old_map),
            locations=locations,
            query=query,
            map_layer=map_layer,
            old_map=old_map
        )

    return render_template_string(
        HTML_TEMPLATE,
        m=create_map(53.1959, 50.1002, selected_points, selected_routes, map_layer=map_layer, old_map=old_map),
        error="Ничего не нашел. Может, опечатка? Или место слишком засекречено?",
        query=query,
        map_layer=map_layer,
        old_map=old_map
    )

@app.route('/select_location', methods=['POST'])
def select_location():
    lat = float(request.form.get('lat'))
    lon = float(request.form.get('lon'))
    selected_points.append((lat, lon))
    return '', 200

@app.route('/center_map', methods=['GET'])
def center_map():
    lat = float(request.args.get('lat'))
    lon = float(request.args.get('lon'))
    map_layer = session.get('map_layer', 'satellite')
    old_map = session.get('old_map', False)
    treasure_info = get_treasure_info(lat, lon)
    weather = get_weather(lat, lon)
    historical_data = get_historical_data(lat, lon)

    return render_template_string(
        HTML_TEMPLATE,
        m=create_map(lat, lon, selected_points, selected_routes, map_layer=map_layer, old_map=old_map),
        query=request.args.get('query', ''),
        treasure_info=treasure_info,
        weather=weather,
        historical_data=historical_data,
        map_layer=map_layer,
        old_map=old_map
    )

@app.route('/chat', methods=['POST'])
def chat():
    message = request.form.get('message', '').strip()

    if not message:
        return jsonify({"response": "Эй, ты ничего не написал!"})

    API_KEY = "___________"
    MODEL = "deepseek/deepseek-r1:free"

    prompt = f"""
    Ты — кладоискатель со стажем. Отвечай только на вопросы, связанные с кладоискательством.
       "{message}"

    Отвечай кратко (5-6 предложения), по делу. Если вопрос не о кладах — откажись отвечать."""

    headers = {
        "Authorization": f"Bearer {API_KEY}",
        "Content-Type": "application/json"
    }

    data = {
        "model": MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.9
    }

    try:
        with Session() as session:
            response = session.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers=headers,
                json=data,
                timeout=30
            )
            response.raise_for_status()
            result = response.json()
            response_text = result['choices'][0]['message']['content']
            return jsonify({"response": response_text})
    except Exception as e:
        print(f"Chat error: {e}")
        return jsonify({"response": "Чёрт- побери, связь барахлит... Попробуй позже."})

@app.route('/save_route', methods=['POST'])
def save_route():
    route = request.form.get('route')
    if route:
        session['route'] = json.loads(route)
        return '', 200
    return '', 400

@app.route('/load_route', methods=['GET'])
def load_route():
    route = session.get('route', [])
    return jsonify({"route": route})

@app.route('/change_map_layer', methods=['POST'])
def change_map_layer():
    layer = request.form.get('layer')
    session['map_layer'] = layer
    return '', 200

@app.route('/toggle_old_map', methods=['POST'])
def toggle_old_map():
    old_map = request.form.get('old_map') == 'true'
    session['old_map'] = old_map
    return '', 200

if __name__ == '__main__':
    app.run(debug=True, port=5001)
# Импортируем необходимые библиотеки
from flask import Flask, render_template_string, request, jsonify, session  # Flask для создания веб-приложения
import folium  # Для работы с картами
from geopy.geocoders import Nominatim  # Для геокодирования
import ssl  # Для работы с SSL
import certifi  # Для SSL сертификатов
from functools import lru_cache  # Для кеширования
import requests  # Для выполнения HTTP-запросов
from requests import Session  # Для сессий запросов
from bs4 import BeautifulSoup  # Для парсинга HTML
import re  # Для работы с регулярными выражениями
from datetime import datetime  # Для работы с датами и временем
import json  # Для работы с JSON
import os  # Для работы с операционной системой
from urllib.parse import urljoin  # Для работы с URL
import time  # Для работы со временем

# Создаем экземпляр Flask приложения
app = Flask(__name__)
app.secret_key = 'your_secret_key'  # Замените на ваш секретный ключ

# Фикс SSL проблем для geopy
ssl_context = ssl.create_default_context(cafile=certifi.where())

# Кешируем геокодирование для уменьшения запросов к 
@lru_cache(maxsize=100)
def search_locations(query):
    # Создаем экземпляр геокодера Nominatim
    geolocator = Nominatim(
        user_agent="map_application",
        ssl_context=ssl_context,
        timeout=20
    )
    try:
        # Ищем местоположения по запросу
        locations = geolocator.geocode(query, country_codes='RU', exactly_one=False)
        return locations if locations else []  # Возвращаем найденные местоположения или пустой список
    except Exception as e:
        print(f"Ошибка геокодирования: {e}")  # Выводим ошибку, если она есть
        return []  # Возвращаем пустой список в случае ошибки

# Создаем карту с заданными параметрами
def create_map(lat, lon, points=None, routes=None, zoom_start=15, map_layer='satellite', old_map=False):
    # Определяем URL для разных слоев карты
    tile_urls = {
        'satellite': 'https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}',
        'topographic': 'https://{s}.tile.opentopomap.org/{z}/{x}/{y}.png',
        'street': 'https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png'
    }

    # Создаем карту с заданными параметрами
    m = folium.Map(
        location=[lat, lon],
        zoom_start=zoom_start,
        tiles=tile_urls[map_layer],
        attr='Данные карты'
    )

    # Добавляем исторические карты, если включены
    if old_map:
        folium.TileLayer(
            tiles='https://maps.etomesto.ru/tiles/1880/{z}/{x}/{y}.png',
            attr='Историческая карта 1880 года',
            name='Историческая карта',
            overlay=True,
            control=True
        ).add_to(m)

    # Добавляем маркеры на карту, если есть точки
    if points:
        for point in points:
            folium.Marker(
                location=[point[0], point[1]],
                popup=f"Точка: {point[0]}, {point[1]}",
                icon=folium.Icon(color='red', icon='treasure-sign', prefix='fa')
            ).add_to(m)

    # Добавляем маршруты на карту, если есть
    if routes:
        folium.PolyLine(routes, color="blue", weight=2.5, opacity=1).add_to(m)

    # Добавляем контроль слоев на карту
    folium.LayerControl().add_to(m)

    return m  # Возвращаем созданную карту

# Получаем текущую температуру в пиратском стиле
def get_weather(lat, lon):
    try:
        # Формируем URL для запроса погоды
        url = f"https://.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}&current_weather=true"
        response = requests.get(url, timeout=20)  # Выполняем запрос
        data = response.json()  # Получаем данные в формате JSON

        # Проверяем, что данные содержат нужные поля
        if 'current_weather' not in data:
            return None

        temp = data['current_weather'].get('temperature')  # Получаем температуру
        if temp is None:
            return None

        # Пиратские описания температуры
        if temp < -10:
            description = "Лютый холод! Даже черти в аду кутаются!"
        elif -10 <= temp < 0:
            description = "Морозец, но для настоящего пиратского рома в самый раз!"
        elif 0 <= temp < 10:
            description = "Прохладно, как в трюме после шторма"
        elif 10 <= temp < 20:
            description = "Отличная погода для поиска сокровищ!"
        elif 20 <= temp < 30:
            description = "Жара, но для кладоискателя это не помеха!"
        else:
            description = "Адская жара! Где мой ром?!"

        return {
            'temp': temp,
            'description': description,
            'time': datetime.now().strftime("%d.%m.%Y %H:%M")  # Возвращаем текущее время
        }
    except Exception as e:
        print(f"Ошибка  погоды: {e}")  # Выводим ошибку, если она есть
        return None  # Возвращаем None в случае ошибки

# Парсим тематические сайты о кладах в указанном регионе
def parse_clad_sites(location_name):
    sites = [
        ("http://samara-clad.ru/", "div.post-content"),
        ("https://samarafishing.ru/board/index.php?topic=40553.0", "div.post"),
        ("https://mdrussia.ru/topic/89888-samarskaja-oblast/", "div.msg")
    ]

    results = []

    for url, selector in sites:
        try:
            response = requests.get(url, timeout=20)  # Выполняем запрос
            soup = BeautifulSoup(response.text, 'html.parser')  # Парсим HTML
            posts = soup.select(selector)  # Ищем посты по селектору

            for post in posts[:3]:  # Берем первые 3 записи
                text = post.get_text(separator=' ', strip=True)  # Получаем текст поста
                if location_name.lower() in text.lower():  # Проверяем, содержится ли название местности в тексте
                    # Очищаем текст от лишних пробелов и переносов
                    text = ' '.join(text.split())
                    results.append({
                        'source': url,
                        'text': text[:500] + '...' if len(text) > 500 else text  # Ограничиваем длину текста
                    })
                    if len(results) >= 3:  # Ограничиваемся 3 результатами
                        break
        except Exception as e:
            print(f"Ошибка парсинга {url}: {e}")  # Выводим ошибку, если она есть
            continue

    return results  # Возвращаем результаты

# Получаем информацию о возможных кладах в регионе через нейросеть
def get_treasure_info(lat, lon, radius=5):
    API_KEY = "____________"
    MODEL = "deepseek/deepseek-r1:free"

    # Сначала получаем название местности
    geolocator = Nominatim(user_agent="treasure_app", ssl_context=ssl_context)
    location = geolocator.reverse(f"{lat}, {lon}", language='ru')
    location_name = location.address if location else "этом районе"

    # Парсим сайты
    parsed_info = parse_clad_sites(location_name.split(',')[0])

    prompt = f"""
    Ты — кладоискатель со стажем! Отвечай только на вопросы, связанные с кладоискательством.
    Проанализируй регион {location_name} (координаты: {lat}, {lon}, радиус {radius} км) как эксперт:

    1. Историческая справка (коротко, только факты):
       - Какие народы здесь жили?
       - Были ли значимые события (войны, переселения)?
       - Где могли прятать ценности?

    2. Анализ местности для поиска кладов (3-4 конкретных совета):
       - Где искать (старые деревни, дороги, берега рек)?
       - На что обратить внимание (аномалии рельефа, старые карты)?

    3. Парсинг с тематических сайтов (уже выполнено, используй эту информацию):
       {parsed_info if parsed_info else "Нет данных с тематических сайтов"}

    Ответ дай в формате HTML, без лишних вступлений. Будь конкретным и критичным.
    Если данных действительно нет, скажи честно — не придумывай.
    """

    headers = {
        "Authorization": f"Bearer {API_KEY}",
        "Content-Type": "application/json"
    }

    data = {
        "model": MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.8
    }

    try:
        with Session() as session:
            response = session.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers=headers,
                json=data,
                timeout=30
            )
            response.raise_for_status()
            result = response.json()
            return result['choices'][0]['message']['content']  # Возвращаем ответ от нейросети
    except Exception as e:
        print(f"Ошибка API нейросети: {e}")  # Выводим ошибку, если она есть
        return "Не удалось получить информацию. Попробуйте позже."  # Возвращаем сообщение об ошибке

# Получаем исторические данные о местности
def get_historical_data(lat, lon):
    # Получаем название местности
    geolocator = Nominatim(user_agent="treasure_app", ssl_context=ssl_context)
    location = geolocator.reverse(f"{lat}, {lon}", language='ru')
    location_name = location.address.split(',')[0] if location else "этом районе"

    # Получаем данные из разных источников
    wikipedia_text = get_wikipedia_data(location_name)
    privolge_text = get_privolge_data(location_name)
    etomesto_text = get_etomesto_data(location_name)

    # Объединяем информацию
    combined_text = f"""
    Данные по региону {location_name}:

    Википедия:
    {wikipedia_text if wikipedia_text else "Нет данных из Википедии"}

    Privolge (исчезнувшие деревни):
    {privolge_text if privolge_text else "Нет данных с Privolge"}

    Etomesto (исторические карты):
    {etomesto_text if etomesto_text else "Нет данных с Etomesto"}
    """

    # Анализируем информацию с помощью нейросети
    analysis = analyze_with_ai(combined_text)

    return analysis  # Возвращаем анализ

# Получаем данные с Википедии по всем регионам
def get_wikipedia_data(location_name):
    try:
        base_url = "https://ru.wikipedia.org"
        search_url = f"{base_url}/w/index.php?search={location_name}"

        response = requests.get(search_url, timeout=20)  # Выполняем запрос
        soup = BeautifulSoup(response.text, 'html.parser')  # Парсим HTML

        # Ищем все ссылки на статьи, связанные с этим регионом
        links = []
        for link in soup.select('div.mw-search-result-heading a'):
            href = link.get('href')
            if href and not href.startswith('#'):
                links.append(urljoin(base_url, href))

        # Также проверяем категории
        for cat in soup.select('div.mw-search-results li a[href^="/wiki/Category:"]'):
            href = cat.get('href')
            if href:
                links.append(urljoin(base_url, href))

        # Убираем дубликаты
        links = list(set(links))

        # Собираем текст со всех найденных страниц
        all_text = []
        for link in links[:5]:  # Ограничиваемся 5 страницами для скорости
            try:
                time.sleep(1)  # Задержка между запросами
                page_response = requests.get(link, timeout=20)  # Выполняем запрос
                page_soup = BeautifulSoup(page_response.text, 'html.parser')  # Парсим HTML

                # Получаем основной текст статьи
                content = page_soup.find('div', {'id': 'mw-content-text'})
                if content:
                    # Удаляем таблицы и боковые панели
                    for element in content(['table', 'div.infobox', 'div.thumb']):
                        element.decompose()

                    text = content.get_text(separator=' ', strip=True)  # Получаем текст статьи
                    text = ' '.join(text.split())  # Удаляем лишние пробелы
                    all_text.append(text[:2000])  # Ограничиваем длину текста
            except Exception as e:
                print(f"Ошибка парсинга страницы Википедии {link}: {e}")  # Выводим ошибку, если она есть
                continue

        return ' '.join(all_text)  # Возвращаем собранный текст
    except Exception as e:
        print(f"Ошибка получения данных с Википедии: {e}")  # Выводим ошибку, если она есть
        return ""  # Возвращаем пустую строку в случае ошибки

# Получаем данные с сайта Privolge
def get_privolge_data(location_name):
    try:
        url = "https://privolge.ru/ischeznuvshie-derevni/"
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/58.0.3029.110 Safari/537.3'
        }
        response = requests.get(url, headers=headers, timeout=20)  # Выполняем запрос
        soup = BeautifulSoup(response.text, 'html.parser')  # Парсим HTML

        # Ищем все статьи, связанные с этим регионом
        articles = []
        for article in soup.find_all('article'):
            if location_name.lower() in article.get_text().lower():  # Проверяем, содержится ли название местности в тексте
                # Удаляем ненужные элементы
                for element in article(['script', 'style', 'iframe', 'img']):
                    element.decompose()

                text = article.get_text(separator=' ', strip=True)  # Получаем текст статьи
                text = ' '.join(text.split())  # Удаляем лишние пробелы
                articles.append(text[:2000])  # Ограничиваем длину текста

        return ' '.join(articles)  # Возвращаем собранный текст
    except Exception as e:
        print(f"Ошибка получения данных с Privolge: {e}")  # Выводим ошибку, если она есть
        return ""  # Возвращаем пустую строку в случае ошибки

# Получаем данные с сайта etomesto.ru
def get_etomesto_data(location_name):
    try:
        url = f"https://www.etomesto.ru/search/?query={location_name}"
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/58.0.3029.110 Safari/537.3'
        }
        response = requests.get(url, headers=headers, timeout=20)  # Выполняем запрос
        soup = BeautifulSoup(response.text, 'html.parser')  # Парсим HTML

        # Ищем информацию о картах
        maps_info = []
        for item in soup.select('div.search-item'):
            title = item.select_one('h3 a')
            if title and location_name.lower() in title.get_text().lower():  # Проверяем, содержится ли название местности в тексте
                desc = item.select_one('div.search-item-desc')
                if desc:
                    text = desc.get_text(separator=' ', strip=True)  # Получаем текст описания
                    text = ' '.join(text.split())  # Удаляем лишние пробелы
                    maps_info.append(text[:1000])  # Ограничиваем длину текста

        return ' '.join(maps_info)  # Возвращаем собранный текст
    except Exception as e:
        print(f"Ошибка получения данных с Etomesto: {e}")  # Выводим ошибку, если она есть
        return ""  # Возвращаем пустую строку в случае ошибки

# Анализируем текст с помощью нейросети
def analyze_with_ai(text):
    API_KEY = "_____________"
    MODEL = "deepseek/deepseek-r1:free"

    prompt = f"""
    Ты — кладоискатель со стажем! Проанализируй следующие данные и выдели важную информацию о возможных местах для поиска кладов:

    {text}

    Ответ дай в формате HTML, без лишних вступлений. Будь конкретным и критичным.
    Если данных действительно нет, скажи честно — не придумывай.
    """

    headers = {
        "Authorization": f"Bearer {API_KEY}",
        "Content-Type": "application/json"
    }

    data = {
        "model": MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.8
    }

    try:
        with Session() as session:
            response = session.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers=headers,
                json=data,
                timeout=30
            )
            response.raise_for_status()
            result = response.json()
            return result['choices'][0]['message']['content']  # Возвращаем ответ от нейросети
    except Exception as e:
        print(f"Ошибка API нейросети: {e}")  # Выводим ошибку, если она есть
        return "Не удалось получить информацию. Попробуйте позже."  # Возвращаем сообщение об ошибке

# HTML шаблон для отображения карты и интерфейса
HTML_TEMPLATE = '''
<!DOCTYPE html>
<html>
<head>
    <title>Карта старого копателя</title>
    <meta charset="utf-8">
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.0.0/css/all.min.css">
    <style>
        body {
            display: flex;
            margin: 0;
            padding: 0;
            font-family: 'Georgia', serif;
            background-color: #f5f5f5;
        }
        #map {
            width: 70%;
            height: 100vh;
            border-right: 3px solid #8B4513;
        }
        #sidebar {
            width: 30%;
            height: 100vh;
            background-color: #2E2E2E;
            color: #D2B48C;
            padding: 15px;
            overflow-y: auto;
            box-shadow: -2px 0 5px rgba(0,0,0,0.5);
        }
        .form-group {
            margin-bottom: 15px;
        }
        .form-group label {
            display: block;
            margin-bottom: 5px;
            font-weight: bold;
            color: #F4A460;
        }
        .form-group input {
            width: 100%;
            padding: 8px;
            background: #3E3E3E;
            border: 1px solid #8B4513;
            color: #D2B48C;
        }
        button {
            width: 100%;
            padding: 10px;
            margin-top: 10px;
            background: #8B4513;
            color: white;
            border: none;
            cursor: pointer;
            font-weight: bold;
            transition: background 0.3s;
        }
        button:hover {
            background: #A0522D;
        }
        .error {
            color: #FF6347;
            margin-top: 10px;
            padding: 5px;
            border-left: 3px solid #FF6347;
        }
        .location-list {
            margin-top: 15px;
            display: none;
            border: 1px solid #8B4513;
            border-radius: 5px;
        }
        .location-item {
            padding: 10px;
            border-bottom: 1px solid #8B4513;
            cursor: pointer;
            transition: background 0.2s;
        }
        .location-item:hover {
            background-color: #3E3E3E;
        }
        .treasure-info {
            margin-top: 20px;
            background: #3E3E3E;
            padding: 15px;
            border-radius: 5px;
            border: 1px solid #8B4513;
        }
        .treasure-info h3 {
            color: #F4A460;
            border-bottom: 1px dashed #8B4513;
            padding-bottom: 5px;
        }
        .expert-advice {
            font-size: 14px;
            line-height: 1.6;
        }
        .expert-advice h3 {
            color: #F4A460;
            margin-top: 10px;
        }
        .expert-advice p {
            margin: 8px 0;
            padding-left: 10px;
            border-left: 2px solid #8B4513;
        }
        .chat-message {
            margin: 10px 0;
            padding: 8px 12px;
            border-radius: 5px;
            max-width: 80%;
        }
        .user-message {
            background: #8B4513;
            margin-left: auto;
            color: white;
        }
        .bot-message {
            background: #3E3E3E;
            margin-right: auto;
            border: 1px solid #8B4513;
        }
        #chat-container {
            height: 200px;
            overflow-y: auto;
            margin-top: 15px;
            padding: 10px;
            background: #2E2E2E;
            border: 1px solid #8B4513;
            border-radius: 5px;
        }
        #chat-input {
            width: calc(100% - 70px);
            padding: 8px;
            background: #3E3E3E;
            border: 1px solid #8B4513;
            color: #D2B48C;
        }
        #send-btn {
            width: 60px;
            padding: 8px;
            margin-left: 5px;
        }
        .weather-info {
            margin-top: 15px;
            padding: 10px;
            background: #3E3E3E;
            border: 1px solid #8B4513;
            border-radius: 5px;
        }
        .weather-info h3 {
            color: #F4A460;
            margin-top: 0;
            border-bottom: 1px dashed #8B4513;
            padding-bottom: 5px;
        }
        .weather-temp {
            font-size: 24px;
            font-weight: bold;
            color: #F4A460;
            margin: 5px 0;
        }
        .weather-desc {
            font-style: italic;
            margin-bottom: 5px;
        }
        .weather-time {
            font-size: 12px;
            color: #A0A0A0;
            text-align: right;
        }
        .route-actions {
            margin-top: 15px;
            display: flex;
            justify-content: space-between;
        }
        .route-actions button {
            width: 48%;
            padding: 8px;
            background: #8B4513;
            color: white;
            border: none;
            cursor: pointer;
            font-weight: bold;
            transition: background 0.3s;
        }
        .route-actions button:hover {
            background: #A0522D;
        }
        .historical-data {
            margin-top: 15px;
            padding: 10px;
            background: #3E3E3E;
            border: 1px solid #8B4513;
            border-radius: 5px;
        }
        .historical-data h3 {
            color: #F4A460;
            margin-top: 0;
            border-bottom: 1px dashed #8B4513;
            padding-bottom: 5px;
        }
        .historical-data p {
            margin: 5px 0;
        }
        .social-share {
            margin-top: 15px;
            display: flex;
            justify-content: space-between;
        }
        .social-share button {
            width: 48%;
            padding: 8px;
            background: #8B4513;
            color: white;
            border: none;
            cursor: pointer;
            font-weight: bold;
            transition: background 0.3s;
        }
        .social-share button:hover {
            background: #A0522D;
        }
        .map-layer-selector {
            margin-top: 15px;
            padding: 10px;
            background: #3E3E3E;
            border: 1px solid #8B4513;
            border-radius: 5px;
        }
        .map-layer-selector h3 {
            color: #F4A460;
            margin-top: 0;
            border-bottom: 1px dashed #8B4513;
            padding-bottom: 5px;
        }
        .map-layer-selector select {
            width: 100%;
            padding: 8px;
            background: #3E3E3E;
            border: 1px solid #8B4513;
            color: #D2B48C;
        }
        .map-layer-selector button {
            width: 100%;
            padding: 8px;
            background: #8B4513;
            color: white;
            border: none;
            cursor: pointer;
            font-weight: bold;
            transition: background 0.3s;
        }
        .map-layer-selector button:hover {
            background: #A0522D;
        }
        .historical-map {
            margin-top: 15px;
            padding: 10px;
            background: #3E3E3E;
            border: 1px solid #8B4513;
            border-radius: 5px;
        }
        .historical-map h3 {
            color: #F4A460;
            margin-top: 0;
            border-bottom: 1px dashed #8B4513;
            padding-bottom: 5px;
        }
        .historical-map iframe {
            width: 100%;
            height: 500px;
            border: none;
        }
    </style>
    <script>
        let selectedPoints = [];
        let selectedRoutes = [];

        function selectLocation(lat, lon) {
            selectedPoints.push([lat, lon]);
            fetch('/select_location', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/x-www-form-urlencoded',
                },
                body: `lat=${lat}&lon=${lon}`
            }).then(response => {
                if (response.ok) {
                    window.location.href = `/center_map?lat=${lat}&lon=${lon}`;
                }
            });
        }

        function toggleLocationList() {
            const locationList = document.querySelector('.location-list');
            if (locationList.style.display === 'none' || !locationList.style.display) {
                locationList.style.display = 'block';
            } else {
                locationList.style.display = 'none';
            }
        }

        function sendMessage() {
            const input = document.getElementById('chat-input');
            const message = input.value.trim();
            if (!message) return;

            const chatContainer = document.getElementById('chat-container');

            // Добавляем сообщение пользователя
            const userDiv = document.createElement('div');
            userDiv.className = 'chat-message user-message';
            userDiv.textContent = message;
            chatContainer.appendChild(userDiv);

            // Очищаем поле ввода
            input.value = '';

            // Прокручиваем чат вниз
            chatContainer.scrollTop = chatContainer.scrollHeight;

            // Отправляем запрос к серверу
            fetch('/chat', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/x-www-form-urlencoded',
                },
                body: `message=${encodeURIComponent(message)}`
            })
            .then(response => response.json())
            .then(data => {
                // Добавляем ответ бота
                const botDiv = document.createElement('div');
                botDiv.className = 'chat-message bot-message';
                botDiv.innerHTML = data.response;
                chatContainer.appendChild(botDiv);

                // Прокручиваем чат вниз
                chatContainer.scrollTop = chatContainer.scrollHeight;
            });
        }

        function saveRoute() {
            fetch('/save_route', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/x-www-form-urlencoded',
                },
                body: `route=${encodeURIComponent(JSON.stringify(selectedPoints))}`
            }).then(response => {
                if (response.ok) {
                    alert('Маршрут сохранен!');
                }
            });
        }

        function loadRoute() {
            fetch('/load_route')
            .then(response => response.json())
            .then(data => {
                if (data.route) {
                    selectedPoints = data.route;
                    alert('Маршрут загружен!');
                    // Обновляем карту с загруженным маршрутом
                    window.location.reload();
                }
            });
        }

        function shareOnTelegram() {
            const message = encodeURIComponent("Посмотрите мой маршрут поиска кладов!");
            window.open(`https://t.me/share/url?url=${encodeURIComponent(window.location.href)}&text=${message}`, '_blank');
        }

        function shareOnVK() {
            const message = encodeURIComponent("Посмотрите мой маршрут поиска кладов!");
            window.open(`https://vk.com/share.php?url=${encodeURIComponent(window.location.href)}&title=${message}`, '_blank');
        }

        function changeMapLayer() {
            const layer = document.getElementById('map-layer').value;
            fetch('/change_map_layer', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/x-www-form-urlencoded',
                },
                body: `layer=${encodeURIComponent(layer)}`
            }).then(response => {
                if (response.ok) {
                    alert(`Слой карты изменен на: ${layer}`);
                    window.location.reload();
                }
            });
        }

        function toggleOldMap() {
            const oldMap = document.getElementById('old-map-toggle').checked;
            fetch('/toggle_old_map', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/x-www-form-urlencoded',
                },
                body: `old_map=${oldMap}`
            }).then(response => {
                if (response.ok) {
                    window.location.reload();
                }
            });
        }

        document.addEventListener('DOMContentLoaded', function() {
            const locationList = document.querySelector('.location-list');
            if (locationList && locationList.children.length > 1) {
                locationList.style.display = 'block';
            }

            // Обработка нажатия Enter в чате
            document.getElementById('chat-input').addEventListener('keypress', function(e) {
                if (e.key === 'Enter') {
                    sendMessage();
                }
            });
        });

        document.addEventListener('click', function(event) {
            const locationList = document.querySelector('.location-list');
            const searchForm = document.querySelector('form');
            if (locationList && !locationList.contains(event.target) && !searchForm.contains(event.target)) {
                locationList.style.display = 'none';
            }
        });
    </script>
</head>
<body>
    <div id="map">
        {{ m._repr_html_()|safe }}
    </div>
    <div id="sidebar">
        <h2><i class="fas fa-skull-crossbones"></i> Карта старого копателя</h2>
        <form method="post" action="/search_location">
            <div class="form-group">
                <label for="query"><i class="fas fa-search"></i> Где будем копать?</label>
                <input type="text" id="query" name="query" required value="{{ query|default('', true) }}" placeholder="Введи название места...">
            </div>
            <button type="submit"><i class="fas fa-shovel"></i> Найти место</button>
        </form>

        {% if error %}
        <div class="error"><i class="fas fa-exclamation-triangle"></i> {{ error }}</div>
        {% endif %}

        {% if locations %}
        <div class="location-list">
            <h3><i class="fas fa-map-marked-alt"></i> Здесь может быть зарыт клад:</h3>
            {% for location in locations %}
            <div class="location-item" onclick="selectLocation({{ location.latitude }}, {{ location.longitude }})">
                <i class="fas fa-map-pin"></i> {{ location.address }}
            </div>
            {% endfor %}
        </div>
        {% endif %}

        {% if weather %}
        <div class="weather-info">
            <h3><i class="fas fa-thermometer-half"></i> Пиратский прогноз</h3>
            <div class="weather-temp">{{ weather.temp }}°C</div>
            <div class="weather-desc">{{ weather.description }}</div>
            <div class="weather-time">Обновлено: {{ weather.time }}</div>
        </div>
        {% endif %}

        {% if treasure_info %}
        <div class="treasure-info">
            <h3><i class="fas fa-coins"></i> Совет от копателя:</h3>
            <div class="expert-advice">
                {{ treasure_info|safe }}
            </div>
        </div>
        {% endif %}

        <div class="route-actions">
            <button onclick="saveRoute()"><i class="fas fa-save"></i> Сохранить маршрут</button>
            <button onclick="loadRoute()"><i class="fas fa-folder-open"></i> Загрузить маршрут</button>
        </div>

        <div class="historical-data">
            <h3><i class="fas fa-history"></i> Исторические данные</h3>
            <p>{{ historical_data }}</p>
        </div>

        <div class="social-share">
            <button onclick="shareOnTelegram()"><i class="fab fa-telegram"></i> Поделиться в Telegram</button>
            <button onclick="shareOnVK()"><i class="fab fa-vk"></i> Поделиться в VK</button>
        </div>

        <div class="map-layer-selector">
            <h3><i class="fas fa-layer-group"></i> Слои карты</h3>
            <select id="map-layer">
                <option value="satellite" {% if map_layer == 'satellite' %}selected{% endif %}>Спутник</option>
                <option value="topographic" {% if map_layer == 'topographic' %}selected{% endif %}>Топографическая</option>
                <option value="street" {% if map_layer == 'street' %}selected{% endif %}>Уличная</option>
            </select>
            <button onclick="changeMapLayer()"><i class="fas fa-sync-alt"></i> Изменить слой</button>

            <label>
                <input type="checkbox" id="old-map-toggle" onchange="toggleOldMap()" {% if old_map %}checked{% endif %}>
                Показать историческую карту
            </label>
        </div>

        <div class="historical-map">
            <h3><i class="fas fa-map"></i> Историческая карта</h3>
            <iframe
                width="100%"
                height="500px"
                frameborder="0"
                src="https://www.oldmapsonline.org/embed?bbox=45.6667,53.1959,50.1002,54.1959&zoom=12"
                allowfullscreen>
            </iframe>
        </div>

        <div id="chat-container"></div>
        <div style="display: flex; margin-top: 10px;">
            <input type="text" id="chat-input" placeholder="Спроси копателя о кладах...">
            <button id="send-btn" onclick="sendMessage()"><i class="fas fa-paper-plane"></i></button>
        </div>
    </div>
</body>
</html>
'''

# Глобальная переменная для хранения точек (в реальном приложении используйте БД)
selected_points = []  # Список для хранения выбранных точек
selected_routes = []  # Список для хранения маршрутов

# Обработчик для главной страницы
@app.route('/', methods=['GET', 'POST'])
def index():
    lat, lon = 53.1959, 50.1002  # Координаты по умолчанию (Самара)
    map_layer = session.get('map_layer', 'satellite')  # Получаем выбранный слой карты из сессии
    old_map = session.get('old_map', False)  # Получаем флаг отображения исторической карты из сессии
    return render_template_string(
        HTML_TEMPLATE,
        m=create_map(lat, lon, selected_points, selected_routes, map_layer=map_layer, old_map=old_map),
        query=request.form.get('query', ''),
        map_layer=map_layer,
        old_map=old_map
    )

# Обработчик для поиска местоположений
@app.route('/search_location', methods=['POST'])
def search_location_route():
    query = request.form.get('query', '').strip()  # Получаем запрос из формы
    map_layer = session.get('map_layer', 'satellite')  # Получаем выбранный слой карты из сессии
    old_map = session.get('old_map', False)  # Получаем флаг отображения исторической карты из сессии

    if not query:
        return render_template_string(
            HTML_TEMPLATE,
            m=create_map(53.1959, 50.1002, selected_points, selected_routes, map_layer=map_layer, old_map=old_map),
            error="Эй, где будем искать-то? Введи название места!",
            query=query,
            map_layer=map_layer,
            old_map=old_map
        )

    locations = search_locations(query)  # Ищем местоположения по запросу
    if locations:
        return render_template_string(
            HTML_TEMPLATE,
            m=create_map(53.1959, 50.1002, selected_points, selected_routes, map_layer=map_layer, old_map=old_map),
            locations=locations,
            query=query,
            map_layer=map_layer,
            old_map=old_map
        )

    return render_template_string(
        HTML_TEMPLATE,
        m=create_map(53.1959, 50.1002, selected_points, selected_routes, map_layer=map_layer, old_map=old_map),
        error="Ничего не нашел. Может, опечатка? Или место слишком засекречено?",
        query=query,
        map_layer=map_layer,
        old_map=old_map
    )

# Обработчик для выбора местоположения
@app.route('/select_location', methods=['POST'])
def select_location():
    lat = float(request.form.get('lat'))  # Получаем широту из формы
    lon = float(request.form.get('lon'))  # Получаем долготу из формы
    selected_points.append((lat, lon))  # Добавляем точку в список выбранных точек
    return '', 200  # Возвращаем пустой ответ с кодом 200

# Обработчик для центрирования карты
@app.route('/center_map', methods=['GET'])
def center_map():
    lat = float(request.args.get('lat'))  # Получаем широту из аргументов запроса
    lon = float(request.args.get('lon'))  # Получаем долготу из аргументов запроса
    map_layer = session.get('map_layer', 'satellite')  # Получаем выбранный слой карты из сессии
    old_map = session.get('old_map', False)  # Получаем флаг отображения исторической карты из сессии
    treasure_info = get_treasure_info(lat, lon)  # Получаем информацию о кладах
    weather = get_weather(lat, lon)  # Получаем прогноз погоды
    historical_data = get_historical_data(lat, lon)  # Получаем исторические данные

    return render_template_string(
        HTML_TEMPLATE,
        m=create_map(lat, lon, selected_points, selected_routes, map_layer=map_layer, old_map=old_map),
        query=request.args.get('query', ''),
        treasure_info=treasure_info,
        weather=weather,
        historical_data=historical_data,
        map_layer=map_layer,
        old_map=old_map
    )

# Обработчик для чата
@app.route('/chat', methods=['POST'])
def chat():
    message = request.form.get('message', '').strip()  # Получаем сообщение из формы

    if not message:
        return jsonify({"response": "Эй, ты ничего не написал!"})  # Возвращаем ответ, если сообщение пустое

    API_KEY = "________________"
    MODEL = "deepseek/deepseek-r1:free"

    prompt = f"""
    Ты — кладоискатель со стажем. Отвечай только на вопросы, связанные с кладоискательством.
       "{message}"

    Отвечай кратко (5-6 предложения), по делу. Если вопрос не о кладах — откажись отвечать."""

    headers = {
        "Authorization": f"Bearer {API_KEY}",
        "Content-Type": "application/json"
    }

    data = {
        "model": MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.9
    }

    try:
        with Session() as session:
            response = session.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers=headers,
                json=data,
                timeout=30
            )
            response.raise_for_status()
            result = response.json()
            response_text = result['choices'][0]['message']['content']  # Получаем ответ от нейросети
            return jsonify({"response": response_text})  # Возвращаем ответ в формате JSON
    except Exception as e:
        print(f"Ошибка чата: {e}")  # Выводим ошибку, если она есть
        return jsonify({"response": "Чёрт- побери, связь барахлит... Попробуй позже."})  # Возвращаем сообщение об ошибке

# Обработчик для сохранения маршрута
@app.route('/save_route', methods=['POST'])
def save_route():
    route = request.form.get('route')  # Получаем маршрут из формы
    if route:
        session['route'] = json.loads(route)  # Сохраняем маршрут в сессии
        return '', 200  # Возвращаем пустой ответ с кодом 200
    return '', 400  # Возвращаем пустой ответ с кодом 400, если маршрут не передан

# Обработчик для загрузки маршрута
@app.route('/load_route', methods=['GET'])
def load_route():
    route = session.get('route', [])  # Получаем маршрут из сессии
    return jsonify({"route": route})  # Возвращаем маршрут в формате JSON

# Обработчик для изменения слоя карты
@app.route('/change_map_layer', methods=['POST'])
def change_map_layer():
    layer = request.form.get('layer')  # Получаем слой карты из формы
    session['map_layer'] = layer  # Сохраняем слой карты в сессии
    return '', 200  # Возвращаем пустой ответ с кодом 200

# Обработчик для переключения исторической карты
@app.route('/toggle_old_map', methods=['POST'])
def toggle_old_map():
    old_map = request.form.get('old_map') == 'true'  # Получаем флаг отображения исторической карты из формы
    session['old_map'] = old_map  # Сохраняем флаг отображения исторической карты в сессии
    return '', 200  # Возвращаем пустой ответ с кодом 200

# Запускаем приложение
if __name__ == '__main__':
    app.run(debug=True, port=5001)  # Запускаем приложение на порту 5001
