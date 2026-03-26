import struct
from enum import Enum


class MESSAGE_TYPES(Enum):
    REQUEST = 1
    DATA = 2
    ACK = 3
    ERROR = 4


"""
struct will then convert them to bytes:
connection_id = 4 bytes → I
sequence_number = 4 bytes → I
message_type = 1 byte → B
is_final = 1 byte → B
payload_length = 2 bytes → H

TOTAL = 12 bytes
"""
HEADER_FORMAT = "!IIBBH"
HEADER_SIZE = struct.calcsize(HEADER_FORMAT)


def pack_packet(
    connection_id: int,
    sequence_number: int,
    message_type: MESSAGE_TYPES,
    is_final: bool,
    payload: bytes,
):
    """
    Packing HEADER+Payload

    Args:
        is_final (bool): Take as bool and transform to bit val

    Returns:
        bytes: data packet in bytes
    """
    payload_length = len(payload)
    header = struct.pack(
        HEADER_FORMAT,
        connection_id,
        sequence_number,
        message_type.value,
        int(is_final),
        payload_length,
    )

    return header + payload


def unpack_packet(data: bytes):
    """
    Receives raw bytes, separate header|payload

    Returns:
        tuple: parsed values connection_id, sequence_number, message_type, is_final, payload
    """
    if len(data) < HEADER_SIZE:
        return

    connection_id, sequence_number, message_type, is_final, payload_length = (
        struct.unpack_from(HEADER_FORMAT, data)
    )

    payload = data[HEADER_SIZE:]

    if len(payload) != payload_length:
        return

    return (
        connection_id,
        sequence_number,
        MESSAGE_TYPES(message_type),
        bool(is_final),
        payload,
    )
