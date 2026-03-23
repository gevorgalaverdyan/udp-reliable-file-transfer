class Client:
    def __init__(self, server_ip: str, port: int, filename: str, max_payload: int):
        self.server_ip = server_ip
        self.port = port
        self.filename = filename
        self.max_payload = max_payload