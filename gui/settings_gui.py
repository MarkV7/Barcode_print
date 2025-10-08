import tkinter as tk
import customtkinter as ctk

# import win32print  <-- УДАЛЕНО

class SettingsMode(ctk.CTkFrame):
    def __init__(self, parent, font, app_context):
        super().__init__(parent)
        self.font = font
        self.app_context = app_context

        # Инициализируем UI
        self.setup_ui()

        # Загружаем текущие настройки из контекста
        self.load_settings()

    def setup_ui(self):
        """Создаёт интерфейс настроек"""

        # === Настройки API Wildberries ===
        wb_frame = ctk.CTkFrame(self)
        wb_frame.pack(fill="x", padx=20, pady=10)

        ctk.CTkLabel(wb_frame, text="Токен Wildberries API (FBS):", font=self.font, anchor="w").pack(pady=(5, 0),
                                                                                                     padx=5, anchor="w")
        self.wb_token_entry = ctk.CTkEntry(wb_frame, font=self.font)
        self.wb_token_entry.pack(fill="x", padx=5, pady=(0, 10))

        # === Настройки API Ozon (НОВОЕ) ===
        ozon_frame = ctk.CTkFrame(self)
        ozon_frame.pack(fill="x", padx=20, pady=10)

        ctk.CTkLabel(ozon_frame, text="Client ID Ozon API:", font=self.font, anchor="w").pack(pady=(5, 0), padx=5,
                                                                                              anchor="w")
        self.ozon_client_id_entry = ctk.CTkEntry(ozon_frame, font=self.font)
        self.ozon_client_id_entry.pack(fill="x", padx=5, pady=(0, 5))

        ctk.CTkLabel(ozon_frame, text="API Key Ozon:", font=self.font, anchor="w").pack(pady=(5, 0), padx=5, anchor="w")
        self.ozon_api_key_entry = ctk.CTkEntry(ozon_frame, font=self.font, show="*")
        self.ozon_api_key_entry.pack(fill="x", padx=5, pady=(0, 10))

        # === Настройки Принтера (СЕТЕВЫЕ) ===
        printer_frame = ctk.CTkFrame(self)
        printer_frame.pack(fill="x", padx=20, pady=10)

        # 1. IP АДРЕС ПРИНТЕРА
        ctk.CTkLabel(printer_frame, text="IP-адрес ZPL-принтера (XPriner 365B):", font=self.font, anchor="w").pack(
            pady=(5, 0), padx=5, anchor="w")
        self.printer_ip_entry = ctk.CTkEntry(printer_frame, font=self.font)
        self.printer_ip_entry.pack(fill="x", padx=5, pady=(0, 5))

        # 2. ПОРТ ПРИНТЕРА
        ctk.CTkLabel(printer_frame, text="Порт принтера (обычно 9100):", font=self.font, anchor="w").pack(pady=(5, 0),
                                                                                                          padx=5,
                                                                                                          anchor="w")
        self.printer_port_entry = ctk.CTkEntry(printer_frame, font=self.font)
        self.printer_port_entry.pack(fill="x", padx=5, pady=(0, 10))

        # --- Кнопки и статус ---
        save_button = ctk.CTkButton(
            self,
            text="Сохранить настройки",
            command=self.save_settings,
            font=self.font
        )
        save_button.pack(pady=10)

        self.status_label = ctk.CTkLabel(
            self,
            text="Статус: Ожидание сохранения...",
            font=self.font,
            text_color="gray"
        )
        self.status_label.pack(pady=5)

    def get_printer_list(self):
        """
        Заглушка, заменяющая win32print.
        В кроссплатформенном режиме мы используем IP/порт.
        Возвращает фиктивный список для совместимости.
        """
        # Возвращаем список, чтобы не сломать инициализацию, если она использует этот метод
        return ["Сетевой ZPL-принтер (IP/порт)"]

    def load_settings(self):
        """Загружает текущие настройки из контекста"""

        # --- WB API ---
        wb_api_token = getattr(self.app_context, "wb_api_token", "")
        self.wb_token_entry.insert(0, wb_api_token)

        # --- Ozon API (НОВОЕ) ---
        ozon_client_id = getattr(self.app_context, "ozon_client_id", "")
        ozon_api_key = getattr(self.app_context, "ozon_api_key", "")
        self.ozon_client_id_entry.insert(0, ozon_client_id)
        self.ozon_api_key_entry.insert(0, ozon_api_key)

        # --- Принтер (IP/Port) ---
        printer_ip = getattr(self.app_context, "printer_ip", "192.168.1.100")
        printer_port = getattr(self.app_context, "printer_port", "9100")

        self.printer_ip_entry.insert(0, printer_ip)
        self.printer_port_entry.insert(0, printer_port)

    def save_settings(self):
        """Сохраняет выбранные настройки в контексте"""

        # --- WB API ---
        wb_api_token = self.wb_token_entry.get().strip()
        self.app_context.wb_api_token = wb_api_token

        # --- Ozon API ---
        self.app_context.ozon_client_id = self.ozon_client_id_entry.get().strip()
        self.app_context.ozon_api_key = self.ozon_api_key_entry.get().strip()

        # --- Принтер (IP/Port) ---
        printer_ip = self.printer_ip_entry.get().strip()
        printer_port = self.printer_port_entry.get().strip()

        # Сохраняем IP и порт, а printer_name устанавливаем в фиктивное значение,
        # чтобы не сломать внешние вызовы (хотя print_on_windows уже переписан)
        self.app_context.printer_ip = printer_ip
        self.app_context.printer_port = int(printer_port) if printer_port.isdigit() else 9100
        self.app_context.printer_name = f"ZPL_PRINTER_{printer_ip}"

        # Обновление статуса
        self.status_label.configure(text="✅ Настройки успешно сохранены!", text_color="green")