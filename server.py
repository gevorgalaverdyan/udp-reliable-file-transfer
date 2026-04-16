"""
1. Server starts by parsing the inputs and making sure the sending file directory exists
2. calls run_server(...) which creates a UDP socket and starts listening
3. Enters a persistant loop and waits. Server doesn't close after transfer is complete, it needs Keyboard interrupt 
4. Receives packets of 65535 bytes, unpacks it to packet(header+payload)
5. This is the first packet so it will start validating and start streaming the document. Calls handle_request

6. handle_request(...): sends chunk by chunk, validates ack packet, resends on timout
7. Final chunk: keep alive for duplicates...
"""

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
    """
    Chunk the data into the passed segment size

    Returns:
        list: list of chunks
    """
    if len(data) == 0:
        return [b""]
    return [data[i : i + chunk_size] for i in range(0, len(data), chunk_size)]


def run_server(port: int, serve_dir: str):
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

    try:
        sock.bind(("", port))
        log(f"Listening on UDP port {port}")

        while True:
            sock.settimeout(None)  # wait forever for a new REQUEST
            raw_data, client_addr = sock.recvfrom(65535)
            packet = unpack_packet(raw_data)

            if not packet:
                log(f"Ignoring malformed packet from {client_addr}")
                continue

            try:
                handle_request(sock, packet, client_addr, serve_dir)
            except Exception as e:
                log(f"Error while handling request from {client_addr}: {e}")
                continue

    finally:
        sock.close()
        log("Socket closed")


def handle_request(
    sock: socket.socket, packet, client_addr, serve_dir: str
):
    connection_id, request_seq, message_type, _, payload = packet

    if message_type != MESSAGE_TYPES.REQUEST:
        log(f"Ignoring unexpected message type: {message_type.name}")
        return

    if len(payload) < 4:
        log("Ignoring REQUEST with payload too short to contain segment size")
        return

    segment_size = int.from_bytes(payload[:4], "big")
    filename = payload[4:].decode("utf-8")

    if segment_size <= 0:
        log(f"Ignoring REQUEST with invalid segment size: {segment_size}")
        return

    log(f"Received REQUEST for '{filename}' from {client_addr} (segment_size={segment_size})")

    file_path = Path(serve_dir) / filename

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

    # Split to chunks on given segment size 
    chunks = split_into_chunks(file_content, segment_size)
    server_seq_num = 0

    # set timeout in case ACK is lost or timeout happens from client
    sock.settimeout(2)

    # send chunk by chunk
    for idx, chunk in enumerate(chunks):
        is_final = idx == len(chunks) - 1

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
                f"Sent DATA packet {idx}: seq={server_seq_num}, "
                f"bytes={len(chunk)}, is_final={is_final}"
            )

            # wait for ACK, If timeout -> throw exception and resend packet
            try:
                ack_raw, ack_addr = sock.recvfrom(65535)
            except socket.timeout:
                log(f"Timeout waiting for ACK for seq={server_seq_num}, retransmitting")
                continue
                """
                Here we retry sending infinitely, so server is stuck.  can add a retry limit
                """

            ack_packet = unpack_packet(ack_raw)

            # Validate ACK
            if ack_addr != client_addr:
                log(f"Ignoring ACK from unexpected sender {ack_addr}")
                continue

            if not ack_packet:
                log("Ignoring malformed ACK")
                continue

            ack_conn_id, ack_seq, ack_type, _, _ = ack_packet

            if ack_conn_id != connection_id:
                log("Ignoring ACK with wrong connection ID")
                continue

            if ack_type != MESSAGE_TYPES.ACK:
                log(f"Ignoring non-ACK packet while waiting for ACK: {ack_type.name}")
                continue

            # If duplicate/out of order, ignore and resend
            if ack_seq != server_seq_num:
                log(
                    f"Ignoring ACK with wrong sequence number "
                    f"(got {ack_seq}, expected {server_seq_num})"
                )
                continue

            # If all good break and go to next chunk
            log(f"ACK received for packet {idx} (seq={server_seq_num})")
            break

        # If final chunk has been sent, keep state and handle dupl ack/req 
        if is_final:
            log("Final packet acknowledged")
            hold_final_state(
                sock=sock,
                client_addr=client_addr,
                connection_id=connection_id,
                filename=filename,
                final_seq_num=server_seq_num,
                final_data_packet=data_packet,
                hold_seconds=3.0,
            )
            log("Transmission complete")
            return

        server_seq_num ^= 1


def hold_final_state(
    sock: socket.socket,
    client_addr,
    connection_id: int,
    filename: str,
    final_seq_num: int,
    final_data_packet: bytes,
    hold_seconds: float = 3.0,
):
    """
    Keep the transfer state for a short time and then safely discard it
    Re-send the final DATA packet if a duplicate ACK or duplicate REQUEST arrives
    """
    log(f"Holding final transfer state for {hold_seconds} seconds")

    deadline = time.monotonic() + hold_seconds
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            log("Final-state hold expired, discarding transfer state")
            return

        sock.settimeout(remaining)

        try:
            raw_data, addr = sock.recvfrom(65535)
        except socket.timeout:
            log("Final-state hold expired, discarding transfer state")
            return

        packet = unpack_packet(raw_data)
        if not packet:
            continue

        recv_conn_id, seq_num, msg_type, _, payload = packet

        # Only care about duplicates for THIS transfer from THIS client
        if addr != client_addr:
            continue

        if recv_conn_id != connection_id:
            continue
        
        # resend to keep in memory
        if msg_type == MESSAGE_TYPES.ACK:
            if seq_num == final_seq_num:
                log("Duplicate ACK for final packet received, resending final DATA")
                sock.sendto(final_data_packet, client_addr)

        elif msg_type == MESSAGE_TYPES.REQUEST:
            if len(payload) < 4:
                continue

            try:
                requested_name = payload[4:].decode("utf-8")
            except UnicodeDecodeError:
                continue

            if requested_name == filename:
                log("Duplicate REQUEST received, resending final DATA")
                sock.sendto(final_data_packet, client_addr)


def main():
    parser = argparse.ArgumentParser(description="UDP File Transfer Server")
    parser.add_argument("port", type=int, help="Server UDP port")

    args = parser.parse_args()

    serve_dir = Path("./files/sent")
    if not serve_dir.is_dir():
        print(f"ERROR: '{serve_dir.resolve()}' is not a directory.")
        sys.exit(1)

    try:
        run_server(args.port, str(serve_dir))
    except KeyboardInterrupt:
        log("Shutting down.")


if __name__ == "__main__":
    main()
