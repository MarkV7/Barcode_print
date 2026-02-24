import requests
from typing import Optional, Dict, Any
from datetime import datetime, timedelta, timezone
import time
import logging

class WildberriesFBSAPI:
    """
    Модуль для работы с API Wildberries FBS (Fulfillment by Seller).
    Документация: https://openapi.wildberries.ru/
    """
    BASE_URL = "https://marketplace-api.wildberries.ru"

    def __init__(self, api_token: str):
        self.api_token = api_token
        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": self.api_token
        })

    def get_orders(self, params: Optional[Dict[str, Any]] = None) -> Dict:
        """
        Получить список заказов FBS.
        params: параметры фильтрации (например, dateFrom, flag, etc)
        Возвращает: dict с данными заказов
        """
        url = f"{self.BASE_URL}/api/v3/orders/new"
        response = self.session.get(url, params=params)
        response.raise_for_status()
        return response.json()

    def get_info_about_orders(self, days_back: int = 10) -> Dict:
        """
        Метод возвращает информацию о сборочных заданиях без их актуального статуса.
        Можно получить данные за заданный период, максимум 30 календарных дней одним запросом.
        params: параметры фильтрации (например, dateFrom, flag, etc)
        Возвращает: dict с данными заказов
        """
        url = f"{self.BASE_URL}/api/v3/orders"
        current_time = int(time.time())
        # dateTo: Берем текущее время
        date_to = current_time
        # dateFrom: Отнимаем дни (days_back * 24 часа * 60 минут * 60 секунд)
        date_from = current_time - (days_back * 86400)
        # Основное тело запроса
        data = {
            "limit": 600,
            "next": 0,
            "dateFrom": date_from,
            "dateTo": date_to,
            }
        response = self.session.get(url, params=data)
        # Если снова будет ошибка, полезно видеть, что ответил сервер (там бывает описание)
        if response.status_code == 400:
            print(f"❌ Ошибка WB API 400: {response.text}")
        response.raise_for_status()
        return response.json()

    def get_status_orders(self, params: Dict) -> Dict:
        """
        Метод возвращает статусы сборочных заданий по их ID
        params: Dict со списком (целых чисел)
        Возвращает: dict с данными заказов
        """
        url = f"{self.BASE_URL}/api/v3/orders/status"
        response = self.session.post(url, json=params)
        # response.raise_for_status()
        return response.json()

    def get_supplies(self, params: Optional[Dict[str, Any]] = None) -> Dict:
        """
        Получить список поставок.
        Возвращает: dict с данными отгрузок
        """
        url = f"{self.BASE_URL}/api/v3/supplies"
        response = self.session.get(url, params=params)
        response.raise_for_status()
        return response.json()

    def get_orders_in_supply(self, supplyId:str) -> Dict:
        """
        Метод возвращает сборочные задания, закреплённые за поставкой.
        """
        url = f"{self.BASE_URL}/api/v3/supplies/{supplyId}/orders"
        response = self.session.get(url)
        response.raise_for_status()
        return response.json()

    def create_supply(self, name: str) -> dict:
        """
        Создать новую поставку (FBS).
        name: наименование поставки (строка, 1-128 символов)
        Возвращает: dict с результатом создания поставки
        """
        url = f"{self.BASE_URL}/api/v3/supplies"
        data = {"name": name}
        response = self.session.post(url, json=data)
        response.raise_for_status()
        return response.json()

    def get_stickers(self, order_ids, type="zplh", width=58, height=40) -> dict:
        """
        Получить стикеры для сборочных заданий (FBS).
        order_ids: список ID сборочных заданий (orders)
        type: формат стикера ("png", "svg", "zplv", "zplh")
        width: ширина стикера
        height: высота стикера
        Возвращает: dict с данными стикеров
        """
        url = f"{self.BASE_URL}/api/v3/orders/stickers"
        data = {"orders": order_ids,}
        response = self.session.post(url, params={"width": width, "height": height, "type": type}, json=data)
        response.raise_for_status()
        return response.json()

    def add_order_to_supply(self, supply_id: str, order_id: int) -> Dict:
        """
        Добавить сборочные задания в поставку.
        supply_id: ID поставки
        order_ids: список ID сборочных заданий (orders)
        Возвращает: dict с результатом
        """
        url = f"{self.BASE_URL}/api/v3/supplies/{supply_id}/orders/{order_id}"
        # url = f"{self.BASE_URL}/api/v3/supplies/{supply_id}/orders"
        # url = f'{self.BASE_URL}/api/marketplace/v3/supplies/{supply_id}/orders'
        # url = f"{self.BASE_URL}/api/v3/supplies/{supply_id}/orders"
        # data = {"orders": [order_id]}
        # response = self.session.patch(url, json=data)

        # Для этого метода тело запроса (json) больше не требуется
        response = self.session.patch(url)
        # Если заказ уже в другой поставке или возник конфликт,
        # добавим обработку, чтобы не «падать»
        if response.status_code == 409:
            logging.warning(f"Заказ {order_id} уже находится в поставке или возник конфликт.")
            return response

        response.raise_for_status()
        return response

    def close_supply_complete(self, supplyId: str) -> Dict:
        """
        Метод закрывает поставку и переводит все сборочные задания в ней в статус complete — в доставке.
        После закрытия поставки добавить новые сборочные задания к ней нельзя.
        supplyId: ID поставки
        Возвращает: dict с результатом
        """
        url = f"{self.BASE_URL}/api/v3/supplies/{supplyId}/deliver"
        response = self.session.patch(url)
        response.raise_for_status()
        return response.json()

    def assign_product_labeling(self, order_id:int, sgtins:Optional[Dict[str, Any]] = None):
        """
        Метод позволяет закрепить за сборочным заданием код маркировки Честный знак.
        Закрепить код маркировки можно только если в метаданных сборочного задания есть поле sgtin,
        а сборочное задание находится в статусе confirm. Вид передачи данных
        { "sgtins": [ "1234567890123456" ] }
        """
        url = f"{self.BASE_URL}/api/v3/orders/{order_id}/meta/sgtin"
        response = self.session.put(url, json=sgtins)
        response.raise_for_status()
        return response

    def get_orders_statuses(self, order_ids: list):
        """
        Получить актуальные статусы заказов (v3).
        Принимает список ID заказов (order_id).
        """
        url = f"{self.BASE_URL}/api/v3/orders/status"
        data = {"orders": order_ids}

        response = self.session.post(url, json=data)
        response.raise_for_status()

        # Ответ содержит список с полями: orderId, status, subStatus
        return response.json().get('orders', [])