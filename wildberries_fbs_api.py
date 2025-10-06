import requests
from typing import Optional, Dict, Any

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

    def get_supplies(self, params: Optional[Dict[str, Any]] = None) -> Dict:
        """
        Получить список поставок.
        Возвращает: dict с данными отгрузок
        """
        url = f"{self.BASE_URL}/api/v3/supplies"
        response = self.session.get(url, params=params)
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

    def get_stickers(self, order_ids, type="png", width=58, height=40) -> dict:
        """
        Получить стикеры для сборочных заданий (FBS).
        order_ids: список ID сборочных заданий (orders)
        type: формат стикера ("png", "pdf", "zpl")
        width: ширина стикера
        height: высота стикера
        Возвращает: dict с данными стикеров
        """
        url = f"{self.BASE_URL}/api/v3/orders/stickers"
        data = {"orders": order_ids,}
        response = self.session.post(url, params={"width": width, "height": height, "type": type}, json=data)
        response.raise_for_status()
        return response.json()

    def add_orders_to_supply(self, supply_id: str, order_ids: list) -> Dict:
        """
        Добавить сборочные задания в поставку.
        supply_id: ID поставки
        order_ids: список ID сборочных заданий (orders)
        Возвращает: dict с результатом
        """
        url = f"{self.BASE_URL}/api/v3/supplies/{supply_id}/orders"
        data = {"orders": order_ids}
        response = self.session.post(url, json=data)
        response.raise_for_status()
        return response.json()