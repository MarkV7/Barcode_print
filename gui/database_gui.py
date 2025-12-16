import customtkinter as ctk
import pandas as pd
from tkinter import filedialog, messagebox
from gui.gui_table import EditableDataTable


class DatabaseMode(ctk.CTkFrame):
    def __init__(self, parent, font, context):
        super().__init__(parent)
        self.parent = parent
        self.font = font
        self.context = context
        self.file_path = None
        self.df = None
        self.data_loaded = False
        if self.context.df is not None and not self.context.df.empty:
            self.df = self.context.df.copy()
            self.data_loaded = True
        else:
            self.df = None

        # Заголовок
        self.title_label = ctk.CTkLabel(
            self,
            text="📁 База Excel",
            font=ctk.CTkFont(size=20, weight="bold"),
            anchor="w"
        )
        self.title_label.pack(pady=(10, 20), anchor="w", padx=20)

        # Путь до файла
        self.path_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.path_frame.pack(fill="x", padx=20, pady=5)
        self.path_label = ctk.CTkLabel(
            self.path_frame,
            text="📄 Путь до Excel файла:",
            font=self.font,
            width=150,
            anchor="w"
        )
        self.path_label.pack(side="left")
        self.path_entry = ctk.CTkEntry(self.path_frame, font=self.font, placeholder_text="Путь к файлу...", width=400)
        self.path_entry.pack(side="left", expand=True, fill="x", padx=5)
        self.browse_button = ctk.CTkButton(
            self.path_frame,
            text="Выбрать",
            width=80,
            command=self.load_excel_file
        )
        self.browse_button.pack(side="left")

        # Информация о количестве строк + кнопка "Обновить"
        self.info_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.info_frame.pack(fill="x", padx=20, pady=5)
        self.rows_label = ctk.CTkLabel(
            self.info_frame,
            text="🔢 Количество строк: неизвестно",
            font=self.font,
            anchor="w"
        )
        self.rows_label.pack(side="left")
        self.refresh_button = ctk.CTkButton(
            self.info_frame,
            text="Обновить",
            width=40,
            height=28,
            font=ctk.CTkFont(size=16),
            command=self.reload_excel_file
        )
        self.refresh_button.pack(side="left", padx=10)

        # Область для таблицы
        self.table_container = ctk.CTkFrame(self)
        self.table_container.pack(fill="both", expand=True, padx=20, pady=10)

        # Контейнер под таблицу
        self.table_frame = ctk.CTkFrame(self.table_container, fg_color="transparent")
        self.table_frame.pack(fill="both", expand=True)

        self.table = None

    def load_excel_file(self, file_path=None):
        if not file_path:
            file_path = filedialog.askopenfilename(filetypes=[("Excel files", "*.xlsx")])
        else:
            self.path_entry.delete(0, "end")
            self.path_entry.insert(0, file_path)
        if not file_path:
            return
        
        try:
            if not self.data_loaded or True:
                self.df = pd.read_excel(file_path, engine="openpyxl").convert_dtypes()
                self.file_path = file_path
                self.path_entry.delete(0, "end")
                self.path_entry.insert(0, file_path)
                row_count = len(self.df)
                self.rows_label.configure(text=f"🔢 Количество строк: {row_count}")
                self.context.file_path = file_path
                self.context.df = self.df
            self.after(50, self.display_table)
        except Exception as e:
            messagebox.showerror("Ошибка", f"Не удалось прочитать файл:\n{str(e)}")

    def reload_excel_file(self):
        if not self.file_path:
            messagebox.showwarning("Файл не загружен", "Сначала выберите файл.")
            return
        try:
            self.df = pd.read_excel(self.file_path, engine="openpyxl").convert_dtypes()
            self.context.df = self.df
            row_count = len(self.df)
            self.rows_label.configure(text=f"🔢 Количество строк: {row_count}")
            self.display_table()
        except Exception as e:
            messagebox.showerror("Ошибка", f"Не удалось перезагрузить файл:\n{str(e)}")

    def display_table(self):
        for widget in self.table_frame.winfo_children():
            widget.destroy()
        if self.df is None:
            return

        # Создаем таблицу с прокруткой — теперь с автономными кнопками внутри
        self.table = EditableDataTable(
            self.table_frame,
            dataframe=self.df,
            columns=self.df.columns.tolist(),  # <--- 1. ПЕРЕДАЕМ СПИСОК КОЛОНОК
            on_row_select=None,                # <--- 2. ПЕРЕДАЕМ None (или lambda row: None)
            max_rows=5000,
            header_font=("Segoe UI", 14, "bold"),
            cell_font=("Segoe UI", 14),
            readonly=False,
            on_edit_end=self.save_changes
        )
        self.table.pack(fill="both", expand=True)

    def save_changes(self):
        self.context.df = self.table.displayed_df
        self.df = self.table.displayed_df
