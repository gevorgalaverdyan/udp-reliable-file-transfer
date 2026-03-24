import pickle
import socket
from uuid import uuid4

from models.packet import Packet
from models.utils import Message

class Client:
    def __init__(self, server_ip: str, port: int, filename: str, max_payload: int):
        self.server_ip = server_ip
        self.port = port
        self.filename = filename
        self.max_payload = max_payload

    def start_sending(self):
        clientSocket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        print(f"UDP Client is sending to {self.server_ip}:{self.port}\n")

        try:
            while True:
                p = pickle.dumps(Packet(uuid4(), 0, Message.REQUEST, payload="none"))
                clientSocket.sendto(p, (self.server_ip, self.port))
                response, _ = clientSocket.recvfrom(1024)

                original_object: Packet= pickle.loads(response)

                if original_object.msg_type == Message.ERROR:
                    pass

                print(f"Received response: {vars(original_object)}")
                break
        except KeyboardInterrupt:
            clientSocket.sendto(b"exit", (self.server_ip, self.port))
            print("\nUDP Client closed")
        finally:
            clientSocket.close()