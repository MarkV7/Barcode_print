import tkinter as tk
import customtkinter as ctk
import sys # <-- Добавить sys

# Попытка импорта Windows-специфичных библиотек


if sys.platform == 'linux':
    IS_WINDOWS = False
else:
    IS_WINDOWS = True
# print('sys.platform:',sys.platform)
# print('IS_WINDOWS:',IS_WINDOWS)


import win32print

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

        # === Настройки Принтера ===
        printer_frame = ctk.CTkFrame(self)
        printer_frame.pack(fill="x", padx=20, pady=10)

        printer_label = ctk.CTkLabel(
            printer_frame,
            text="Выберите принтер:",
            font=self.font,
            anchor="w"
        )
        printer_label.pack(pady=(5, 0), padx=5, anchor="w")

        # Получаем список доступных принтеров
        self.printer_var = tk.StringVar()
        self.printer_combobox = ctk.CTkComboBox(
            printer_frame,
            values=self.get_printer_list(),
            variable=self.printer_var,
            state="readonly",
            font=self.font
        )
        self.printer_combobox.pack(fill="x", padx=5, pady=5)

        # # 1. IP АДРЕС ПРИНТЕРА для СЕТЕВОГО варианта
        # ctk.CTkLabel(printer_frame, text="IP-адрес ZPL-принтера (XPriner 365B):", font=self.font, anchor="w").pack(
        #     pady=(5, 0), padx=5, anchor="w")
        # self.printer_ip_entry = ctk.CTkEntry(printer_frame, font=self.font)
        # self.printer_ip_entry.pack(fill="x", padx=5, pady=(0, 5))
        #
        # # 2. ПОРТ ПРИНТЕРА
        # ctk.CTkLabel(printer_frame, text="Порт принтера (обычно 9100):", font=self.font, anchor="w").pack(pady=(5, 0),
        #                                                                                                   padx=5,
        #                                                                                                   anchor="w")
        # self.printer_port_entry = ctk.CTkEntry(printer_frame, font=self.font)
        # self.printer_port_entry.pack(fill="x", padx=5, pady=(0, 10))

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
        """Получает список доступных принтеров. Реальная работа только под Windows."""
        if IS_WINDOWS:
            try:
                # print('Тестовое сообщение IS_WINDOWS', IS_WINDOWS)
                # Логика для Windows (использует win32print)
                printers = [printer[2] for printer in win32print.EnumPrinters(win32print.PRINTER_ENUM_LOCAL, None, 1)]
                # print('Список принтеров:', printers)
                if not printers:
                    return ["Нет доступных принтеров (Win)"]
                return printers
            except Exception as e:
                print(f"Ошибка при получении списка принтеров (Win): {e}")
                return ["Ошибка получения принтеров (Win)"]
        else:
            # Логика для Linux/тестирования (использует заглушку)
            try:
                # Используем заглушку win32print.py
                mock_printers = win32print.EnumPrinters(win32print.PRINTER_ENUM_LOCAL, None, 1)
                # Вытаскиваем имя принтера (третий элемент в кортеже заглушки)
                printers = [p[2] for p in mock_printers]
                return printers
            except Exception as e:
                print(f"Ошибка при получении списка принтеров (Linux/Mock): {e}")
                return ["Ошибка получения принтеров (Linux/Mock)"]

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

        # --- Принтер (Локальное имя) ---
        default_printer = getattr(self.app_context, "printer_name", "по умолчанию")

        # Устанавливаем в комбобокс выбранное имя принтера, если оно есть в списке
        if default_printer in self.get_printer_list():
            self.printer_var.set(default_printer)
        else:
            # Если принтера нет (например, был удален), выбираем "по умолчанию" или первый
            # Убедитесь, что "по умолчанию" всегда есть в списке values комбобокса.
            self.printer_var.set("по умолчанию")

    def save_settings(self):
            """Сохраняет выбранные настройки в контексте"""

            # --- WB API ---
            wb_api_token = self.wb_token_entry.get().strip()
            self.app_context.wb_api_token = wb_api_token

            # --- Ozon API ---
            self.app_context.ozon_client_id = self.ozon_client_id_entry.get().strip()
            self.app_context.ozon_api_key = self.ozon_api_key_entry.get().strip()

            # --- Принтер (Локальное имя) ---
            selected_printer = self.printer_var.get()
            self.app_context.printer_name = selected_printer  # <--- СОХРАНЯЕМ ИМЯ

            # self.show_save_status("Настройки сохранены!", "green")
            # Обновление метки статуса
            self.status_label.configure(text="Настройки успешно сохранены!")
            self.after(3000, lambda: self.status_label.configure(text=""))