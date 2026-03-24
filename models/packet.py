from uuid import UUID

from models.utils import BinaryInt, Message


class Packet:
    def __init__(self, connection_id: UUID, seq_num: BinaryInt, msg_type: Message, payload, payload_length: bytes = None):
        self.connection_id = connection_id
        self.seq_num = seq_num
        self.msg_type = msg_type
        self.payload_length = payload_length
        self.payload = payload
