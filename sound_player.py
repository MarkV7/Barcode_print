# sound_player.py

import platform
import os
import subprocess
import sys

def play_sound(sound_file):
    """Воспроизводит кастомный звук """
    if platform.system() == "Windows":
        # Windows: используем winsound
        import winsound
        sound_path = os.path.join(get_base_path(), "assets", "sounds", sound_file)
        if os.path.exists(sound_path):
            winsound.PlaySound(sound_path, winsound.SND_ASYNC)

    elif platform.system() == "Darwin":
        # macOS: используем afplay
        sound_path = os.path.join(get_base_path(), "assets", "sounds", sound_file)
        if os.path.exists(sound_path):
            subprocess.run(["afplay", sound_path])

    else:
        # Linux и другие: можно использовать aplay или другое
        sound_path = os.path.join(get_base_path(), "assets", "sounds", sound_file)
        if os.path.exists(sound_path):
            subprocess.run(["aplay", sound_path])


def play_success_scan_sound():
    """Воспроизводит кастомный звук успеха"""
    play_sound("success.wav")


def play_unsuccess_scan_sound():
    play_sound("error.wav")


def get_base_path():
    """Возвращает путь к директории с исполняемым файлом или скриптом"""
    if getattr(sys, 'frozen', False):
        # Если приложение "заморожено" (PyInstaller)
        return sys._MEIPASS
    else:
        return os.path.dirname(os.path.abspath(__file__))
