from dotenv import load_dotenv
import os

# Загружаем переменные окружения из .env файла
load_dotenv()

# Настройки API. Получаем значения из .env
api_token = os.getenv('API_TOKEN_WB')
id_ozon = os.getenv('ID_OZON')
api_token_ozon = os.getenv('API_TOKEN_OZON')
PRINTER_HOST=os.getenv('PRINTER_HOST')