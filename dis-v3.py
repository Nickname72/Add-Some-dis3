import sys
import os
import tempfile
import glob
import requests
import webbrowser
import json
import time
from datetime import datetime

from PyQt5 import QtCore, QtGui
from PyQt5.QtWidgets import (
    QApplication, QWidget, QLineEdit, QPushButton, QVBoxLayout, QHBoxLayout,
    QLabel, QFrame, QComboBox, QMessageBox, QInputDialog, QFileDialog,
    QTextEdit, QScrollArea, QSizePolicy, QCheckBox
)
from PyQt5.QtWebEngineWidgets import QWebEngineView
from PyQt5.QtCore import QThread, pyqtSignal, QTimer

from geopy.geocoders import Nominatim
import folium

# Спроба імпортувати pyqtgraph (міні-графік температури)
try:
    import pyqtgraph as pg
    HAS_PG = True
except ImportError:
    pg = None
    HAS_PG = False

# --- Додані бібліотеки для реального пошуку ---
from serpapi import GoogleSearch

# ---------------- CONFIGURATION & CONSTANTS ----------------
OPENWEATHERMAP_API_KEY = "1a61ee3445e9c64367cd8d49289388a1"
SERPAPI_KEY = "8bfd0e0df483c02d914bf8e04039982d0262ec61d980cd9daa344c766116f252"
TRANSLATE_URL = "https://libretranslate.com/translate"

DEFAULT_LOCATION = (50.4501, 30.5234)  # Київ, Україна
DEFAULT_ZOOM = 6
APP_USER_AGENT = "py_map_weather_app_v1.7_serpapi"
GEOLOCATOR_TIMEOUT = 10
WEATHER_API_TIMEOUT = 10
IP_API_URL = "http://ip-api.com/json/"

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__)) if '__file__' in locals() else os.getcwd()
BACKGROUNDS_DIR = os.path.join(SCRIPT_DIR, "backgrounds")
TEMP_DIR = tempfile.gettempdir()
MAP_TEMP_FILE = os.path.join(TEMP_DIR, "map_weather_app_map.html")
LOG_FILE = os.path.join(SCRIPT_DIR, "app_log.txt")

SUPPORTED_EXTS = [".jpg", ".jpeg", ".png", ".bmp", ".webp", ".gif"]
os.makedirs(BACKGROUNDS_DIR, exist_ok=True)

# файли налаштувань / улюблених
FAV_FILE = os.path.join(SCRIPT_DIR, "favorites.json")
SETTINGS_FILE = os.path.join(SCRIPT_DIR, "settings.json")

# Стилістичні константи
FONT_FAMILY = "Segoe UI, Arial, sans-serif"
COLOR_PRIMARY = "#1e90ff"
COLOR_HOVER = "#1c86ee"
COLOR_BACKGROUND = "rgba(8,12,16,0.6)"
COLOR_TEXT_LIGHT = "#d6d6d6"
COLOR_TEXT_WHITE = "#fff"


def log_message(msg: str):
    """Проста функція логування для відстеження подій у консолі та файлі."""
    timestamp = datetime.now().strftime("[%Y-%m-%d %H:%M:%S]")
    log_entry = f"{timestamp} {msg}"
    print(log_entry)
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(log_entry + "\n")
    except Exception as e:
        print(f"ERROR: Не вдалося записати в лог-файл: {e}")


# ---------------- HELPERS: BACKGROUNDS ----------------
def find_background_for(key: str):
    log_message(f"INFO: Шукаю фон для ключа: {key}")
    for ext in SUPPORTED_EXTS:
        filename_pattern = os.path.join(BACKGROUNDS_DIR, f"{key}*{ext}")
        files = glob.glob(filename_pattern)
        if files:
            log_message(f"INFO: Знайдено фон: {files[0]} для ключа '{key}'")
            return files[0]
    log_message(f"WARNING: Фон для ключа '{key}' не знайдено в '{BACKGROUNDS_DIR}'.")
    return None


BACKGROUND_IMAGES = {
    "clear": find_background_for("clear"),
    "clouds": find_background_for("clouds"),
    "rain": find_background_for("rain"),
    "storm": find_background_for("storm"),
    "snow": find_background_for("snow"),
}
BACKGROUND_IMAGES["default"] = BACKGROUND_IMAGES.get("clear") or next(
    (f for f in BACKGROUND_IMAGES.values() if f), None
)
if not BACKGROUND_IMAGES["default"]:
    log_message(
        f"WARNING: Жодного фонового зображення за замовчуванням не знайдено у '{BACKGROUNDS_DIR}'."
    )


def choose_background_by_description(desc: str):
    w = (desc or "").lower()
    if "thunder" in w or "storm" in w:
        return BACKGROUND_IMAGES.get("storm") or BACKGROUND_IMAGES.get("rain") or BACKGROUND_IMAGES["default"]
    if "rain" in w or "drizzle" in w or "shower" in w:
        return BACKGROUND_IMAGES.get("rain") or BACKGROUND_IMAGES["default"]
    if "snow" in w or "sleet" in w or "ice" in w:
        return BACKGROUND_IMAGES.get("snow") or BACKGROUND_IMAGES["default"]
    if "cloud" in w or "overcast" in w or "broken" in w or "scattered" in w or "mist" in w or "fog" in w:
        return BACKGROUND_IMAGES.get("clouds") or BACKGROUND_IMAGES["default"]
    if "clear" in w or "sun" in w:
        return BACKGROUND_IMAGES.get("clear") or BACKGROUND_IMAGES["default"]
    return BACKGROUND_IMAGES["default"]


# ---------------- HELPERS: MAPS & GEOLOCATION ----------------
def build_folium_map(lat, lon, zoom=DEFAULT_ZOOM, marker=True):
    log_message(f"INFO: Створення карти для Lat: {lat}, Lon: {lon}")
    m = folium.Map(location=[lat, lon], zoom_start=zoom, control_scale=True)

    folium.TileLayer("OpenStreetMap", name="Standard").add_to(m)
    folium.TileLayer("CartoDB positron", name="Light").add_to(m)
    folium.TileLayer("CartoDB dark_matter", name="Dark").add_to(m)

    folium.LayerControl().add_to(m)
    if marker:
        folium.Marker(
            [lat, lon],
            tooltip="Selected location",
            icon=folium.Icon(color="red", icon="info-sign"),
        ).add_to(m)
    m.add_child(folium.LatLngPopup())
    return m


def save_map_html(m, filename):
    try:
        m.save(filename)
        log_message(f"INFO: Карта збережена у {filename}")
    except Exception as e:
        log_message(f"ERROR: Не вдалося зберегти карту у {filename}: {e}")


def geocode_address(address: str):
    geolocator = Nominatim(user_agent=APP_USER_AGENT)
    try:
        loc = geolocator.geocode(address, exactly_one=True, timeout=GEOLOCATOR_TIMEOUT)
        if loc:
            log_message(f"INFO: Геокодування успішне: {loc.address}")
            return (loc.latitude, loc.longitude, loc.address)
    except Exception as e:
        log_message(f"ERROR: Помилка геокодування '{address}': {e}")
        return None
    return None


# ---------------- HELPERS: WEATHER ----------------
def fetch_weather(lat: float, lon: float, api_key: str, lang: str = "en"):
    url = (
        "https://api.openweathermap.org/data/2.5/weather"
        f"?lat={lat}&lon={lon}&units=metric&lang={lang}&appid={api_key}"
    )
    log_message(f"INFO: Запит погоди для ({lat}, {lon})")
    try:
        r = requests.get(url, timeout=WEATHER_API_TIMEOUT)
        r.raise_for_status()
        return r.json()
    except requests.exceptions.RequestException as e:
        log_message(f"ERROR: Помилка запиту погоди: {e}")
        if "401 Client Error" in str(e):
            raise ConnectionError("Помилка API: Невірний ключ OpenWeatherMap.") from e
        raise ConnectionError("Помилка підключення до служби погоди.") from e


def fetch_forecast(lat: float, lon: float, api_key: str, lang: str = "en"):
    """Отримання 5-денного прогнозу (крок 3 год)."""
    url = (
        "https://api.openweathermap.org/data/2.5/forecast"
        f"?lat={lat}&lon={lon}&units=metric&lang={lang}&appid={api_key}"
    )
    log_message(f"INFO: Запит прогнозу для ({lat}, {lon})")
    try:
        r = requests.get(url, timeout=WEATHER_API_TIMEOUT)
        r.raise_for_status()
        return r.json()
    except requests.exceptions.RequestException as e:
        log_message(f"ERROR: Помилка запиту прогнозу: {e}")
        return None


def weather_summary_text(data: dict, lang: str = "en"):
    w = data.get("weather", [{}])[0]
    main = data.get("main", {})
    wind = data.get("wind", {})
    sys_data = data.get("sys", {})

    name = data.get("name") or data.get("timezone", "Невідоме місце")
    country = sys_data.get("country", "")
    full_name = f"{name}, {country}" if country else name

    desc = w.get("description", "—").capitalize()
    temp = main.get("temp")
    feels = main.get("feels_like")
    hum = main.get("humidity")
    pressure = main.get("pressure")
    wind_spd = wind.get("speed")
    ts = data.get("dt")

    lines = []

    if lang == "uk":
        lines.append(f"📍 {full_name}")
        lines.append(f"🌤 {desc}")
        if temp is not None and feels is not None:
            lines.append(f"🌡 {temp:.1f} °C (відчувається як {feels:.1f} °C)")
        if hum is not None:
            lines.append(f"💧 Вологість: {hum}%")
        if pressure is not None:
            lines.append(f"🔽 Тиск: {pressure} hPa")
        if wind_spd is not None:
            lines.append(f"🍃 Вітер: {wind_spd:.1f} м/с")
        if ts:
            lines.append(
                "⏰ Оновлено: "
                + datetime.utcfromtimestamp(ts).strftime("%Y-%m-%d %H:%M UTC")
            )
    else:
        lines.append(f"📍 {full_name}")
        lines.append(f"🌤 {desc}")
        if temp is not None and feels is not None:
            lines.append(f"🌡 {temp:.1f} °C (feels like {feels:.1f} °C)")
        if hum is not None:
            lines.append(f"💧 Humidity: {hum}%")
        if pressure is not None:
            lines.append(f"🔽 Pressure: {pressure} hPa")
        if wind_spd is not None:
            lines.append(f"💨 Wind: {wind_spd:.1f} m/s")
        if ts:
            lines.append(
                "⏰ Updated: "
                + datetime.utcfromtimestamp(ts).strftime("%Y-%m-%d %H:%M UTC")
            )

    return "\n".join(lines), desc, temp


# ---------------- AI ASSISTANT IMPLEMENTATION ----------------
def translate_to_ukrainian(text: str) -> str:
    """Перекладає англійський текст українською через LibreTranslate API."""
    try:
        response = requests.post(
            TRANSLATE_URL,
            data={
                "q": text,
                "source": "en",
                "target": "uk",
                "format": "text",
            },
            timeout=8,
        )

        if response.status_code == 200:
            translated = response.json().get("translatedText", text)
            return translated
        else:
            return text
    except Exception:
        return text


def google_search_tool(query: str):
    """Реальний пошук через SerpAPI + автоматичний переклад результатів."""
    if not SERPAPI_KEY:
        log_message("ERROR: SerpAPI ключ не знайдено.")
        return [
            {
                "snippet": "❌ SerpAPI ключ не знайдено. Додайте його у змінну SERPAPI_KEY.",
                "source_title": "Система (Помилка API)",
            }
        ]

    try:
        params = {
            "engine": "google",
            "q": f"facts and history about {query}",
            "hl": "en",
            "gl": "us",
            "api_key": SERPAPI_KEY,
        }

        search = GoogleSearch(params)
        results = search.get_dict()

        snippets = []
        if "organic_results" in results:
            for item in results["organic_results"][:3]:
                snippet = item.get("snippet", "No description.")
                title = item.get("title", "No title")

                translated_snippet = translate_to_ukrainian(snippet)
                translated_title = translate_to_ukrainian(title)

                snippets.append(
                    {"snippet": translated_snippet, "source_title": translated_title}
                )

        if not snippets:
            snippets.append(
                {
                    "snippet": f"Інформація про {query.title()} не знайдена в результатах пошуку.",
                    "source_title": "Google Search",
                }
            )

        return snippets

    except Exception as e:
        log_message(f"ERROR: SerpAPI пошук провалився: {e}")
        return [
            {
                "snippet": f"Помилка під час пошуку через SerpAPI: {e}. Перевірте ключ та ліміти.",
                "source_title": "SerpAPI",
            }
        ]


def google_search_for_info(query: str):
    """Обгортка для пошуку та форматування результатів у HTML."""
    results = google_search_tool(query)

    if not results:
        return None

    summary = ""
    for item in results[:3]:
        summary += (
            f"<b>Джерело:</b> <span style='color:#76a9ff;'>{item['source_title']}</span><br>"
        )
        summary += f"{item['snippet']}<br><br>"

    return summary.strip()


class SearchWorker(QThread):
    """Потік для SerpAPI пошуку."""

    result_ready = pyqtSignal(str)
    error_occurred = pyqtSignal(str)

    def __init__(self, query: str, lang: str):
        super().__init__()
        self.query = query
        self.preferred_lang = lang

    def run(self):
        try:
            log_message(
                f"AI INFO: Запит до РЕАЛЬНОГО Інтернету (SerpAPI): '{self.query}'"
            )

            response = google_search_for_info(self.query)

            if response and response.strip():
                log_message(
                    f"AI SUCCESS: Інформація про {self.query} отримана з SerpAPI."
                )
                header = (
                    "<p style='color:#1abc9c; font-weight:bold;'>🤖 "
                    "AI-Асистент (WEB-Пошук SerpAPI):</p>"
                )
                response_text = header + response
            else:
                log_message(f"AI WARNING: Інформацію про '{self.query}' не знайдено.")
                header = (
                    "<p style='color:#e74c3c; font-weight:bold;'>Попередження "
                    "(Не знайдено):</p>"
                )
                response_text = (
                    f"{header}Не вдалося знайти детальної інформації про "
                    f"{self.query.title()} через SerpAPI."
                )

            self.result_ready.emit(response_text)

        except Exception as e:
            log_message(f"AI FATAL ERROR: Критична помилка у потоці пошуку: {e}")
            self.error_occurred.emit(
                f"Сталася критична помилка під час виконання запиту з Інтернету: {e}"
            )


class AICountryInfoDialog(QWidget):
    """Окреме діалогове вікно для AI-асистента з чатом."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("AI Асистент: WEB-Пошук (SerpAPI) 🌐")
        self.resize(650, 550)
        self.worker = None
        self._setup_ui()
        self._setup_style()
        self.setWindowFlags(QtCore.Qt.Window)
        self.parent_app = parent

    def _setup_ui(self):
        main_layout = QVBoxLayout(self)

        header = QLabel("🤖 AI-Консультант: Пошук в Інтернеті (SerpAPI)")
        header.setStyleSheet(
            "font-size:18px; font-weight:bold; color: #1abc9c; margin-bottom: 5px;"
        )
        main_layout.addWidget(header)

        self.chat_history = QTextEdit()
        self.chat_history.setReadOnly(True)
        self.chat_history.setFont(QtGui.QFont(FONT_FAMILY, 10))
        self.chat_history.setHtml(
            "<p style='color:#f1c40f; font-weight:bold;'>AI-асистент:</p>"
            "Привіт! Я ваш асистент. Я шукаю інформацію про <b>будь-яке місто "
            "чи країну світу</b> через <b>SerpAPI</b> та перекладаю її. "
            "Спробуйте ввести <b>Токіо, Париж</b> чи будь-що інше."
        )
        main_layout.addWidget(self.chat_history)

        self.query_input = QLineEdit()
        self.query_input.setPlaceholderText("Введіть назву країни або міста...")
        self.query_input.returnPressed.connect(self.send_query)

        self.send_btn = QPushButton("Надіслати запит")
        self.send_btn.clicked.connect(self.send_query)

        input_layout = QHBoxLayout()
        input_layout.addWidget(self.query_input, stretch=4)
        input_layout.addWidget(self.send_btn, stretch=1)
        main_layout.addLayout(input_layout)

    def _setup_style(self):
        self.setStyleSheet(
            f"""
            QWidget {{
                background-color: #2c3e50;
                color: {COLOR_TEXT_WHITE};
                font-family: {FONT_FAMILY};
            }}
            QLineEdit {{
                background: rgba(255,255,255,0.95);
                color:#111;
                border-radius:10px;
                padding:8px;
                border: 1px solid #bdc3c7;
            }}
            QPushButton {{
                background: #3498db;
                color:white;
                border:none;
                padding:10px;
                border-radius:8px;
                font-weight: bold;
            }}
            QPushButton:hover {{ background: #2980b9; }}
            QTextEdit {{
                background-color: #34495e;
                border: 2px solid #1abc9c;
                border-radius: 10px;
                padding: 10px;
                color: {COLOR_TEXT_WHITE};
            }}
            QTextEdit p {{ margin-bottom: 5px; }}
        """
        )

    def send_query(self):
        query = self.query_input.text().strip()
        if not query or (self.worker and self.worker.isRunning()):
            return

        self.chat_history.append(
            f"<p style='color:#1abc9c; font-weight:bold;'>Ви:</p>{query}"
        )
        self.query_input.clear()

        self.send_btn.setText("ШІ шукає в Інтернеті... ⏳")
        self.send_btn.setEnabled(False)

        current_lang = self.parent_app.current_lang if self.parent_app else "uk"

        self.worker = SearchWorker(query, current_lang)
        self.worker.result_ready.connect(self.handle_result)
        self.worker.error_occurred.connect(self.handle_error)
        self.worker.finished.connect(self.reset_ui)
        self.worker.start()

    def handle_result(self, result: str):
        self.chat_history.append(result)

    def handle_error(self, error: str):
        self.chat_history.append(
            f"<p style='color:#e74c3c; font-weight:bold;'>Помилка:</p>{error}"
        )

    def reset_ui(self):
        self.send_btn.setText("Надіслати запит")
        self.send_btn.setEnabled(True)


# ---------------- GUI MAIN APPLICATION ----------------
class MapWeatherApp(QWidget):
    """Основний клас додатку для відображення карти, погоди, прогнозу, графіка та улюблених."""

    def __init__(self):
        super().__init__()

        # базові стейти (можуть бути перезаписані load_settings)
        self.current_lat = DEFAULT_LOCATION[0]
        self.current_lon = DEFAULT_LOCATION[1]
        self.current_lang = "uk"
        self.map_tempfile = MAP_TEMP_FILE
        self._current_bg_path = BACKGROUND_IMAGES["default"]
        self.ai_assistant_dialog = None

        self.settings = {}
        self.favorites = []

        # тема
        self.is_dark_theme = True
        self.auto_theme_enabled = True

        # спочатку читаємо налаштування / улюблені
        self.load_settings()
        self.load_favorites()

        self.setWindowTitle("Map & Weather Explorer Pro 🗺️🌦️")
        self.resize(1200, 750)

        self._setup_ui()
        self._setup_style()
        self._setup_connections()
        self._setup_timers()

        # після створення UI – оновлюємо улюблені
        self.refresh_favorites_ui()

        self.update_map()
        self.update_weather_and_background()

    # ---------- SETTINGS & FAVORITES ----------
    def load_settings(self):
        """Завантаження settings.json (мова, тема, локація, авто-тема)."""
        if os.path.exists(SETTINGS_FILE):
            try:
                with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
                    self.settings = json.load(f)

                self.current_lang = self.settings.get("lang", self.current_lang)
                self.is_dark_theme = self.settings.get("dark_theme", self.is_dark_theme)
                self.auto_theme_enabled = self.settings.get(
                    "auto_theme", self.auto_theme_enabled
                )

                lat = self.settings.get("last_lat")
                lon = self.settings.get("last_lon")
                if lat is not None and lon is not None:
                    self.current_lat = lat
                    self.current_lon = lon

                log_message("INFO: Налаштування успішно завантажені.")
            except Exception as e:
                log_message(f"ERROR: Не вдалося завантажити налаштування: {e}")
                self.settings = {}
        else:
            self.settings = {}

    def save_settings(self):
        """Збереження налаштувань у settings.json."""
        self.settings["lang"] = self.current_lang
        self.settings["dark_theme"] = self.is_dark_theme
        self.settings["auto_theme"] = self.auto_theme_enabled
        self.settings["last_lat"] = self.current_lat
        self.settings["last_lon"] = self.current_lon
        try:
            with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
                json.dump(self.settings, f, ensure_ascii=False, indent=2)
            log_message("INFO: Налаштування збережено.")
        except Exception as e:
            log_message(f"ERROR: Не вдалося зберегти налаштування: {e}")

    def load_favorites(self):
        """Завантаження улюблених локацій з favorites.json."""
        if os.path.exists(FAV_FILE):
            try:
                with open(FAV_FILE, "r", encoding="utf-8") as f:
                    self.favorites = json.load(f)
                log_message("INFO: Улюблені локації завантажено.")
            except Exception as e:
                log_message(f"ERROR: Не вдалося завантажити favorites.json: {e}")
                self.favorites = []
        else:
            self.favorites = []

    def save_favorites(self):
        """Збереження улюблених локацій."""
        try:
            with open(FAV_FILE, "w", encoding="utf-8") as f:
                json.dump(self.favorites, f, ensure_ascii=False, indent=2)
            log_message("INFO: Улюблені локації збережено.")
        except Exception as e:
            log_message(f"ERROR: Не вдалося зберегти favorites.json: {e}")

    def refresh_favorites_ui(self):
        """Оновити комбобокс улюблених локацій."""
        if not hasattr(self, "fav_combo"):
            return
        self.fav_combo.clear()
        self.fav_combo.addItem("— Оберіть улюблене місто —", None)
        for fav in self.favorites:
            label = f"{fav['name']} ({fav['lat']:.2f}, {fav['lon']:.2f})"
            self.fav_combo.addItem(label, fav)

    # ---------- UI ----------
    def _setup_ui(self):
        # Background
        self.bg_label = QLabel(self)
        self.bg_label.setScaledContents(True)
        self.bg_label.lower()

        # Header label
        self.header_label = QLabel("Weather & Map Explorer")
        self.header_label.setAlignment(QtCore.Qt.AlignCenter)
        self.header_label.setObjectName("header_label")

        # Webview (Map)
        self.webview = QWebEngineView()
        self.webview.setMinimumHeight(350)

        # Search & controls
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Search city or address (e.g., London, Kyiv)")
        self.search_btn = QPushButton("Search 🔍")
        self.loc_btn = QPushButton("My Location 🏠")
        self.search_input.returnPressed.connect(self.on_search)

        self.lang_selector = QComboBox()
        self.lang_selector.addItem("English", "en")
        self.lang_selector.addItem("Українська", "uk")
        if self.current_lang == "uk":
            self.lang_selector.setCurrentIndex(1)
        else:
            self.lang_selector.setCurrentIndex(0)

        # Weather display
        self.temp_label = QLabel("—°C")
        self.temp_label.setObjectName("temp_label")
        self.desc_label = QLabel("")
        self.desc_label.setObjectName("desc_label")
        self.info_label = QLabel("")
        self.info_label.setWordWrap(True)
        self.info_label.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Expanding)

        # Forecast
        self.forecast_label = QLabel("Прогноз на 3 дні:")
        self.forecast_text = QLabel("")
        self.forecast_text.setWordWrap(True)

        # Міні-графік прогнозу температури
        if HAS_PG:
            self.forecast_plot = pg.PlotWidget()
            self.forecast_plot.setMinimumHeight(150)
            self.forecast_plot.showGrid(x=True, y=True)
            self.forecast_plot.setLabel("left", "Температура", "°C")
            self.forecast_plot.setLabel("bottom", "Точка прогнозу", "крок")
            self.forecast_plot_placeholder = None
        else:
            self.forecast_plot = None
            self.forecast_plot_placeholder = QLabel(
                "Міні-графік недоступний (pyqtgraph не встановлено)"
            )
            self.forecast_plot_placeholder.setWordWrap(True)

        # Favorites UI
        self.fav_combo = QComboBox()
        self.fav_combo.addItem("— Оберіть улюблене місто —", None)
        self.add_fav_btn = QPushButton("Додати в улюблені ⭐")

        # Theme controls
        self.auto_theme_checkbox = QCheckBox("Авто-тема за часом доби")
        self.auto_theme_checkbox.setChecked(self.auto_theme_enabled)

        self.theme_toggle_btn = QPushButton("Світла тема ☀️")
        self.theme_toggle_btn.setObjectName("theme_toggle_btn")

        # Action Buttons
        self.refresh_btn = QPushButton("Refresh Weather 🔄")
        self.open_browser_btn = QPushButton("Open Map in Browser 🌐")
        self.resize_map_btn = QPushButton("Resize Map Window 📏")
        self.change_bg_btn = QPushButton("Change Background 🖼️")
        self.export_btn = QPushButton("Експортувати звіт 📝")
        self.ai_assistant_btn = QPushButton("AI Асистент (WEB) 🌐")
        self.ai_assistant_btn.setObjectName("ai_assistant_btn")

        # Layouts
        top_layout = QVBoxLayout()
        top_layout.addWidget(self.header_label)

        search_layout = QHBoxLayout()
        search_layout.addWidget(self.search_input, stretch=6)
        search_layout.addWidget(self.search_btn)
        search_layout.addWidget(self.loc_btn)
        top_layout.addLayout(search_layout)
        top_layout.setSpacing(6)

        left_layout = QVBoxLayout()
        left_layout.addLayout(top_layout)
        left_layout.addWidget(self.webview)
        left_frame = QFrame()
        left_frame.setLayout(left_layout)
        left_frame.setObjectName("left_panel")

        right_layout = QVBoxLayout()
        right_layout.setContentsMargins(15, 15, 15, 15)

        # мова
        right_layout.addWidget(self.lang_selector)
        right_layout.addSpacing(10)

        # улюблені
        right_layout.addWidget(self.fav_combo)
        right_layout.addWidget(self.add_fav_btn)
        right_layout.addSpacing(10)

        right_layout.addWidget(QLabel("--- Current Weather Status ---"))
        right_layout.addWidget(self.temp_label)
        right_layout.addWidget(self.desc_label)
        right_layout.addWidget(self.info_label)

        right_layout.addSpacing(10)
        right_layout.addWidget(self.forecast_label)
        right_layout.addWidget(self.forecast_text)

        if HAS_PG:
            right_layout.addWidget(self.forecast_plot)
        else:
            right_layout.addWidget(self.forecast_plot_placeholder)

        right_layout.addStretch()

        # тема
        right_layout.addWidget(self.auto_theme_checkbox)
        right_layout.addWidget(self.theme_toggle_btn)

        # дії
        right_layout.addWidget(self.ai_assistant_btn)
        right_layout.addWidget(self.refresh_btn)
        right_layout.addWidget(self.open_browser_btn)
        right_layout.addWidget(self.resize_map_btn)
        right_layout.addWidget(self.change_bg_btn)
        right_layout.addWidget(self.export_btn)

        right_frame = QFrame()
        right_frame.setObjectName("glass")
        right_frame.setLayout(right_layout)

        # 🔽 Створюємо "ленту" з прокруткою для правої панелі
        self.right_scroll = QScrollArea()
        self.right_scroll.setWidgetResizable(True)
        self.right_scroll.setFrameShape(QFrame.NoFrame)
        self.right_scroll.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        self.right_scroll.setWidget(right_frame)

        main_layout = QHBoxLayout(self)
        main_layout.addWidget(left_frame, stretch=4)
        main_layout.addWidget(self.right_scroll, stretch=1)
        self.setLayout(main_layout)

    # ---------- STYLE ----------
    def update_theme_button_text(self):
        """Оновити текст кнопки теми."""
        if self.is_dark_theme:
            self.theme_toggle_btn.setText("Світла тема ☀️")
        else:
            self.theme_toggle_btn.setText("Темна тема 🌙")

    def _apply_dark_theme_styles(self):
        self.is_dark_theme = True
        self.update_theme_button_text()

        self.setStyleSheet(
            f"""
            QWidget {{ background: transparent; font-family: {FONT_FAMILY}; }}

            QFrame#glass {{
                background-color: {COLOR_BACKGROUND};
                border-radius: 18px;
            }}

            QFrame#left_panel {{ background: transparent; }}

            QLineEdit {{
                background: rgba(255,255,255,0.98);
                color:#111;
                border-radius:12px;
                padding:10px 12px;
                border: 1px solid #ccc;
            }}
            QLineEdit::placeholder {{ color:#888; }}

            QComboBox {{
                background: rgba(255,255,255,0.9);
                border-radius: 8px;
                padding: 6px;
                color: #333;
            }}

            QCheckBox {{
                color:{COLOR_TEXT_LIGHT};
            }}

            QPushButton {{
                background: {COLOR_PRIMARY};
                color:white;
                border:none;
                padding:10px 15px;
                border-radius:10px;
                font-weight: 600;
                margin-top: 5px;
            }}
            QPushButton:hover {{ background: {COLOR_HOVER}; }}

            QPushButton#ai_assistant_btn {{
                background: #e74c3c;
                margin-bottom: 15px;
            }}
            QPushButton#ai_assistant_btn:hover {{ background: #c0392b; }}

            QPushButton#theme_toggle_btn {{
                background: #9b59b6;
            }}
            QPushButton#theme_toggle_btn:hover {{
                background: #8e44ad;
            }}

            QLabel {{ color:{COLOR_TEXT_LIGHT}; font-size:16px; }}
            QLabel#temp_label {{ font-size:90px; font-weight:800; color:{COLOR_TEXT_WHITE}; margin-bottom: -15px; }}
            QLabel#desc_label {{ font-size:24px; color:#f1c40f; font-weight: 500; }}

            QLabel#header_label {{
                font-size:32px;
                font-weight:bold;
                color:#FFFFFF;
                margin-bottom:10px;
                padding: 10px;
                background-color: rgba(0,0,0,0.3);
                border-radius: 15px;
            }}
        """
        )

        app = QApplication.instance()
        if app:
            palette = QtGui.QPalette()
            palette.setColor(QtGui.QPalette.Window, QtGui.QColor(43, 47, 51))
            palette.setColor(QtGui.QPalette.WindowText, QtCore.Qt.white)
            palette.setColor(QtGui.QPalette.Base, QtGui.QColor(30, 30, 30))
            palette.setColor(QtGui.QPalette.Text, QtCore.Qt.white)
            palette.setColor(QtGui.QPalette.Button, QtGui.QColor(60, 63, 65))
            palette.setColor(QtGui.QPalette.ButtonText, QtCore.Qt.white)
            app.setPalette(palette)

    def _apply_light_theme_styles(self):
        self.is_dark_theme = False
        self.update_theme_button_text()

        self.setStyleSheet(
            f"""
            QWidget {{
                background-color: #f0f2f5;
                font-family: {FONT_FAMILY};
            }}

            QFrame#glass {{
                background-color: rgba(255,255,255,0.95);
                border-radius: 18px;
                border: 1px solid #d0d0d0;
            }}

            QFrame#left_panel {{
                background: transparent;
            }}

            QLineEdit {{
                background: #ffffff;
                color:#111;
                border-radius:10px;
                padding:8px 10px;
                border: 1px solid #cccccc;
            }}
            QLineEdit::placeholder {{ color:#999; }}

            QComboBox {{
                background: #ffffff;
                border-radius: 8px;
                padding: 6px;
                color: #333;
                border: 1px solid #cccccc;
            }}

            QCheckBox {{
                color:#333333;
            }}

            QPushButton {{
                background: #1976d2;
                color:white;
                border:none;
                padding:8px 12px;
                border-radius:10px;
                font-weight: 600;
                margin-top: 5px;
            }}
            QPushButton:hover {{ background: #1565c0; }}

            QPushButton#ai_assistant_btn {{
                background: #e53935;
                margin-bottom: 15px;
            }}
            QPushButton#ai_assistant_btn:hover {{ background: #c62828; }}

            QPushButton#theme_toggle_btn {{
                background: #8e24aa;
            }}
            QPushButton#theme_toggle_btn:hover {{
                background: #6a1b9a;
            }}

            QLabel {{ color:#333333; font-size:16px; }}
            QLabel#temp_label {{ font-size:90px; font-weight:800; color:#222222; margin-bottom: -15px; }}
            QLabel#desc_label {{ font-size:24px; color:#ff9800; font-weight: 500; }};

            QLabel#header_label {{
                font-size:32px;
                font-weight:bold;
                color:#1f2933;
                margin-bottom:10px;
                padding: 10px;
                background-color: rgba(255,255,255,0.9);
                border-radius: 15px;
                border: 1px solid #d0d0d0;
            }}
        """
        )

        app = QApplication.instance()
        if app:
            palette = QtGui.QPalette()
            palette.setColor(QtGui.QPalette.Window, QtGui.QColor(240, 242, 245))
            palette.setColor(QtGui.QPalette.WindowText, QtCore.Qt.black)
            palette.setColor(QtGui.QPalette.Base, QtGui.QColor(255, 255, 255))
            palette.setColor(QtGui.QPalette.Text, QtCore.Qt.black)
            palette.setColor(QtGui.QPalette.Button, QtGui.QColor(245, 245, 245))
            palette.setColor(QtGui.QPalette.ButtonText, QtCore.Qt.black)
            app.setPalette(palette)

    def _setup_style(self):
        # при старті застосовуємо тему з налаштувань
        if self.is_dark_theme:
            self._apply_dark_theme_styles()
        else:
            self._apply_light_theme_styles()

    def _setup_timers(self):
        # таймер авто-теми
        self.theme_timer = QTimer(self)
        self.theme_timer.timeout.connect(self.apply_theme_by_time)

        if self.auto_theme_enabled:
            self.theme_timer.start(60 * 1000)  # щохвилини
            self.apply_theme_by_time()

    def _setup_connections(self):
        self.search_btn.clicked.connect(self.on_search)
        self.loc_btn.clicked.connect(self.on_use_my_location)
        self.refresh_btn.clicked.connect(self.on_refresh)
        self.open_browser_btn.clicked.connect(self.open_map_in_browser)
        self.lang_selector.currentIndexChanged.connect(self.on_lang_change)
        self.resize_map_btn.clicked.connect(self.on_resize_map)
        self.change_bg_btn.clicked.connect(self.on_change_bg)
        self.ai_assistant_btn.clicked.connect(self.on_ai_assistant)
        self.export_btn.clicked.connect(self.on_export_report)

        self.theme_toggle_btn.clicked.connect(self.on_toggle_theme)
        self.auto_theme_checkbox.toggled.connect(self.on_auto_theme_toggled)

        self.add_fav_btn.clicked.connect(self.on_add_favorite)
        self.fav_combo.currentIndexChanged.connect(self.on_favorite_selected)

    # ---------- AUTO THEME ----------
    def apply_theme_by_time(self):
        """Автоматично обрати тему в залежності від часу доби."""
        if not self.auto_theme_enabled:
            return

        hour = datetime.now().hour
        # вдень (8–20) – світла, вночі – темна
        desired_dark = not (8 <= hour < 20)

        if desired_dark != self.is_dark_theme:
            if desired_dark:
                self._apply_dark_theme_styles()
            else:
                self._apply_light_theme_styles()
            log_message(f"INFO: Авто-тема змінена за часом доби (hour={hour}).")

    def on_auto_theme_toggled(self, checked: bool):
        """Увімкнення / вимкнення авто-теми."""
        self.auto_theme_enabled = checked
        if checked:
            self.theme_timer.start(60 * 1000)
            self.apply_theme_by_time()
        else:
            self.theme_timer.stop()
            log_message("INFO: Авто-тема вимкнена користувачем.")

    def on_toggle_theme(self):
        """Ручний перемикач теми. Вимикає авто-тему."""
        if self.auto_theme_enabled:
            self.auto_theme_checkbox.setChecked(False)

        if self.is_dark_theme:
            self._apply_light_theme_styles()
        else:
            self._apply_dark_theme_styles()

    # ---------- RESIZE / BACKGROUND ----------
    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.bg_label.resize(self.size())

        if self._current_bg_path and os.path.exists(self._current_bg_path):
            pix = QtGui.QPixmap(self._current_bg_path)
            if pix.isNull():
                log_message(
                    f"ERROR: QPixmap не змогла завантажити файл: {self._current_bg_path}."
                )
                return
            pix = pix.scaled(
                self.size(),
                QtCore.Qt.KeepAspectRatioByExpanding,
                QtCore.Qt.SmoothTransformation,
            )
            self.bg_label.setPixmap(pix)
            log_message(f"INFO: Фон оновлено з файлу: {self._current_bg_path}")
        elif self._current_bg_path:
            log_message(
                f"ERROR: Файл фону не існує за шляхом: {self._current_bg_path}"
            )

    # ---------- MAP & WEATHER ----------
    def update_map(self):
        m = build_folium_map(self.current_lat, self.current_lon)
        save_map_html(m, self.map_tempfile)
        self.webview.load(QtCore.QUrl.fromLocalFile(self.map_tempfile))

    def update_forecast_ui(self, forecast_data: dict):
        """Оновлення текстового блоку прогнозу на 3 дні."""
        try:
            lines = []
            used_dates = set()
            for item in forecast_data.get("list", []):
                dt_txt = item.get("dt_txt", "")
                if not dt_txt:
                    continue
                date_str = dt_txt.split(" ")[0]  # YYYY-MM-DD
                if date_str in used_dates:
                    continue
                used_dates.add(date_str)

                main = item.get("main", {})
                weather = (item.get("weather") or [{}])[0]
                desc = weather.get("description", "—").capitalize()
                temp = main.get("temp")

                pretty_date = datetime.strptime(
                    date_str, "%Y-%m-%d"
                ).strftime("%d.%m")
                lines.append(f"{pretty_date}: {temp:.1f} °C, {desc}")

                if len(lines) >= 3:
                    break

            self.forecast_text.setText("\n".join(lines) if lines else "—")
        except Exception as e:
            log_message(f"ERROR: Не вдалося оновити UI прогнозу: {e}")
            self.forecast_text.setText("Не вдалося завантажити прогноз.")

    def update_forecast_graph(self, forecast_data: dict):
        """Оновлює міні-графік прогнозу температури (якщо pyqtgraph доступний)."""
        if not HAS_PG or self.forecast_plot is None:
            return

        try:
            temps = []
            for item in forecast_data.get("list", [])[:16]:  # перші 16 точок (~2 доби)
                main = item.get("main", {})
                temp = main.get("temp")
                if temp is None:
                    continue
                temps.append(temp)

            self.forecast_plot.clear()
            if not temps:
                return

            x = list(range(len(temps)))
            self.forecast_plot.plot(x, temps, pen=pg.mkPen(width=2))

        except Exception as e:
            log_message(f"ERROR: Не вдалося оновити графік прогнозу: {e}")

    def update_weather_and_background(self):
        """Оновити погоду, фон, прогноз і графік для поточної локації."""
        try:
            data = fetch_weather(
                self.current_lat, self.current_lon, OPENWEATHERMAP_API_KEY, self.current_lang
            )
            summary, desc, temp = weather_summary_text(data, self.current_lang)

            self.info_label.setText(summary)
            self.temp_label.setText(f"{temp:.0f}°C" if temp is not None else "—°C")
            self.desc_label.setText(desc.capitalize() if desc else "")

            bg = choose_background_by_description(desc)
            if bg:
                self._current_bg_path = bg
                # примусово оновити фон
                self.resizeEvent(QtGui.QResizeEvent(self.size(), self.size()))

            # прогноз + графік
            forecast = fetch_forecast(
                self.current_lat, self.current_lon, OPENWEATHERMAP_API_KEY, self.current_lang
            )
            if forecast:
                self.update_forecast_ui(forecast)
                self.update_forecast_graph(forecast)
            else:
                self.forecast_text.setText("Не вдалося завантажити прогноз.")
                if HAS_PG and self.forecast_plot is not None:
                    self.forecast_plot.clear()

            # після успішного оновлення зберігаємо налаштування (локація)
            self.save_settings()

        except ConnectionError as e:
            self.info_label.setText(f"Помилка з'єднання: {e}")
            log_message(f"ERROR: {e}")
        except Exception as e:
            self.info_label.setText(f"Загальна помилка: {e}")
            log_message(f"FATAL: Непередбачена помилка: {e}")

    # ---------- ACTIONS ----------
    def on_refresh(self):
        log_message("ACTION: Оновлення погоди.")
        self.update_weather_and_background()

    def on_search(self):
        query = self.search_input.text().strip()
        if not query:
            return

        self.search_btn.setEnabled(False)
        self.search_btn.setText("Шукаємо...")

        res = geocode_address(query)

        self.search_btn.setEnabled(True)
        self.search_btn.setText("Search 🔍")

        if res:
            self.current_lat, self.current_lon, _ = res
            self.update_map()
            self.update_weather_and_background()
        else:
            QMessageBox.warning(
                self, "Not Found", "Не вдалося знайти місце за вашим запитом."
            )

    def on_use_my_location(self):
        try:
            r = requests.get(IP_API_URL, timeout=8).json()
            if r.get("status") == "success":
                self.current_lat, self.current_lon = r.get("lat"), r.get("lon")
                self.update_map()
                self.update_weather_and_background()
            else:
                raise Exception("Не вдалося отримати координати.")
        except Exception:
            QMessageBox.warning(
                self,
                "Error",
                "Не вдалося отримати поточне місцезнаходження за IP.",
            )

    def open_map_in_browser(self):
        if os.path.exists(self.map_tempfile):
            webbrowser.open(f"file:///{self.map_tempfile}")

    def on_lang_change(self, idx):
        self.current_lang = self.lang_selector.currentData()
        self.update_weather_and_background()

    def on_resize_map(self):
        w, ok1 = QInputDialog.getInt(
            self,
            "Map Width",
            "Введіть нову ширину (px):",
            self.webview.width(),
            400,
            1400,
            10,
        )
        if not ok1:
            return
        h, ok2 = QInputDialog.getInt(
            self,
            "Map Height",
            "Введіть нову висоту (px):",
            self.webview.height(),
            300,
            900,
            10,
        )
        if not ok2:
            return

        self.webview.setFixedSize(w, h)

    def on_change_bg(self):
        """Вибір користувацького фону та оновлення екрану."""
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Select Background Image",
            BACKGROUNDS_DIR,
            f"Images (*{' *'.join(SUPPORTED_EXTS)})",
        )
        if path:
            self._current_bg_path = path
            self.resizeEvent(QtGui.QResizeEvent(self.size(), self.size()))

    def on_ai_assistant(self):
        """Відкриває діалогове вікно AI-асистента."""
        if self.ai_assistant_dialog is None:
            self.ai_assistant_dialog = AICountryInfoDialog(parent=self)
        self.ai_assistant_dialog.show()

    def on_export_report(self):
        """Експортувати звіт про погоду + прогноз у TXT / HTML."""
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Зберегти звіт",
            SCRIPT_DIR,
            "Text Files (*.txt);;HTML Files (*.html)",
        )
        if not path:
            return

        summary_text = self.info_label.text()
        forecast_text = self.forecast_text.text()

        try:
            if path.lower().endswith(".html"):
                html = (
                    "<html><head><meta charset='utf-8'>"
                    "<title>Weather Report</title></head><body>"
                )
                html += "<h1>Поточна погода</h1><pre>" + summary_text + "</pre>"
                html += "<h2>Прогноз</h2><pre>" + forecast_text + "</pre>"
                html += "</body></html>"
                with open(path, "w", encoding="utf-8") as f:
                    f.write(html)
            else:
                with open(path, "w", encoding="utf-8") as f:
                    f.write("Поточна погода:\n")
                    f.write(summary_text + "\n\n")
                    f.write("Прогноз:\n")
                    f.write(forecast_text + "\n")
            QMessageBox.information(self, "Готово", "Звіт успішно збережено.")
        except Exception as e:
            QMessageBox.warning(self, "Помилка", f"Не вдалося зберегти файл: {e}")

    # ---------- FAVORITES ----------
    def on_add_favorite(self):
        """Додати поточну локацію в улюблені."""
        name, ok = QInputDialog.getText(
            self,
            "Нове улюблене",
            "Введіть назву для цієї локації (наприклад: Київ дім):",
        )
        if not ok or not name.strip():
            return

        fav = {"name": name.strip(), "lat": self.current_lat, "lon": self.current_lon}
        self.favorites.append(fav)
        self.save_favorites()
        self.refresh_favorites_ui()
        QMessageBox.information(self, "Готово", "Локацію додано в улюблені ⭐")

    def on_favorite_selected(self, idx):
        data = self.fav_combo.itemData(idx)
        if not data:
            return
        self.current_lat = data["lat"]
        self.current_lon = data["lon"]
        self.update_map()
        self.update_weather_and_background()

    # ---------- CLOSE ----------
    def closeEvent(self, event):
        """При закритті – зберігаємо налаштування."""
        self.save_settings()
        super().closeEvent(event)


# ---------------- MAIN EXECUTION ----------------
def main():
    log_message("INFO: Запуск програми.")

    app = QApplication(sys.argv)
    app.setStyle("Fusion")

    # Початкову палітру все одно перезапишуть стилі тем
    palette = QtGui.QPalette()
    palette.setColor(QtGui.QPalette.Window, QtGui.QColor(43, 47, 51))
    palette.setColor(QtGui.QPalette.WindowText, QtCore.Qt.white)
    app.setPalette(palette)

    window = MapWeatherApp()
    window.show()

    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
