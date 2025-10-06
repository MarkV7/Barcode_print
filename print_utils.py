import socket

def send_zpl_to_printer(zpl_code: str, host: str, port: int = 9100):
    """Отправляет ZPL-код на сетевой принтер."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.connect((host, port))
        s.sendall(zpl_code.encode('utf-8'))
        s.close()
        print(f"ZPL-код успешно отправлен на {host}:{port}")
    except socket.error as e:
        print(f"Ошибка при отправке ZPL-кода на принтер: {e}")

# Пример использования в логике:
# ...
# print_utils.send_zpl_to_printer(zpl_code, host="192.168.1.100", port=9100)
# ...