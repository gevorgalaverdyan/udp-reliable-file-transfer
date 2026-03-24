from pathlib import Path
import pickle
import socket

from models.packet import Packet
from models.utils import Message

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
            # if data.decode() == 'exit':
            #     break
            original_object: Packet= pickle.loads(data)

            print(f"Received Data from {client_address}: {vars(original_object)}")

            response_packet = b'Hello, Client!'
            if not Path(f"./files/{original_object.payload}").exists():
                response_packet = pickle.dumps(Packet(original_object.connection_id, seq_num=0, msg_type=Message.ERROR, payload=None))

            serverSocket.sendto(response_packet, client_address)

        serverSocket.close()
        print("UDP Server closed")