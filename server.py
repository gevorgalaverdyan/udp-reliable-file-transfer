import argparse
from pathlib import Path
import socket
import sys
import time

from common import pack_packet, unpack_packet, MESSAGE_TYPES


def log(msg: str):
    ts = time.strftime("%H:%M:%S")
    print(f"[SERVER {ts}] {msg}")


def split_into_chunks(data: bytes, chunk_size: int) -> list[bytes]:
    if len(data) == 0:
        return [b""]
    return [data[i:i + chunk_size] for i in range(0, len(data), chunk_size)]


def run_server(port: int, segment_size: int, serve_dir: str):
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

    try:
        sock.bind(("", port))
        log(f"Listening on UDP port {port}")

        raw_data, client_addr = sock.recvfrom(65535)
        packet = unpack_packet(raw_data)

        if not packet:
            log("ERROR: malformed packet received")
            return

        connection_id, request_seq, message_type, _, payload = packet

        if message_type != MESSAGE_TYPES.REQUEST:
            log(f"ERROR: unexpected message type: {message_type.name}")
            return

        filename = payload.decode("utf-8")
        file_path = Path(serve_dir) / filename

        log(f"Received REQUEST for '{filename}' from {client_addr}")

        if not file_path.exists() or not file_path.is_file():
            error_packet = pack_packet(
                connection_id,
                request_seq,
                MESSAGE_TYPES.ERROR,
                False,
                b"file not found",
            )
            sock.sendto(error_packet, client_addr)
            log("Sent ERROR: file not found")
            return

        with open(file_path, "rb") as f:
            file_content = f.read()

        chunks = split_into_chunks(file_content, segment_size)
        server_seq_num = 0
        sock.settimeout(2)

        for idx, chunk in enumerate(chunks):
            is_final = (idx == len(chunks) - 1)

            data_packet = pack_packet(
                connection_id,
                server_seq_num,
                MESSAGE_TYPES.DATA,
                is_final,
                chunk,
            )

            while True:
                sock.sendto(data_packet, client_addr)
                log(
                    f"Sent {idx}-th DATA packet: seq={server_seq_num}, "
                    f"bytes={len(chunk)}, is_final={is_final}"
                )
                try:
                    ack_raw, ack_addr = sock.recvfrom(65535)
                    ack_packet = unpack_packet(ack_raw)
                except socket.timeout:
                    log(f"Timeout waiting for ACK for seq={server_seq_num}, retransmitting")
                    continue

                if ack_addr != client_addr:
                    log(f"ERROR: ACK came from unexpected sender {ack_addr}")
                    continue

                if not ack_packet:
                    log("ERROR: malformed ACK received")
                    continue

                ack_conn_id, ack_seq, ack_type, _, _ = ack_packet

                if ack_conn_id != connection_id:
                    log("ERROR: ACK connection_id does not match")
                    continue

                if ack_type != MESSAGE_TYPES.ACK:
                    log(f"ERROR: expected ACK, got {ack_type.name}")
                    continue

                if ack_seq != server_seq_num:
                    log(
                        f"ERROR: ACK sequence number mismatch "
                        f"(got {ack_seq}, expected {server_seq_num})"
                    )
                    continue

                log(f"ACK received for packet {idx} (seq={server_seq_num})")
                break
            
            if is_final:
                log("Transmission complete")
                return
            server_seq_num ^= 1

    finally:
        sock.close()
        log("Socket closed")


def main():
    parser = argparse.ArgumentParser(description="UDP File Transfer Server")
    parser.add_argument("port", type=int, help="Server UDP port")
    parser.add_argument(
        "--segment-size",
        type=int,
        required=True,
        help="Max file bytes per DATA packet",
    )

    args = parser.parse_args()

    if args.segment_size <= 0:
        print("ERROR: --segment-size must be greater than 0")
        sys.exit(1)

    serve_dir = Path("./files/sent")
    if not serve_dir.is_dir():
        print(f"ERROR: '{serve_dir.resolve()}' is not a directory.")
        sys.exit(1)

    try:
        run_server(args.port, args.segment_size, str(serve_dir))
    except KeyboardInterrupt:
        log("Shutting down.")


if __name__ == "__main__":
    main()