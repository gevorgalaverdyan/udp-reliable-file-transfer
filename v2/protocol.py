"""
UDP File Transfer Protocol — Shared Definitions
================================================
Packet layout (9-byte fixed header):
  Offset  Size  Field
  ------  ----  -----
  0       4     Connection ID  (uint32, big-endian)
  4       1     Sequence Number (uint8,  0 or 1 for stop-and-wait)
  5       1     Message Type   (uint8)
  6       1     Flags          (uint8,  bit-0 = FINAL)
  7       2     Payload Length (uint16, big-endian)
  9       N     Payload        (bytes)
"""

import struct

HEADER_FORMAT  = "!IBBBH"       # network byte-order: uint32, uint8×3, uint16
HEADER_SIZE    = struct.calcsize(HEADER_FORMAT)   # == 9

# ── Message types ─────────────────────────────────────────────────────────────
MSG_REQUEST = 0x01
MSG_DATA    = 0x02
MSG_ACK     = 0x03
MSG_ERROR   = 0x04

MSG_NAMES = {
    MSG_REQUEST: "REQUEST",
    MSG_DATA:    "DATA",
    MSG_ACK:     "ACK",
    MSG_ERROR:   "ERROR",
}

# ── Flags ─────────────────────────────────────────────────────────────────────
FLAG_FINAL = 0x01   # set on the last DATA packet of a transfer

# ── Network defaults ──────────────────────────────────────────────────────────
DEFAULT_PORT         = 9000
DEFAULT_SEGMENT_SIZE = 512     # max payload bytes per DATA packet
DEFAULT_TIMEOUT      = 2.0     # seconds before retransmit
MAX_RETRIES          = 10      # give up after this many consecutive timeouts


# ── Pack / unpack helpers ──────────────────────────────────────────────────────

def pack_packet(conn_id: int, seq: int, msg_type: int,
                flags: int, payload: bytes) -> bytes:
    """Serialise a complete packet (header + payload)."""
    header = struct.pack(HEADER_FORMAT,
                         conn_id, seq, msg_type, flags, len(payload))
    return header + payload


def unpack_packet(data: bytes):
    """
    Parse raw bytes into (conn_id, seq, msg_type, flags, payload).
    Returns None if the data is too short or malformed.
    """
    if len(data) < HEADER_SIZE:
        return None
    conn_id, seq, msg_type, flags, pay_len = struct.unpack(
        HEADER_FORMAT, data[:HEADER_SIZE]
    )
    payload = data[HEADER_SIZE: HEADER_SIZE + pay_len]
    if len(payload) != pay_len:
        return None
    return conn_id, seq, msg_type, flags, payload


def is_final(flags: int) -> bool:
    return bool(flags & FLAG_FINAL)


def type_name(msg_type: int) -> str:
    return MSG_NAMES.get(msg_type, f"UNKNOWN(0x{msg_type:02x})")