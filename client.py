import argparse
from pathlib import Path
import random
import socket
import time
from common import pack_packet, unpack_packet, MESSAGE_TYPES


def log(msg: str):
    ts = time.strftime("%H:%M:%S")
    print(f"[CLIENT {ts}] {msg}")


def rcv_file(server_ip: str, port: int, filename: str, segment_size: int):
    path_to_output = Path("./files/received/"+filename)
    path_to_output.parent.mkdir(parents=True, exist_ok=True)

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    conn_id = random.getrandbits(32)
    server_addr = (server_ip, port)

    log(f"Connection ID: {conn_id}")
    log(
        f"Requesting '{filename}' from {server_ip}:{port}  "
        f"(segment_size={segment_size})"
    )

    req_packet = pack_packet(
        conn_id, 0, MESSAGE_TYPES.REQUEST, False, filename.encode()
    )
    sock.sendto(req_packet, server_addr)

    raw_data, addr = sock.recvfrom(65535)
    packet = unpack_packet(raw_data)

    expected_seq = 0

    if not packet:
        log("ERROR: malformed packet received")
        return

    connection_id, sequence_number, message_type, is_final, payload = packet
    if connection_id != conn_id:
        log(
            f"ERROR: connection ids not equal received={connection_id} expecting={conn_id}"
        )
        return

    if message_type == MESSAGE_TYPES.ERROR:
        log(f"MESSAGE ERROR: {payload.decode('utf-8')}")
        return
    elif message_type == MESSAGE_TYPES.DATA:
        log(
            f"RECEIVED: seq={sequence_number}, payload_size={len(payload)}, is_final={is_final}"
        )
        if sequence_number == expected_seq:
            with open(path_to_output, "wb") as f:
                f.write(payload)

            ack_packet = pack_packet(conn_id, sequence_number, MESSAGE_TYPES.ACK, False, b"") 
            sock.sendto(ack_packet, addr)
            
            if is_final:
                return
            
            expected_seq ^= 1
        else: 
            log("ERROR: Unexpected seq number")
    else:
        log(f"Unexpected packet type: {message_type.name}")
        return


def main():
    """Captures server_ip, server_port, filename, segment_size"""

    parser = argparse.ArgumentParser(description="UDP File Transfer Client")
    parser.add_argument("server_ip", help="Server IP address (e.g. 127.0.0.1)")
    parser.add_argument("port", type=int, help="Server UDP port")
    parser.add_argument("filename", help="Name of the file to retrieve from the server")
    parser.add_argument(
        "--segment-size",
        type=int,
        help=f"Max UDP payload bytes per DATA packet",
        required=True,
    )

    args = parser.parse_args()
    rcv_file(args.server_ip, args.port, args.filename, args.segment_size)


if __name__ == "__main__":
    main()
