from logger_setup import setup_global_logger
setup_global_logger()
import customtkinter as ctk
from gui.app_ui import AppUI



# --- Запуск приложения ---
if __name__ == "__main__":
    root = ctk.CTk()
    app = AppUI(root)
    root.mainloop()
