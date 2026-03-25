from enum import StrEnum
from typing import Literal

BinaryInt = Literal[0, 1]

class Message(StrEnum):
    REQUEST = 'REQUEST'
    DATA = 'DATA'
    ACK = 'ACK'
    ERROR  = 'ERROR'
