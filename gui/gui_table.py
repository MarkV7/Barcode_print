import customtkinter as ctk
from tkinter import ttk
import pandas as pd
from tkinter import filedialog, messagebox
from PIL import Image


class EntryPopup(ttk.Entry):
    def __init__(self, parent, row_id, col_index, text, font=None, **kw):
        super().__init__(parent.tree, **kw)  # Размещается на Treeview
        self.parent = parent
        self.tree = parent.tree

        self.row_id = row_id
        self.col_index = col_index

        if parent.on_edit_start:
            parent.on_edit_start()

        # Настройка визуала
        self['font'] = font or ('Segoe UI', 14)
        self.insert(0, text)
        self['exportselection'] = False
        self.focus_force()
        self.select_all()

        # Привязки
        self.bind("<Return>", self.on_return)
        self.bind("<Control-a>", self.select_all)
        self.bind("<Escape>", lambda e: (self.parent.on_edit_end() if self.parent.on_edit_end else None) or self.destroy())
        self.bind("<FocusOut>", self.on_focus_out)
        self.bind("<Tab>", self.on_tab)

        # Показываем поле редактирования поверх ячейки
        tree_bbox = self.tree.bbox(row_id, f"#{col_index + 1}")  # колонка с учётом "№"
        if tree_bbox:
            x, y, width, height = tree_bbox
            self.place(x=x, y=y, width=width, height=height)

    def on_tab(self, event=None):
        self.apply_changes()  # Сохраняем изменения в текущей ячейке

        # Получаем количество колонок (без учета столбца "№")
        num_cols = len(self.parent.displayed_df.columns)

        # Переход к следующей ячейке или следующей строке
        next_col = self.col_index + 1
        row_id = int(self.row_id)

        if next_col < num_cols:
            # Переходим к следующей ячейке той же строки
            self.destroy()
            self.parent.open_next_cell_editor(str(row_id), next_col)
        else:
            # Если это была последняя ячейка — переходим на первую ячейку следующей строки
            next_row = row_id + 1
            if next_row < len(self.parent.displayed_df):
                self.destroy()
                self.parent.open_next_cell_editor(str(next_row), 0)
            else:
                # Если это последняя строка — просто закрываем
                self.destroy()

        return "break"  # Блокируем стандартное поведение Tab

    def on_return(self, event=None):
        self.apply_changes()
        self.destroy()

    def on_focus_out(self, event=None):
        self.apply_changes()
        self.destroy()

    def apply_changes(self):
        new_value = self.get()

        # Получаем текущие значения из Treeview
        tree_values = list(self.tree.item(self.row_id, "values"))

        # Обновляем значение в нужной позиции (учитываем столбец "№")
        real_col_index_in_tree = self.col_index + 1
        tree_values[real_col_index_in_tree] = new_value
        self.tree.item(self.row_id, values=tree_values)

        # Обновляем displayed_df
        index = int(self.row_id)
        col_name = self.parent.displayed_df.columns[self.col_index]
        self.parent.displayed_df.at[index, col_name] = new_value

        if self.parent.on_edit_end:
            self.parent.on_edit_end()

    def select_all(self, *ignore):
        self.selection_range(0, "end")
        return "break"


class EditableDataTable(ctk.CTkFrame):
    def __init__(self, parent, dataframe, columns, on_row_select,
                 max_rows=None, header_font=None, cell_font=None,
                 show_statusbar=True, readonly=False,
                 on_edit_start=None, on_edit_end=None, textlbl = "Таблица:",**kwargs):
        super().__init__(parent, **kwargs)
        self.dataframe = dataframe.copy()
        self.original_df = dataframe.copy()  # Сохраняем оригинал для сравнения
        self.max_rows = max_rows if max_rows else len(dataframe)
        self.displayed_df = self.dataframe.head(self.max_rows).copy().astype(object)
        self.header_font = header_font or ("Segoe UI", 14, "bold")
        self.cell_font = cell_font or ("Segoe UI", 14)
        self.show_statusbar = show_statusbar
        self.columns = columns  # 💡 Сохраняем список колонок
        self.on_row_select = on_row_select # Сохраняем колбэк
        self.readonly = readonly
        self.on_edit_start = on_edit_start
        self.on_edit_end = on_edit_end
        self.textlbl = textlbl
        self._last_selected_iid = None

        # Настройка стиля
        self.style = ttk.Style()
        self._configure_styles()

        # Создание виджетов
        self._create_widgets()

        # 💡 ОБЯЗАТЕЛЬНАЯ ПРИВЯЗКА СОБЫТИЯ
        self.tree.bind('<<TreeviewSelect>>', self._on_tree_select)

    def _configure_styles(self):
        self.style.theme_use("default")  # <-- замена на clam
        self.style.configure("Treeview",
                     font=self.cell_font,
                     rowheight=30,
                     background="white",
                     foreground="black",
                     fieldbackground="white",
                     bordercolor="lightgray",  # <-- важный параметр
                     lightcolor="lightgray",   # <-- важный параметр
                     darkcolor="lightgray",    # <-- важный параметр
                     relief="solid",)           # <-- важный параметр


        # Добавляем границы для ячеек — имитация сетки Excel
        self.style.configure("Treeview", rowheight=25, fieldbackground="white")
        self.style.map("Treeview", background=[('selected', '#4a6fae')])

        # Стиль заголовков
        self.style.configure("Treeview.Heading",
                            font=self.header_font,
                            background="#f0f0f0",
                            foreground="black",
                            relief="flat")

        # Активный заголовок (при наведении)
        self.style.map("Treeview.Heading",
                    relief=[('active', 'groove')],
                    background=[('active', '#e0e0e0')])

        # Добавляем тонкие границы между строками и столбцами
        self.style.layout("Treeview.Item", [
            ('Treeitem.row', {'sticky': 'nswe'}),
            ('Treeitem.image', {'side': 'left', 'sticky': ''}),
            ('Treeitem.text', {'side': 'left', 'sticky': ''})
        ])

        # Имитируем сетку с помощью фона и разделителей
        self.style.configure("Treeview",
                            bordercolor="lightgray",
                            lightcolor="lightgray",
                            darkcolor="lightgray",
                            relief="solid")

    def _create_widgets(self):
        # --- Контейнер для кнопок ---
        button_frame = ctk.CTkFrame(self, fg_color="transparent")
        if not self.readonly:
            button_frame.pack(pady=(5, 0), fill="x")

        # Label для таблицы
        self.table_label = ctk.CTkLabel(
            button_frame,
            text=self.textlbl,
            font=ctk.CTkFont(size=14, weight="bold"),
            anchor="w"
        )
        self.table_label.pack(side="left", padx=5)

        # Кнопка "Вверх"
        self.up_btn = ctk.CTkButton(
            button_frame,
            image=ctk.CTkImage(light_image=Image.open("assets/icons/up.png"), size=(16, 16)),
            text="",
            width=18,
            height=22,
            command=self.move_row_up
        )
        self.up_btn.pack(side="left", padx=2)

        # Кнопка "Вниз"
        self.down_btn = ctk.CTkButton(
            button_frame,
            image=ctk.CTkImage(light_image=Image.open("assets/icons/down.png"), size=(16, 16)),
            text="",
            width=18,
            height=22,
            command=self.move_row_down
        )
        self.down_btn.pack(side="left", padx=2)

        # Кнопка "Удалить"
        self.del_btn = ctk.CTkButton(
            button_frame,
            image=ctk.CTkImage(light_image=Image.open("assets/icons/trashcan.png"), size=(16, 16)),
            text="",
            width=18,
            height=22,
            fg_color="#FA3C3C",
            hover_color="#FF0000",
            command=self.delete_selected_row
        )
        self.del_btn.pack(side="left", padx=2)

        # --- Таблица с прокруткой ---
        container = ctk.CTkFrame(self)
        container.pack(fill="both", expand=True)

        y_scroll = ctk.CTkScrollbar(container, orientation="vertical")
        x_scroll = ctk.CTkScrollbar(container, orientation="horizontal")
        y_scroll.pack(side="right", fill="y")
        x_scroll.pack(side="bottom", fill="x")

        columns = ["№"] + list(self.displayed_df.columns)
        self.tree = ttk.Treeview(
            container,
            columns=columns,
            show="headings",
            selectmode="browse",
            yscrollcommand=y_scroll.set,
            xscrollcommand=x_scroll.set,
        )
        self.tree.pack(fill="both", expand=True)

        self.tree.heading("№", text="№")
        self.tree.column("№", anchor="center", width=50, stretch=False)

        for col in self.displayed_df.columns:
            self.tree.heading(col, text=col)
            if col=="Количество": self.tree.column(col, anchor="w", width=50)
            elif col == "Размер": self.tree.column(col, anchor="w", width=50)
            elif col == "Служба доставки":
                self.tree.column(col, anchor="w", width=150)
            elif col == "Статус обработки":
                self.tree.column(col, anchor="w", width=150)
            else:
                self.tree.column(col, anchor="w", width=200)

        self._insert_data()

        y_scroll.configure(command=self.tree.yview)
        x_scroll.configure(command=self.tree.xview)

        # --- Строка статуса + кнопка сохранения ---
        status_frame = ctk.CTkFrame(self, fg_color=self.cget("fg_color"))
        status_frame.pack(pady=5, fill="x")

        if self.show_statusbar:
            self.status_label = ctk.CTkLabel(
                status_frame,
                text=f"🔢 Показано {len(self.displayed_df)} строк из {len(self.dataframe)}",
                text_color="gray",
                font=ctk.CTkFont(size=12)
            )
            self.status_label.pack(side="left", padx=5)

        # Кнопка "Добавить строку"
        if not self.readonly:
            add_button = ctk.CTkButton(
                status_frame,
                text="➕ Добавить строку",
                width=160,
                height=30,
                command=self.add_row,
            )
            add_button.pack(side="left", padx=5)

        # Кнопка "Очистить всё"
        if not self.readonly:
            clear_button = ctk.CTkButton(
                status_frame,
                text="🗑 Очистить всё",
                width=160,
                height=30,
                fg_color="#FA3C3C",
                hover_color="#FF0000",
                command=self.clear_all_data,
            )
            clear_button.pack(side="left", padx=5)

        save_button = ctk.CTkButton(
            status_frame,
            text="💾 Сохранить как Excel",
            width=160,
            height=30,
            command=self.save_to_excel
        )
        save_button.pack(side="right", padx=5)

        # --- Прячем кнопки по умолчанию ---
        self.up_btn.pack_forget()
        self.down_btn.pack_forget()
        self.del_btn.pack_forget()

        # --- Группа кнопок управления строкой ---
        self.row_controls = [self.up_btn, self.down_btn, self.del_btn]

        # --- Привязка события выбора строки ---
        self.tree.bind("<<TreeviewSelect>>", self.on_row_selected)
        self.tree.bind("<Double-1>", self._on_double_click)

        # Привязываем клавиши к действиям
        self.tree.bind("<KeyPress>", self.on_keypress)
    
    def on_keypress(self, event):
        if event.keysym == "Delete":
            self.delete_selected_row()
        elif event.keysym == "Up":
            self.move_row_up()
        elif event.keysym == "Down":
            self.move_row_down()
        elif (event.keycode == 67) and (event.state & 0x0004):
            self._on_copy_selection(event)

    def clear_all_data(self):
        """Очищает все данные в таблице после подтверждения"""
        answer = messagebox.askyesno("Подтверждение", "Вы действительно хотите очистить все данные?")
        if answer:
            # Очищаем DataFrame
            self.dataframe = self.dataframe.iloc[0:0]  # Оставляем пустой DataFrame той же структуры
            self.displayed_df = self.dataframe.head(self.max_rows).copy().astype(object)

            # Обновляем таблицу и статус
            self._insert_data()
            self.update_status()
            if self.on_edit_end:
                self.on_edit_end()

    def _insert_data(self):
        self.tree.delete(*self.tree.get_children())
        for idx, row in self.displayed_df.iterrows():
            str_values = []
            for val in row:
                if pd.isna(val):
                    str_values.append("")
                elif isinstance(val, float) and val.is_integer():
                    str_values.append(str(int(val)))
                else:
                    str_values.append(str(val))
            values = (idx + 1,) + tuple(str_values)
            self.tree.insert("", "end", iid=idx, values=values)

    def _on_double_click(self, event):
        if self.readonly:
            return
        
        region = self.tree.identify_region(event.x, event.y)
        if region != "cell":
            return

        row_id = self.tree.identify_row(event.y)
        column = self.tree.identify_column(event.x)

        if not row_id:
            return

        bbox = self.tree.bbox(row_id, column)
        if not bbox:
            return

        x, y, width, height = bbox

        try:
            self.entry_popup.destroy()
        except AttributeError:
            pass

        tree_columns = self.tree["columns"]
        col_index_in_tree = int(column[1:]) - 1
        col_name_in_tree = tree_columns[col_index_in_tree]

        if col_name_in_tree == "№":
            return

        # Индекс столбца в displayed_df
        col_index_in_df = col_index_in_tree - 1

        values = self.tree.item(row_id, "values")
        current_text = values[col_index_in_tree]

        # Создаем EntryPopup и размещаем его на Treeview
        self.entry_popup = EntryPopup(
            self,
            row_id=row_id,
            col_index=col_index_in_df,
            text=current_text,
            font=self.cell_font
        )

        # Размещаем поверх ячейки
        self.entry_popup.place(x=x, y=y, width=width, height=height)



        # ... (внутри класса EditableDataTable)

    def select_row(self, df_index):
        """Выделяет строку по индексу DataFrame, устанавливает фокус и прокручивает к ней."""
        # Индексы DataFrame используются как строковые IID в Treeview
        item_id = str(df_index)
        # 1. Сброс предыдущего выделения
        self.tree.selection_set()
        # 2. Выделение новой строки
        self.tree.selection_set(item_id)
        # 3. Установка фокуса (делает строку активной/текущей)
        self.tree.focus(item_id)
        # 4. 💡 КРИТИЧНОЕ ИЗМЕНЕНИЕ: Прокрутка Treeview к элементу, чтобы он был виден
        self.tree.see(item_id)
        # Обновляем внутреннюю переменную для предотвращения дублирующих вызовов
        self._last_selected_iid = item_id

    def on_row_selected(self, event=None):
        selected = self.tree.selection()
        if selected:
            # Показываем кнопки
            for btn in self.row_controls:
                btn.pack(side="left", padx=2)
        else:
            # Скрываем кнопки
            for btn in self.row_controls:
                btn.pack_forget()

    def _on_copy_selection(self, event):
        """Копирует выбранную строку в буфер обмена"""
        selected = self.tree.selection()
        if not selected:
            return

        item = selected[0]
        values = self.tree.item(item, "values")  # Получаем значения всех колонок
        values = list(values)
        del values[0]

        separator = "\t"  # можно использовать ", " или ";" и т.п.
        copied_text = separator.join(str(v) for v in values)

        # Копируем в буфер обмена
        self.clipboard_clear()
        self.clipboard_append(copied_text)
        self.update()  # Обновляем буфер обмена

        print(f"Скопировано: {copied_text}")

    # gui/gui_table.py (Внутри класса EditableDataTable)

    def update_data(self, new_df: pd.DataFrame):
        """
        Очищает Treeview и заполняет его данными из нового DataFrame.
        Использует первый элемент списка values для порядкового номера.
        """
        # 1. Очистка Treeview
        for item in self.tree.get_children():
            self.tree.delete(item)

        # 2. Обновляем внутренний DataFrame
        if new_df.empty:
            self.displayed_df = new_df.copy()
        else:
            # Преобразуем все данные в строки, чтобы Treeview гарантированно их отобразил.
            self.displayed_df = new_df.head(self.max_rows).copy().astype(str)

            # 3. Заменяем NaNs на пустые строки
        self.displayed_df = self.displayed_df.fillna('')

        # 4. Заполняем Treeview новыми данными
        for index, row in self.displayed_df.iterrows():
            # --- КЛЮЧЕВОЕ ИСПРАВЛЕНИЕ: ПРАВИЛЬНЫЙ ФОРМАТ VALUES ---
            # row_list = [№ строки] + [Значение колонки 1, Значение колонки 2, ...]
            row_list = [str(index + 1)] + row.tolist()

            self.tree.insert(
                parent='',
                index='end',
                iid=str(index),
                values=row_list  # Вставляем список с номером строки на первом месте
            )

        # 5. Обновляем скроллбар
        try:
            self._update_scrollbar()
        except AttributeError:
            pass

    def delete_selected_row(self, event=None):
        if self.readonly:
            return
        
        self._close_editor()

        selected = self.tree.selection()
        if not selected:
            return
        row_id = selected[0]
        index = int(row_id)
        self.displayed_df.drop(index=index, inplace=True)
        self.displayed_df.reset_index(drop=True, inplace=True)
        self._insert_data()
        self.update_status()
        if self.on_edit_end:
            self.on_edit_end()

    def move_row_up(self):
        if self.readonly:
            return
        
        self._close_editor()
        selected = self.tree.selection()
        if not selected:
            return
        row_id = selected[0]
        index = int(row_id)
        if index <= 0:
            return
        self.displayed_df.iloc[index - 1], self.displayed_df.iloc[index] = (
            self.displayed_df.iloc[index].copy(),
            self.displayed_df.iloc[index - 1].copy()
        )
        self._insert_data()
        self.tree.selection_set(str(index - 1))
        self.update_status()
        if self.on_edit_end:
            self.on_edit_end()

    def move_row_down(self):
        if self.readonly:
            return
        
        self._close_editor()
        selected = self.tree.selection()
        if not selected:
            return
        row_id = selected[0]
        index = int(row_id)
        if index >= len(self.displayed_df) - 1:
            return
        self.displayed_df.iloc[index + 1], self.displayed_df.iloc[index] = (
            self.displayed_df.iloc[index].copy(),
            self.displayed_df.iloc[index + 1].copy()
        )
        self._insert_data()
        self.tree.selection_set(str(index + 1))
        self.update_status()
        if self.on_edit_end:
            self.on_edit_end()

        """Перемещает выбранную строку вверх по нажатию ↑"""
        selected = self.tree.selection()
        if not selected:
            return
        
        self._close_editor()

        row_id = selected[0]
        index = int(row_id)
        if index <= 0:
            return
        self.displayed_df.iloc[index - 1], self.displayed_df.iloc[index] = (
            self.displayed_df.iloc[index].copy(),
            self.displayed_df.iloc[index - 1].copy()
        )
        self._insert_data()
        self.tree.selection_set(str(index - 1))
        self.update_status()
        if self.on_edit_end:
            self.on_edit_end()

        """Перемещает выбранную строку вниз по нажатию ↓"""
        selected = self.tree.selection()
        if not selected:
            return
        self._close_editor()
        row_id = selected[0]
        index = int(row_id)
        if index >= len(self.displayed_df) - 1:
            return
        self.displayed_df.iloc[index + 1], self.displayed_df.iloc[index] = (
            self.displayed_df.iloc[index].copy(),
            self.displayed_df.iloc[index + 1].copy()
        )
        self._insert_data()
        self.tree.selection_set(str(index + 1))
        self.update_status()
        if self.on_edit_end:
            self.on_edit_end()

    def update_status(self):
        if self.show_statusbar:
            self.status_label.configure(text=f"🔢 Показано {len(self.displayed_df)} строк из {len(self.dataframe)}")

    def add_row(self):
        """Добавляет новую пустую строку в конец таблицы и активирует редактирование первой ячейки"""
        if self.readonly:
            return
        self._close_editor()

        empty_row = pd.Series({col: "" for col in self.displayed_df.columns})
        self.displayed_df = pd.concat([self.displayed_df, pd.DataFrame([empty_row])], ignore_index=True)
        self._insert_data()

        new_index = len(self.displayed_df) - 1
        self.tree.see(new_index)
        self.tree.selection_set(str(new_index))

        # Автоматическое открытие редактирования первой ячейки
        row_id = str(new_index)
        column = "#2"  # "#1" — это №, "#2" — первый столбец из данных

        bbox = self.tree.bbox(row_id, column)
        if not bbox:
            return

        x, y, width, height = bbox

        try:
            self.entry_popup.destroy()
        except AttributeError:
            pass

        tree_columns = self.tree["columns"]
        col_index_in_tree = int(column[1:]) - 1  # Индекс столбца в Treeview
        col_name_in_tree = tree_columns[col_index_in_tree]

        # Индекс столбца в displayed_df
        col_index_in_df = col_index_in_tree - 1  # т.к. первый столбец — "№"

        values = self.tree.item(row_id, "values")
        current_text = values[col_index_in_tree]

        # Создаем EntryPopup и размещаем его на Treeview
        self.entry_popup = EntryPopup(
            self,
            row_id=row_id,
            col_index=col_index_in_df,
            text=current_text,
            font=self.cell_font
        )

        # Размещаем поверх ячейки
        self.entry_popup.place(x=x, y=y, width=width, height=height)

        self.update_status()

    def save_to_excel(self):
        file_path = filedialog.asksaveasfilename(
            defaultextension=".xlsx",
            filetypes=[("Excel файл", "*.xlsx")]
        )
        if not file_path:
            return

        try:
            # Создаем копию и очищаем NaN перед сохранением
            export_df = self.displayed_df.copy()

            for col in export_df.columns:
                export_df[col] = export_df[col].apply(
                    lambda x: "" if pd.isna(x) else (
                        str(int(x)) if isinstance(x, float) and x.is_integer() else str(x)
                    )
                )

            export_df.to_excel(file_path, index=False)
            messagebox.showinfo("Успех", f"Файл успешно сохранён:\n{file_path}")

        except Exception as e:
            messagebox.showerror("Ошибка", f"Не удалось сохранить файл:\n{str(e)}")

    def open_next_cell_editor(self, row_id, col_index):
        if self.readonly:
            return
        
        column = f"#{col_index + 2}"  # Treeview использует "#1" для №, "#2" для первой колонки
        bbox = self.tree.bbox(row_id, column)
        if not bbox:
            return
        x, y, width, height = bbox
        try:
            self.entry_popup.destroy()
        except AttributeError:
            pass

        tree_columns = self.tree["columns"]
        col_name_in_tree = tree_columns[col_index + 1]  # С учётом "№"
        if col_name_in_tree == "№":
            return

        values = self.tree.item(row_id, "values")
        current_text = values[col_index + 1]

        # Создаем EntryPopup и размещаем его на Treeview
        self.entry_popup = EntryPopup(
            self,
            row_id=row_id,
            col_index=col_index,
            text=current_text,
            font=self.cell_font
        )
        self.entry_popup.place(x=x, y=y, width=width, height=height)

    def _close_editor(self):
        """Закрывает открытый EntryPopup, если он есть"""
        try:
            self.entry_popup.destroy()
            del self.entry_popup
        except (AttributeError, KeyError):
            pass

        # /home/markv7/PycharmProjects/Barcode_print/gui/gui_table.py (EditableDataTable._on_tree_select)

    def _on_tree_select(self, event):
        """
        Обрабатывает событие выбора строки, проверяя, что выбор фактически изменился,
        чтобы подавить промежуточные события 'None'.
        """
        # 1. Получаем текущий набор выбранных элементов (строковые ID, список)
        selected_items = self.tree.selection()
        current_iid = selected_items[0] if selected_items else None

        # 2. Если текущий выбранный ID совпадает с предыдущим, просто выходим.
        # Это предотвращает дублирующие вызовы, если пользователь кликнул на уже выбранную строку.
        if current_iid == self._last_selected_iid:
            return

        # 3. Обновляем ID последнего выбранного элемента
        self._last_selected_iid = current_iid

        # 4. Определяем числовой индекс для передачи в колбэк
        selected_index = None
        if current_iid:
            try:
                # Преобразование IID (строкового ID) в числовой индекс (0, 1, 2...)
                selected_index = int(current_iid)
            except ValueError:
                # Если IID не число (например, служебные IID), оставляем None
                pass

        # 5. Вызываем внешний колбэк
        if self.on_row_select:
            # Если пользователь кликнул на новую строку (2) -> вызов с 2.
            # Если пользователь кликнул в пустое место -> вызов с None.
            self.on_row_select(selected_index)