#!/usr/bin/env python3
"""
UDP File Transfer — Client
==========================
Usage:
    python3 client/client.py <server_ip> <port> <filename>
                             [--segment-size BYTES]
                             [--output PATH]
                             [--timeout SEC]

Downloads <filename> from the server using the custom UDP stop-and-wait protocol.
No threads are used; the receive loop is driven by select().
"""

import argparse
import os
import random
import select
import socket
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from protocol import (
    DEFAULT_PORT, DEFAULT_SEGMENT_SIZE, DEFAULT_TIMEOUT, MAX_RETRIES,
    FLAG_FINAL, MSG_REQUEST, MSG_DATA, MSG_ACK, MSG_ERROR,
    pack_packet, unpack_packet, is_final, type_name,
)

# ── Logging ────────────────────────────────────────────────────────────────────

def log(msg: str):
    ts = time.strftime("%H:%M:%S")
    print(f"[CLIENT {ts}] {msg}")


# ── Main transfer logic ────────────────────────────────────────────────────────

def receive_file(server_ip: str, server_port: int, filename: str,
                 segment_size: int, output_path: str, timeout: float):

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.settimeout(timeout)
    server_addr = (server_ip, server_port)

    # Generate a random 32-bit Connection ID for this transfer
    conn_id = random.randint(1, 0xFFFFFFFF)
    log(f"Connection ID: {conn_id:#010x}")
    log(f"Requesting '{filename}' from {server_ip}:{server_port}  "
        f"(segment_size={segment_size})")

    # ── Step 1: Send REQUEST ───────────────────────────────────────────────────
    # Encode segment_size into the REQUEST payload so the server knows
    # how large to make each chunk.
    # Format:  <filename_bytes> \x00 <segment_size_ascii>
    req_payload = filename.encode() + b"\x00" + str(segment_size).encode()
    req_packet  = pack_packet(conn_id, 0, MSG_REQUEST, 0, req_payload)

    expected_seq  = 0       # next sequence number we expect from the server
    retries       = 0
    chunks        = []      # received data payloads in order

    send_time = time.monotonic()
    sock.sendto(req_packet, server_addr)
    log(f"--> REQUEST  conn={conn_id:#010x}")

    # ── Step 2 & 3: Receive DATA packets with stop-and-wait ───────────────────
    while True:
        now     = time.monotonic()
        elapsed = now - send_time
        wait    = max(timeout - elapsed, 0.0)

        readable, _, _ = select.select([sock], [], [], wait)

        # ── Timeout: retransmit the last sent packet ───────────────────────────
        if not readable:
            retries += 1
            if retries > MAX_RETRIES:
                log("ERROR: Too many retries. Server unreachable or transfer stalled.")
                sys.exit(1)

            if not chunks:
                # Still waiting for first DATA — resend REQUEST
                log(f"Timeout #{retries}: resending REQUEST…")
                sock.sendto(req_packet, server_addr)
            else:
                # Waiting for the next DATA — resend our last ACK
                ack_seq = 1 - expected_seq      # seq we already confirmed
                ack_pkt = pack_packet(conn_id, ack_seq, MSG_ACK, 0, b"")
                log(f"Timeout #{retries}: resending ACK seq={ack_seq}…")
                sock.sendto(ack_pkt, server_addr)

            send_time = time.monotonic()
            continue

        # ── Receive a packet ───────────────────────────────────────────────────
        data, addr = sock.recvfrom(65535)
        parsed = unpack_packet(data)

        if parsed is None:
            log("Malformed packet received, ignoring.")
            continue

        p_conn_id, p_seq, p_type, p_flags, payload = parsed

        log(f"<-- {type_name(p_type)}  conn={p_conn_id:#010x}  "
            f"seq={p_seq}  bytes={len(payload)}")

        # ── ERROR from server ──────────────────────────────────────────────────
        if p_type == MSG_ERROR:
            log(f"ERROR from server: {payload.decode(errors='replace')}")
            sys.exit(1)

        # ── Validate connection ID ─────────────────────────────────────────────
        if p_conn_id != conn_id:
            log(f"Wrong connection ID {p_conn_id:#010x}, ignoring.")
            continue

        # ── DATA packet ───────────────────────────────────────────────────────
        if p_type == MSG_DATA:
            if p_seq == expected_seq:
                # ── Valid in-order packet ──────────────────────────────────────
                chunks.append(payload)
                retries = 0
                chunk_num = len(chunks)
                final = is_final(p_flags) or (len(payload) < segment_size)

                log(f"    Chunk #{chunk_num}  {len(payload)} bytes  "
                    f"{'[FINAL]' if final else ''}")

                # Send ACK
                ack_pkt = pack_packet(conn_id, expected_seq, MSG_ACK, 0, b"")
                sock.sendto(ack_pkt, server_addr)
                log(f"--> ACK  seq={expected_seq}")

                if final:
                    # ── Step 4: End of transfer ────────────────────────────────
                    break

                # Flip expected sequence
                expected_seq = 1 - expected_seq
                send_time    = time.monotonic()

            else:
                # ── Duplicate / out-of-order DATA — re-ACK with previous seq ──
                prev_seq = 1 - expected_seq
                ack_pkt  = pack_packet(conn_id, prev_seq, MSG_ACK, 0, b"")
                sock.sendto(ack_pkt, server_addr)
                log(f"    Out-of-order seq={p_seq} (expected {expected_seq}), "
                    f"re-sent ACK seq={prev_seq}")
            continue

        # Ignore anything else
        log(f"Unexpected message type {type_name(p_type)}, ignoring.")

    # ── Write output file ──────────────────────────────────────────────────────
    total_bytes = sum(len(c) for c in chunks)
    log(f"Transfer complete: {len(chunks)} chunks, {total_bytes} bytes total.")

    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
    with open(output_path, "wb") as f:
        for chunk in chunks:
            f.write(chunk)
    log(f"File saved to '{output_path}'.")
    sock.close()


# ── Entry point ────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="UDP File Transfer Client")
    parser.add_argument("server_ip",
                        help="Server IP address (e.g. 127.0.0.1)")
    parser.add_argument("port", type=int,
                        help="Server UDP port")
    parser.add_argument("filename",
                        help="Name of the file to retrieve from the server")
    parser.add_argument("--segment-size", type=int, default=DEFAULT_SEGMENT_SIZE,
                        dest="segment_size",
                        help=f"Max UDP payload bytes per DATA packet "
                             f"(default: {DEFAULT_SEGMENT_SIZE})")
    # parser.add_argument("--output", type=str, default=None,
    #                     help="Local path to save the file "
    #                          "(default: same name as requested file)")
    parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT,
                        help=f"Retransmit timeout in seconds "
                             f"(default: {DEFAULT_TIMEOUT})")
    args = parser.parse_args()

    # output_path = args.output or os.path.basename(args.filename)

    receive_file(
        server_ip    = args.server_ip,
        server_port  = args.port,
        filename     = args.filename,
        segment_size = args.segment_size,
        output_path  = f"./files/received/{args.filename}",
        timeout      = args.timeout,
    )


if __name__ == "__main__":
    main()