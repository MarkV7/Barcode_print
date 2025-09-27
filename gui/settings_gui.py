import tkinter as tk
import customtkinter as ctk
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
        # === Выбор принтера ===
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

        # === Поля ввода Токена WB API ===
        wb_api_frame = ctk.CTkFrame(self)
        wb_api_frame.pack(fill="x", padx=20, pady=10)

        wb_api_label = ctk.CTkLabel(
            wb_api_frame,
            text="Укажите API Токен Wildberries:",
            font=self.font,
            anchor="w"
        )
        wb_api_label.pack(pady=(5, 0), padx=5, anchor="w")

        # Поле ввода с плейсхолдером и возможностью скрытия текста
        self.wb_token_entry = ctk.CTkEntry(
            wb_api_frame,
            font=self.font,
            placeholder_text="Введите ваш API токен...",
            show="•"  # Можно убрать, если не нужно скрывать
        )
        self.wb_token_entry.pack(fill="x", padx=5, pady=5)

        # Если нужно: переключатель видимости
        self.show_token_var = tk.BooleanVar(value=False)
        toggle_token_visibility = ctk.CTkCheckBox(
            wb_api_frame,
            text="Показать токен",
            variable=self.show_token_var,
            command=lambda: self.wb_token_entry.configure(show="" if self.show_token_var.get() else "•")
        )
        toggle_token_visibility.pack(padx=5, pady=5, anchor="w")

        # === Кнопка сохранения ===
        save_button = ctk.CTkButton(
            self,
            text="Сохранить настройки",
            command=self.save_settings,
            font=self.font
        )
        save_button.pack(pady=10)

        # === Статус сохранения ===
        self.status_label = ctk.CTkLabel(
            self,
            text="",
            font=("Segoe UI", 12),
            text_color="green"
        )
        self.status_label.pack(pady=5)

    def get_printer_list(self):
        """Получает список доступных принтеров в Windows"""
        try:
            printers = [printer[2] for printer in win32print.EnumPrinters(win32print.PRINTER_ENUM_LOCAL, None, 1)]
            if not printers:
                return ["Нет доступных принтеров"]
            return printers
        except Exception as e:
            print(f"Ошибка при получении списка принтеров: {e}")
            return ["Ошибка получения принтеров"]

    def load_settings(self):
        """Загружает текущие настройки из контекста"""
        default_printer = getattr(self.app_context, "printer_name", "по умолчанию")
        wb_api_token = getattr(self.app_context, "wb_api_token", "")
        if default_printer in self.get_printer_list():
            self.printer_var.set(default_printer)
        else:
            self.printer_var.set("по умолчанию")
        self.wb_token_entry.insert(0, wb_api_token)

    def save_settings(self):
        """Сохраняет выбранный принтер в контексте"""
        selected_printer = self.printer_var.get()
        wb_api_token = self.wb_token_entry.get().strip()
        self.app_context.printer_name = selected_printer
        self.app_context.wb_api_token = wb_api_token

        # Обновление метки статуса
        self.status_label.configure(text="Настройки успешно сохранены!")
        self.after(3000, lambda: self.status_label.configure(text=""))
