import requests
from typing import Optional, Dict, Any, List
import json
from datetime import datetime, timedelta, timezone

class OzonFBSAPI:
    """
    Модуль для работы с API Ozon FBS.
    Документация: https://docs.ozon.ru/api/seller
    """
    BASE_URL = "https://api-seller.ozon.ru"

    def __init__(self, client_id: str, api_key: str):
        self.client_id = client_id
        self.api_key = api_key
        self.session = requests.Session()
        self.session.headers.update({
            "Client-Id": self.client_id,
            "Api-Key": self.api_key,
            "Content-Type": "application/json"
        })

    def _request(self, method: str, path: str, data: Optional[Dict] = None, params: Optional[Dict] = None) -> Dict:
        """Внутренний метод для выполнения API запросов."""
        url = f"{self.BASE_URL}/{path}"
        try:
            if method == "GET":
                response = self.session.get(url, params=params)
            elif method == "POST":
                response = self.session.post(url, json=data, params=params)
            else:
                raise ValueError(f"Неподдерживаемый метод: {method}")

            response.raise_for_status()

            # Ozon может возвращать пустой ответ с кодом 200, если нечего возвращать
            if response.status_code == 204:
                return {"result": True}

            return response.json()
        except requests.exceptions.HTTPError as e:
            print(f"❌ Ошибка HTTP: {e.response.status_code} - {e.response.text}")
            raise
        except Exception as e:
            print(f"❌ Непредвиденная ошибка API: {e}")
            raise

    def get_orders(self, status: str = 'awaiting_packaging', days_back: int = 30, params: Optional[Dict] = None) -> Dict:
        """
        Получить список заказов FBS (отправлений).
        status: статус отправления для фильтрации (например, 'awaiting_packaging').
        days_back: сколько дней назад начинать поиск (обязателен для Ozon).
        params: дополнительные параметры для тела запроса.
        Возвращает: dict с данными заказов
        """
        path = "v3/posting/fbs/list"

        # 💡 ИСПРАВЛЕНИЕ ОШИБКИ: Ozon требует обязательный фильтр даты processed_at_from.
        # Вычисляем дату, отстоящую на days_back дней назад, в формате ISO 8601 (UTC).
        date_from = (datetime.now(timezone.utc) - timedelta(days=days_back)).isoformat().replace('+00:00', 'Z')

        # Основное тело запроса
        data = {
            "dir": "asc",
            "filter": {
                "since": date_from,  # required
                "to": datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z'),  # required
                "status": status,
            },
            "limit": 100,
            "offset": 0,
            "with": {
                "analytics_data": True,
                "barcodes": True,
                "financial_data": True,
                "translit": True
            }
        }

        # Если переданы дополнительные параметры, обновляем ими основное тело
        if params:
            data.update(params)

        response = self._request("POST", path, data=data)
        return response

    def get_status_orders(self,posting_number:str) -> Dict:
        """
        Получить детальную информацию и статус по конкретному отправлению Ozon FBS.
        posting_number: Номер отправления (обязателен).
        Возвращает: dict с детальными данными отправления.
        """
        if not posting_number or not isinstance(posting_number, str):
            raise ValueError("Номер отправления не может быть пустым.")
        path = 'v3/posting/fbs/get'
        data = {
          "posting_number": posting_number,
          "with": {
                "analytics_data": False,
                "barcodes": False,
                "financial_data": False,
                "legal_info": False,
                "product_exemplars": False,
                "related_postings": True,
                "translit": False
          }
        }
        response = self._request("POST", path, data=data)
        return response

    def set_status_to_assembly(self, posting_number: str, products: Optional[List[Dict]] = None) -> Dict:
        """
        Переводит отправление в статус "awaiting_deliver" (Собрано/В сборке).
        Использует метод API /v4/posting/fbs/ship.

        :param posting_number: Номер отправления (например, "12345678-0001-1").
        :param products: (Опционально) Список товаров в отправлении.
                         Формат: [{"sku": 123, "quantity": 1}, ...].
                         Если не передан, метод сам запросит состав отправления у Ozon.
        :return: Ответ API Ozon.
        """
        path = "v4/posting/fbs/ship"

        # 1. Если список товаров не передан, запрашиваем его у Ozon
        if not products:
            # self.logger.info(f"Состав отправления {posting_number} не передан, запрашиваем...")
            details = self.get_status_orders(posting_number)  # Используем ваш метод получения деталей

            # Проверка на ошибки получения
            if 'result' not in details:
                raise ValueError(f"Не удалось получить состав отправления {posting_number}")

            raw_products = details['result'].get('products', [])

            # Формируем список товаров для отправки (нужны только sku и quantity)
            products = [
                {"sku": item["sku"], "quantity": item["quantity"]}
                for item in raw_products
            ]

        if not products:
            raise ValueError(f"Отправление {posting_number} не содержит товаров или состав не получен.")

        # 2. Формируем тело запроса
        # Даже если коробка одна, мы обязаны обернуть товары в структуру packages
        data = {
            "posting_number": posting_number,
            "packages": [
                {
                    "products": products
                    # Примечание: В v4 поле называется "products", в старых версиях было "items".
                    # Для v4 структура: packages:List -> items:List (где items это продукт)
                    # Уточнение по доке Ozon v4: packages -> products -> [{sku, quantity}]
                }
            ],
            "with": {
                "additional_data": True
            }
        }

        # 3. Отправляем запрос
        # self.logger.info(f"Сборка отправления {posting_number} (1 место)...")
        return self._request("POST", path, data=data)

    def set_product_marking_code(self, posting_number: str, product_id: int, cis_code: str) -> Dict:
        """
        Установить код маркировки ("Честный Знак") для товара в сборочном задании.
        """
        path = "v2/fbs/posting/product/country/code/set"
        data = {
            "posting_number": posting_number,
            "products": [
                {
                    "product_id": product_id,
                    "cis": [cis_code]
                }
            ]
        }
        return self._request("POST", path, data=data)

    def get_stickers(self, posting_number: str) -> Dict:
        """
        Получить этикетку сборочного задания (фактически PDF/Base64 от Ozon).

        Внимание: Ozon API обычно возвращает PDF. Здесь мы возвращаем сырые данные,
        предполагая, что дальнейшая логика печати преобразует/обрабатывает их.
        """
        path = "/v2/posting/fbs/package-label"
        data = {
            "posting_number": [ posting_number ]
        }

        response = self._request("POST", path, params=data)
        return response