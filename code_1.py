from flask import Flask, render_template_string, request, jsonify
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

app = Flask(__name__)

# Фикс SSL проблем для geopy
ssl_context = ssl.create_default_context(cafile=certifi.where())

# Кешируем геокодирование для уменьшения запросов к API
@lru_cache(maxsize=100)
def search_locations(query):
    geolocator = Nominatim(
        user_agent="map_application",
        ssl_context=ssl_context,
        timeout=10
    )
    try:
        locations = geolocator.geocode(query, country_codes='RU', exactly_one=False)
        return locations if locations else []
    except Exception as e:
        print(f"Geocoding error: {e}")
        return []

def create_map(lat, lon, points=None, zoom_start=15):
    m = folium.Map(
        location=[lat, lon],
        zoom_start=zoom_start,
        tiles='https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}',
        attr='Esri'
    )

    if points:
        for point in points:
            folium.Marker(
                location=[point[0], point[1]],
                popup=f"Point: {point[0]}, {point[1]}",
                icon=folium.Icon(color='red', icon='treasure-sign', prefix='fa')
            ).add_to(m)

    return m

def get_weather(lat, lon):
    """Получаем текущую температуру в пиратском стиле"""
    try:
        url = f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}&current_weather=true"
        response = requests.get(url, timeout=10)
        data = response.json()

        temp = data.get('current_weather', {}).get('temperature')
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
            response = requests.get(url, timeout=10)
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
    API_KEY = "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"
    MODEL = "deepseek/deepseek-r1:free"

    # Сначала получаем название местности
    geolocator = Nominatim(user_agent="treasure_app", ssl_context=ssl_context)
    location = geolocator.reverse(f"{lat}, {lon}", language='ru')
    location_name = location.address if location else "этом районе"

    # Парсим сайты
    parsed_info = parse_clad_sites(location_name.split(',')[0])

    prompt = f"""
    Ты — кладоискатель со стажем. Отвечай только на вопросы, связанные с кладоискательством.
    Твой стиль: любишь копать, знаешь все труды о древних монетах, истории, Труды П. Алабина в которых он описывает Самарскую область: в целом все труды связанных с кладами самарской области: где какие Бояри правили и как располагались боярские дома: где археологические памятники или где могли быть поселения калмыков: скифов или сарматов по, монголов географическому принципу. Используй всевозможные статьи и данные по археологическим находкам: информацию по историческим людям жившим здесь.

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

    Пример хорошего ответа:
    <div class="expert-advice">
        <h3>Саратовский уезд, 18 век</h3>
        <p>Здесь проходил соляной тракт — ищи тайники вдоль старой дороги.</p>
        <p>В 1920-х крестьяне прятали зерно — проверь овраги у бывших хуторов.</p>
        <p>На форуме samara-clad.ru пишут про находки монет у старой мельницы.</p>
    </div>
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
    </style>
    <script>
        function selectLocation(lat, lon) {
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

@app.route('/', methods=['GET', 'POST'])
def index():
    lat, lon = 53.1959, 50.1002  # Координаты по умолчанию (Самара)
    return render_template_string(
        HTML_TEMPLATE,
        m=create_map(lat, lon, selected_points),
        query=request.form.get('query', '')
    )

@app.route('/search_location', methods=['POST'])
def search_location_route():
    query = request.form.get('query', '').strip()
    if not query:
        return render_template_string(
            HTML_TEMPLATE,
            m=create_map(53.1959, 50.1002, selected_points),
            error="Эй, где будем искать-то? Введи название места!",
            query=query
        )

    locations = search_locations(query)
    if locations:
        return render_template_string(
            HTML_TEMPLATE,
            m=create_map(53.1959, 50.1002, selected_points),
            locations=locations,
            query=query
        )

    return render_template_string(
        HTML_TEMPLATE,
        m=create_map(53.1959, 50.1002, selected_points),
        error="Ничего не нашел. Может, опечатка? Или место слишком засекречено?",
        query=query
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
    treasure_info = get_treasure_info(lat, lon)
    weather = get_weather(lat, lon)

    return render_template_string(
        HTML_TEMPLATE,
        m=create_map(lat, lon, selected_points),
        query=request.args.get('query', ''),
        treasure_info=treasure_info,
        weather=weather
    )

@app.route('/chat', methods=['POST'])
def chat():
    message = request.form.get('message', '').strip()

    if not message:
        return jsonify({"response": "Эй, ты ничего не написал!"})

    API_KEY = "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"
    MODEL = "deepseek/deepseek-r1:free"

    prompt = f"""
    Ты — кладоискатель со стажем. Отвечай только на вопросы, связанные с кладоискательством.
    Твой стиль: грубоватый, любишь копать и костры, знаешь все труды о древних монетах, истории, Труды П. Алабина в которых он описывает Самарскую облась: в целом все труды связанных с кладами самарской области: где какие Бояри правили гдеи как располагались боярские дома: где археологические памятники или где могли быть поселения калмыков: скифов или сарматов по географическому принципу.

    Вот вопрос от пользователя:
    "{message}"

    Отвечай кратко (5-6 предложения), по делу. Если вопрос не о кладах — откажись отвечать.

    Пример хорошего ответа:
    "В Ищи Барский дом на возвышенности, прошурфи углы дома: проверяй возле больших ям: скорее всего там были Бани: походи вдоль Оврагов."
    """

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
                timeout=20
            )
            response.raise_for_status()
            result = response.json()
            response_text = result['choices'][0]['message']['content']
            return jsonify({"response": response_text})
    except Exception as e:
        print(f"Chat error: {e}")
        return jsonify({"response": "Чёрт, связь барахлит... Попробуй позже."})

if __name__ == '__main__':
    app.run(debug=True)
