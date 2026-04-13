"""
1. Create output file
2. Create client socket
3. create first packet, try establishing request with SERVER
4. Retry attempt 4 tims with temout of 2.0s
5. unpack first packet from server
6. Validate that packet is DATA, open file, write data, send ack back
    *If first is last, close connection
7. Enter persistant loop and wait for packets
8. Receive packet and validate
9. If ok send ack and negate the seq num || If unexpected seq, send ACK and skip
"""
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
    path_to_output = Path("./files/received") / filename
    path_to_output.parent.mkdir(parents=True, exist_ok=True)

    # Open Socket and instantiate conn_id and server_addr
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    conn_id = random.getrandbits(32)
    server_addr = (server_ip, port)

    log(f"Connection ID: {conn_id}")
    log(
        f"Requesting '{filename}' from {server_ip}:{port} "
        f"(segment_size={segment_size})"
    )

    req_packet = pack_packet(
        conn_id, 0, MESSAGE_TYPES.REQUEST, False, filename.encode()
    )

    expected_seq = 0
    sock.settimeout(2)

    try:
        first_packet = None
        first_addr = None

        for attempt in range(1, 4):
            sock.sendto(req_packet, server_addr)
            log(f"Sent REQUEST attempt {attempt}")

            try:
                raw_data, addr = sock.recvfrom(65535)
            except socket.timeout:
                log("Timeout waiting for first response, retrying...")
                continue

            packet = unpack_packet(raw_data)
            if not packet:
                log("Ignoring malformed first packet")
                continue

            if addr != server_addr:
                log(f"Ignoring packet from unexpected sender {addr}")
                continue

            recv_conn_id, sequence_number, message_type, is_final, payload = packet

            if recv_conn_id != conn_id:
                log(
                    f"Ignoring packet with wrong connection id "
                    f"(got {recv_conn_id}, expected {conn_id})"
                )
                continue

            first_packet = packet
            first_addr = addr
            break

        if first_packet is None:
            log("ERROR: server did not respond after 3 attempts")
            return

        recv_conn_id, sequence_number, message_type, is_final, payload = first_packet

        if message_type == MESSAGE_TYPES.ERROR:
            log(f"MESSAGE ERROR: {payload.decode('utf-8')}")
            return

        if message_type != MESSAGE_TYPES.DATA:
            log(f"Unexpected first packet type: {message_type.name}")
            return

        with open(path_to_output, "wb") as f:
            log(
                f"RECEIVED: seq={sequence_number}, "
                f"payload_size={len(payload)}, is_final={is_final}"
            )

            if sequence_number != expected_seq:
                log(
                    f"Unexpected first sequence number {sequence_number}, "
                    f"expected {expected_seq}"
                )
                return

            f.write(payload)

            ack_packet = pack_packet(
                conn_id, sequence_number, MESSAGE_TYPES.ACK, False, b""
            )
            sock.sendto(ack_packet, first_addr)

            if is_final:
                log("****************************************")
                log("Final packet received, transfer complete")
                log("****************************************")
                return

            expected_seq ^= 1

            data_timeouts = 0
            max_data_timeouts = 5

            while True:
                try:
                    raw_data, addr = sock.recvfrom(65535)
                except socket.timeout:
                    data_timeouts += 1
                    log(f"Timeout waiting for DATA packet ({data_timeouts}/{max_data_timeouts})")
                    if data_timeouts >= max_data_timeouts:
                        log("Too many DATA timeouts, aborting transfer")
                        return
                    continue # -> if there is a timeout dont stop, re-loop and wait for server restransmit
                    # can add retransmit limit
                    # return will stop completely not good
                
                data_timeouts = 0
                
                packet = unpack_packet(raw_data)

                if not packet:
                    log("Ignoring malformed packet")
                    continue

                if addr != server_addr:
                    log(f"Ignoring packet from unexpected sender {addr}")
                    continue

                recv_conn_id, sequence_number, message_type, is_final, payload = packet

                if recv_conn_id != conn_id:
                    log(
                        f"Ignoring packet with wrong connection id "
                        f"(got {recv_conn_id}, expected {conn_id})"
                    )
                    continue

                if message_type == MESSAGE_TYPES.ERROR:
                    log(f"MESSAGE ERROR: {payload.decode('utf-8')}")
                    return

                if message_type != MESSAGE_TYPES.DATA:
                    log(f"Ignoring unexpected packet type: {message_type.name}")
                    continue

                log(
                    f"RECEIVED: seq={sequence_number}, "
                    f"payload_size={len(payload)}, is_final={is_final}"
                )

                # if out of order/dupl ignore and send confirmation that already had received
                # send ack and go back to listen
                if sequence_number != expected_seq:
                    log(
                        f"Duplicate/out-of-order DATA {sequence_number}, "
                        f"expected {expected_seq}"
                    )
                    dup_ack = pack_packet(conn_id, sequence_number, MESSAGE_TYPES.ACK, False, b"")
                    sock.sendto(dup_ack, addr)
                    continue

                f.write(payload)

                ack_packet = pack_packet(
                    conn_id, sequence_number, MESSAGE_TYPES.ACK, False, b""
                )
                sock.sendto(ack_packet, addr)

                if is_final:
                    log("****************************************")
                    log("Final packet received, transfer complete")
                    log("****************************************")
                    break

                expected_seq ^= 1

    finally:
        sock.close()


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
