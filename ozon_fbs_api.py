import requests
from typing import Optional, Dict, Any, List
import json
from datetime import datetime, timedelta, timezone
import base64
import logging
# Создаем логгер для конкретного модуля
logger = logging.getLogger(__name__)

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

    # новый метод
    def _request_experience(self, method: str, path: str, data: Optional[Dict] = None, params: Optional[Dict] = None,
                 expect_json: bool = True) -> Any:
        # Убираем лишний слэш, если он есть в начале пути
        path = path.lstrip('/')
        url = f"{self.BASE_URL}/{path}"

        try:
            if method == "GET":
                response = self.session.get(url, params=params, timeout=15)
            else:
                response = self.session.post(url, json=data, params=params, timeout=15)

            # Если статус 4xx или 5xx, это вызовет исключение HTTPError
            response.raise_for_status()

            if expect_json:
                return response.json()
            return response

        except requests.exceptions.HTTPError as e:
            # Читаем детали ошибки из ответа сервера (там часто пишут причину)
            error_msg = f"HTTP Error {e.response.status_code}: {e.response.text}"
            logger.error(f"Ozon API Error на пути {path}: {error_msg}")
            # Возвращаем пустой словарь, чтобы GUI не падал при вызове .get()
            return {"error": error_msg, "status_code": e.response.status_code}

        except Exception as e:
            logger.error(f"Критическая ошибка запроса Ozon: {e}")
            return {"error": str(e)}

    def _request(self, method: str, path: str, data: Optional[Dict] = None, params: Optional[Dict] = None,
                 expect_json: bool = True) -> Any:
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
            # --- ИСПРАВЛЕННАЯ ЛОГИКА ---
            # Если JSON не ожидается (для получения PDF), возвращаем сырой объект ответа
            if not expect_json:
                return response

            # Ozon может возвращать пустой ответ с кодом 200, если нечего возвращать
            if response.status_code == 204 or not response.text:
                return {"result": True}

            # Если ожидаем JSON и ответ не пустой, пытаемся декодировать
            return response.json()

        except requests.exceptions.HTTPError as e:
            # Улучшенная обработка для HTTPError
            try:
                error_response = response.json()
                error_msg = json.dumps(error_response, ensure_ascii=False)
            except:
                error_msg = response.text

            raise Exception(f"Ошибка HTTP: {response.status_code}. Ответ: {error_msg}")
        except json.JSONDecodeError as e:
            # Этот блок может сработать, если expect_json=True, но получен не JSON
            raise Exception(
                f"Ошибка декодирования JSON. Код: {response.status_code}. Ответ: '{response.text[:100]}...'. Original Error: {e}")
        except Exception as e:
            raise Exception(f"Непредвиденная ошибка API: {e}")

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
        # 1. Определяем текущую дату/время в UTC
        now_utc = datetime.now(timezone.utc)
        # 2. Определяем дату/время на ЗАВТРА
        # Добавляем один день к текущему моменту
        tomorrow_utc = now_utc + timedelta(days=1)
        # Устанавливаем время "to" (до) - это ЗАВТРАШНЕЕ время (ключевое изменение)
        to_iso = tomorrow_utc.isoformat().replace('+00:00', 'Z')  # <-- ИЗМЕНЕНИЕ: now_utc заменен на tomorrow_utc
        # Основное тело запроса
        data = {
            "dir": "asc",
            "filter": {
                "since": date_from,  # required
                "to": to_iso,
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

    def get_unfulfilled_orders(self, days_back: int = 10) -> Dict:
        """
        Получает ВСЕ активные заказы (в сборке, ожидают отгрузки, арбитраж).
        Идеально подходит для Express, чтобы не терять заказы.
        """
        path = "v3/posting/fbs/unfulfilled/list"
        date_from = (datetime.now(timezone.utc) - timedelta(days=days_back)).isoformat().replace('+00:00', 'Z')

        data = {
            "dir": "ASC",
            "filter": {
                "cutoff_from": date_from  # Фильтр по времени окончания сборки
            },
            "limit": 100,
            "offset": 0,
            "with": {
                "analytics_data": True,
                "barcodes": True,
                "financial_data": True
            }
        }
        return self._request("POST", path, data=data)

    def get_order_transaction_info(self, posting_number: str, days_back: int = 30) -> Dict[str, Any]:
        """
        Получает финансовую информацию по конкретному отправлению через список транзакций.
        Позволяет узнать цену, за которую покупатель фактически приобрел товар.
        """
        path = "v3/finance/transaction/list"

        # Определяем временной интервал для поиска транзакций
        to_date = datetime.now(timezone.utc)
        from_date = to_date - timedelta(days=days_back)

        data = {
            "filter": {
                "date": {
                    "from": from_date.strftime('%Y-%m-%dT%H:%M:%SZ'),
                    "to": to_date.strftime('%Y-%m-%dT%H:%M:%SZ')
                },
                "posting_number": posting_number,
                "transaction_type": "all"
            },
            "page": 1,
            "page_size": 100
        }

        return self._request("POST", path, data=data)

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
                {"product_id": item["sku"],
                 "quantity": item["quantity"]}
                for item in raw_products
            ]

        if not products:
            raise ValueError(f"Отправление {posting_number} не содержит товаров или состав не получен.")

        # 2. Формируем тело запроса
        # Даже если коробка одна, мы обязаны обернуть товары в структуру packages
        print(products)
        data = {
            "packages": [
                {
                    "products": products
                    # Примечание: В v4 поле называется "products", в старых версиях было "items".
                    # Для v4 структура: packages:List -> items:List (где items это продукт)
                    # Уточнение по доке Ozon v4: packages -> products -> [{sku, quantity}]
                }
            ],
            "posting_number": posting_number,
            "with": {
                "additional_data": True
            }
        }

        # 3. Отправляем запрос
        # self.logger.info(f"Сборка отправления {posting_number} (1 место)...")
        return self._request("POST", path, data=data)


    def set_product_marking_code(self, posting_number: str, cis_code: list,
                                 product_id: Optional[int] = None) -> Dict:
        """
        Установить код маркировки ("Честный Знак") для товара в сборочном задании.

        :param posting_number: Номер отправления.
        :param cis_code: Код маркировки (полная строка).
        :param product_id: ID товара (sku) Ozon. Если None, метод попытается определить его автоматически.
        """
        #
        # # 1. Автоматическое определение product_id, если он не передан
        # if product_id is None:
        #     # Получаем детали отправления
        #     details = self.get_status_orders(posting_number)
        #     products = details.get('result', {}).get('products', [])
        #
        #     if not products:
        #         raise ValueError(f"Не удалось получить товары для отправления {posting_number}")
        #
        #     # Логика автовыбора:
        #     # Если товар в отправлении ВСЕГО ОДИН, берем его ID.
        #     if len(products) == 1:
        #         product_id = products[0].get('sku')  # В Ozon FBS sku обычно равен product_id
        #     else:
        #         # Если товаров много, мы не знаем, к какому привязать КМ без дополнительных данных.
        #         # В этом случае product_id должен быть передан явно.
        #         raise ValueError(
        #             f"В отправлении {posting_number} несколько товаров. "
        #             "Необходимо явно передать product_id для маркировки."
        #         )

        if not product_id:
            raise ValueError("Не удалось определить product_id (sku) товара.")

        # 2. Формирование запроса
        path = "v2/fbs/posting/product/country/code/set"
        data = {
            "posting_number": posting_number,
            "products": [
                {
                    "product_id": int(product_id),  # API требует int
                    "cis": cis_code
                }
            ]
        }
        return self._request("POST", path, data=data)

    def get_stickers(self, posting_number: str) -> str:
        """
        Получить этикетку сборочного задания (Base64 PDF).
        Использует v3 API, возвращающий JSON.
        """
        path = "/v2/posting/fbs/package-label"
        data = {
            "posting_number": [ posting_number ], # В v2 API это список
        }
        response = self._request("POST", path, data=data, expect_json = False)
        # Ozon возвращает Base64 строку в поле 'pdf'
        label_data_base64 = base64.b64encode(response.content).decode('utf-8')

        return label_data_base64  # Возвращаем Base64 строку

    def get_posting_info(self, posting_number: str) -> Dict:
        """
        Получить подробную информацию о конкретном отправлении (v3).
        Позволяет узнать статус выкупа и доставки.
        """
        path = "v3/posting/fbs/get"
        data = {"posting_number": posting_number}
        return self._request("POST", path, data=data)

    def create_orders_report(self, date_from: str, date_to: str) -> Dict:
        """
        Запрос на создание отчета о реализации (postings).
        Документация: https://docs.ozon.ru/api/seller/#operation/ReportAPI_ReportPostingCreate
        """
        # Был ошибочный путь v1/report/order/create
        path = "v1/report/postings/create"
        data = {
            "filter": {
                "processed_at_from": f"{date_from}T00:00:00Z",
                "processed_at_to": f"{date_to}T23:59:59Z",
                "delivery_schema": ["fbs"], # Указываем схему работы
                "status": "all"
            },
            "language": "DEFAULT"
        }
        return self._request("POST", path, data=data)

    def get_report_info(self, report_code: str) -> Dict:
        """
        Проверка статуса отчета и получение ссылки на файл.
        Документация: https://docs.ozon.ru/api/seller/#operation/ReportAPI_ReportInfo
        """
        path = "v1/report/info"
        data = {"code": report_code}
        return self._request("POST", path, data=data)

    def get_returns_list_v1_old(self, schema: str = 'FBS', days: int = 30) -> List[Dict[str, Any]]:
        """
        Метод для получения информации о возвратах FBO и FBS (v1).
        https://docs.ozon.ru/api/seller/#operation/returnsList
        """
        path = "v1/returns/list"

        # Расчет временного диапазона
        now = datetime.now(timezone.utc)
        date_from = now - timedelta(days=days)

        # Форматирование дат строго по ISO 8601 (например, 2024-03-19T10:00:00Z)
        time_from_str = date_from.strftime('%Y-%m-%dT%H:%M:%SZ')
        time_to_str = now.strftime('%Y-%m-%dT%H:%M:%SZ')

        # Формируем payload согласно документации v1
        payload = {
            "filter": {
                "logistic_return_date": {
                    "time_from": time_from_str,
                    "time_to": time_to_str
                },
                "return_schema": schema.upper()  # 'FBS' или 'FBO'
            },
            "limit": 500,
            "last_id": 0
        }

        try:
            logger.info(f"Ozon API: Запрос возвратов {schema} через {path} за {days} дн.")

            # Используем ваш стандартный метод _request
            response = self._request("POST", path, data=payload)

            # В v1 данные обычно лежат сразу в корне ответа в ключе 'returns'
            data = response.json() if hasattr(response, 'json') else response

            returns_list = data.get('returns', [])

            logger.info(f"Ozon API: Найдено возвратов: {len(returns_list)}")
            return returns_list

        except Exception as e:
            logger.error(f"Ошибка в get_returns_list_v1: {e}")
            if hasattr(e, 'response') and e.response is not None:
                logger.error(f"Детали ответа сервера: {e.response.text}")
            return []

    def get_returns_list_v1_old(self, schema: str = 'FBS', days: int = 90) -> List[Dict[str, Any]]:
        """
        Метод v1 для получения информации о возвратах.
        Преобразует вложенную структуру API в плоский список для БД.
        """
        path = "v1/returns/list"
        now = datetime.now(timezone.utc)
        date_from = now - timedelta(days=days)

        payload = {
            "filter": {
                "logistic_return_date": {
                    "time_from": date_from.strftime('%Y-%m-%dT%H:%M:%SZ'),
                    "time_to": now.strftime('%Y-%m-%dT%H:%M:%SZ')
                },
                "return_schema": schema.upper()
            },
            "limit": 500,
            "last_id": 0
        }

        try:
            logger.info(f"Ozon API: Запрос возвратов {schema} за {days} дн.")
            response = self._request("POST", path, data=payload)
            data = response.json() if hasattr(response, 'json') else response

            raw_returns = data.get('returns', [])
            processed_returns = []

            for item in raw_returns:
                # Извлекаем SKU и Номер отправления правильно
                # В v1 артикул (offer_id) находится внутри product
                product_data = item.get('product', {})

                processed_returns.append({
                    'posting_number': item.get('posting_number'),
                    'sku': product_data.get('sku'),
                    'return_date': item.get('logistic', {}).get('return_date'),
                    'status_name': item.get('visual', {}).get('status', {}).get('display_name'),
                    'quantity': product_data.get('quantity')
                })

            logger.info(f"Ozon API: Обработано {len(processed_returns)} записей.")
            return processed_returns

        except Exception as e:
            logger.error(f"Ошибка в get_returns_list_v1: {e}")
            return []

    def get_returns_list_v1(self, schema: str = 'FBS', days: int = 90) -> List[Dict[str, Any]]:
        """
        Метод v1 для получения информации о возвратах.
        Поддерживает пагинацию (last_id), чтобы обходить лимит в 500 записей.
        """
        path = "v1/returns/list"
        now = datetime.now(timezone.utc)
        date_from = now - timedelta(days=days)

        time_from_str = date_from.strftime('%Y-%m-%dT%H:%M:%SZ')
        time_to_str = now.strftime('%Y-%m-%dT%H:%M:%SZ')

        processed_returns = []
        last_id = 0
        has_next = True

        logger.info(f"Ozon API: Запрос возвратов {schema.upper()} за {days} дн. (с пагинацией)")

        while has_next:
            payload = {
                "filter": {
                    "logistic_return_date": {
                        "time_from": time_from_str,
                        "time_to": time_to_str
                    },
                    "return_schema": schema.upper()
                },
                "limit": 500,
                "last_id": last_id
            }

            try:
                response = self._request("POST", path, data=payload)
                data = response.json() if hasattr(response, 'json') else response

                raw_returns = data.get('returns', [])

                for item in raw_returns:
                    product_data = item.get('product', {})

                    processed_returns.append({
                        'posting_number': item.get('posting_number'),
                        'sku': product_data.get('sku'),
                        'return_date': item.get('logistic', {}).get('return_date'),
                        'status_name': item.get('visual', {}).get('status', {}).get('display_name'),
                        'quantity': product_data.get('quantity', 1)  # Берем кол-во, по умолчанию 1
                    })

                has_next = data.get('has_next', False)

                # Для следующего запроса берем ID последней записи в текущем ответе
                if raw_returns:
                    last_id = raw_returns[-1].get('id')
                else:
                    has_next = False

            except Exception as e:
                logger.error(f"Ошибка в get_returns_list_v1 (last_id={last_id}): {e}")
                break

        logger.info(f"Ozon API: Всего обработано {len(processed_returns)} записей для {schema}.")
        return processed_returns