import socket

class Server:
    def __init__(self, server_ip: str, port: int):
        self.server_ip = server_ip
        self.port = port
    
    def start_listener(self):
        serverSocket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        serverSocket.bind((self.server_ip, self.port))
        
        print(f"UDP Server is listening on {self.server_ip}:{self.port}")
        while True:
            data, client_address = serverSocket.recvfrom(1024)
            if data.decode() == 'exit':
                break
            print(f"Received Data from {client_address}: {data.decode()}")
            
            response_message = b'Hello, Client!'
            serverSocket.sendto(response_message, client_address)

        serverSocket.close()
        print("UDP Server closed")