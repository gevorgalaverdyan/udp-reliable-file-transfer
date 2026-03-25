
#!/usr/bin/env python3
"""
UDP File Transfer — Server
==========================
Usage:
    python3 server/server.py [--port PORT] [--dir SERVE_DIR] [--timeout SEC]

The server listens for REQUEST packets, reads the requested file from SERVE_DIR,
and streams it to the client using stop-and-wait ARQ over UDP.
No threads are used; all I/O is handled with select().
"""

import argparse
import os
import random
import select
import socket
import sys
import time

# Allow running as  python3 server/server.py  from any working directory
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from protocol import (
    DEFAULT_PORT, DEFAULT_SEGMENT_SIZE, DEFAULT_TIMEOUT, MAX_RETRIES,
    FLAG_FINAL, MSG_REQUEST, MSG_DATA, MSG_ACK, MSG_ERROR,
    pack_packet, unpack_packet, is_final, type_name,
)

# ── Logging helpers ────────────────────────────────────────────────────────────

def log(msg: str):
    ts = time.strftime("%H:%M:%S")
    print(f"[SERVER {ts}] {msg}")


# ── Transfer state ─────────────────────────────────────────────────────────────

class Transfer:
    """Holds all state for one in-progress (or recently completed) transfer."""

    def __init__(self, conn_id: int, addr, chunks: list[bytes], segment_size: int):
        self.conn_id      = conn_id
        self.addr         = addr          # (ip, port) of the client
        self.chunks       = chunks        # list[bytes] – all file segments
        self.total        = len(chunks)
        self.index        = 0             # next chunk to send
        self.seq          = 0             # current sequence number (0/1)
        self.segment_size = segment_size
        self.send_time    = 0.0           # timestamp of last send
        self.retries      = 0
        self.done         = False
        self.done_time    = 0.0           # when we finished (for lingering)
        self.last_packet  = b""           # cached final DATA for retransmit

    def current_packet(self) -> bytes:
        """Build (or return cached) DATA packet for the current chunk."""
        payload = self.chunks[self.index]
        flags   = FLAG_FINAL if self.index == self.total - 1 else 0x00
        return pack_packet(self.conn_id, self.seq, MSG_DATA, flags, payload)


# ── Core server logic ──────────────────────────────────────────────────────────

def run_server(port: int, serve_dir: str, timeout: float):
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(("", port))
    log(f"Listening on UDP port {port}  (serving from '{serve_dir}')")

    # conn_id → Transfer
    transfers: dict[int, Transfer] = {}

    # How long to keep a completed transfer around (seconds)
    LINGER = 5.0

    while True:
        # ── Compute the next select() deadline ────────────────────────────────
        now      = time.monotonic()
        deadline = timeout   # default: wake up after one full timeout

        for xfer in transfers.values():
            if xfer.done:
                continue
            elapsed = now - xfer.send_time
            wait    = timeout - elapsed
            if wait < deadline:
                deadline = wait

        deadline = max(deadline, 0.0)

        readable, _, _ = select.select([sock], [], [], deadline)

        # ── Handle incoming packet ─────────────────────────────────────────────
        if readable:
            data, addr = sock.recvfrom(65535)
            parsed = unpack_packet(data)
            if parsed is None:
                log(f"Malformed packet from {addr}, ignored.")
            else:
                conn_id, seq, msg_type, flags, payload = parsed
                log(f"<-- {type_name(msg_type)}  conn={conn_id:#010x}  "
                    f"seq={seq}  from {addr}")
                _handle_packet(sock, transfers, addr, conn_id, seq,
                               msg_type, payload, serve_dir, timeout)

        # ── Retransmit timeouts ────────────────────────────────────────────────
        now = time.monotonic()
        for xfer in list(transfers.values()):
            if xfer.done:
                # Expire lingering finished transfers
                if now - xfer.done_time > LINGER:
                    log(f"Transfer {xfer.conn_id:#010x} expired, removing state.")
                    del transfers[xfer.conn_id]
                continue

            if now - xfer.send_time >= timeout:
                if xfer.retries >= MAX_RETRIES:
                    log(f"Transfer {xfer.conn_id:#010x}: too many retries, aborting.")
                    del transfers[xfer.conn_id]
                    continue
                xfer.retries  += 1
                xfer.send_time = now
                pkt = xfer.current_packet()
                sock.sendto(pkt, xfer.addr)
                log(f"--> DATA (RETRANSMIT #{xfer.retries})  "
                    f"conn={xfer.conn_id:#010x}  "
                    f"seq={xfer.seq}  chunk {xfer.index+1}/{xfer.total}")


def _handle_packet(sock, transfers, addr, conn_id, seq,
                   msg_type, payload, serve_dir, timeout):
    # ── REQUEST ───────────────────────────────────────────────────────────────
    if msg_type == MSG_REQUEST:
        filename = payload.decode(errors="replace").strip("\x00")
        log(f"    REQUEST for '{filename}' from {addr}")

        # If we already have state for this conn_id, the client is retrying
        # the REQUEST — just retransmit the first DATA packet.
        if conn_id in transfers:
            xfer = transfers[conn_id]
            if xfer.done:
                # Re-send last DATA packet (client may have missed our final)
                sock.sendto(xfer.last_packet, addr)
                log(f"--> DATA (re-send final)  conn={conn_id:#010x}")
            else:
                pkt = xfer.current_packet()
                sock.sendto(pkt, addr)
                log(f"--> DATA (re-send current chunk)  conn={conn_id:#010x}")
            return

        # Read segment size from REQUEST payload footer if embedded,
        # else use default.
        segment_size = DEFAULT_SEGMENT_SIZE
        if b"\x00" in payload:
            parts = payload.split(b"\x00", 1)
            filename = parts[0].decode(errors="replace")
            try:
                segment_size = int(parts[1])
            except (ValueError, IndexError):
                pass

        filepath = os.path.join(serve_dir, filename)
        if not os.path.isfile(filepath):
            err_payload = f"File not found: {filename}".encode()
            pkt = pack_packet(conn_id, 0, MSG_ERROR, 0, err_payload)
            sock.sendto(pkt, addr)
            log(f"--> ERROR  '{filename}' not found")
            return

        # Chunk the file
        with open(filepath, "rb") as f:
            raw = f.read()
        chunks = [raw[i:i+segment_size]
                  for i in range(0, max(len(raw), 1), segment_size)]
        log(f"    File size {len(raw)} bytes → {len(chunks)} chunks "
            f"(segment_size={segment_size})")

        xfer = Transfer(conn_id, addr, chunks, segment_size)
        transfers[conn_id] = xfer

        # Send first chunk immediately
        pkt = xfer.current_packet()
        sock.sendto(pkt, addr)
        xfer.send_time = time.monotonic()
        log(f"--> DATA  conn={conn_id:#010x}  seq={xfer.seq}  "
            f"chunk 1/{xfer.total}  bytes={len(chunks[0])}")
        return

    # ── ACK ───────────────────────────────────────────────────────────────────
    if msg_type == MSG_ACK:
        if conn_id not in transfers:
            log(f"    ACK for unknown conn {conn_id:#010x}, ignored.")
            return

        xfer = transfers[conn_id]

        # Duplicate ACK for the previous segment — retransmit current
        if seq != xfer.seq:
            log(f"    Duplicate/old ACK seq={seq} (expected {xfer.seq}), "
                f"retransmitting chunk {xfer.index+1}/{xfer.total}.")
            pkt = xfer.current_packet()
            sock.sendto(pkt, xfer.addr)
            xfer.send_time = time.monotonic()
            return

        # Correct ACK — advance
        xfer.retries = 0

        if xfer.done:
            log(f"    Transfer already complete, ignoring late ACK.")
            return

        log(f"    ACK accepted for chunk {xfer.index+1}/{xfer.total}")

        # Check if this was the final chunk
        if xfer.index == xfer.total - 1:
            log(f"    All chunks acknowledged — transfer complete!")
            xfer.last_packet = xfer.current_packet()
            xfer.done      = True
            xfer.done_time = time.monotonic()
            return

        # Advance to next chunk
        xfer.index   += 1
        xfer.seq      = 1 - xfer.seq   # flip 0↔1

        pkt = xfer.current_packet()
        sock.sendto(pkt, xfer.addr)
        xfer.send_time = time.monotonic()
        log(f"--> DATA  conn={conn_id:#010x}  seq={xfer.seq}  "
            f"chunk {xfer.index+1}/{xfer.total}  "
            f"bytes={len(xfer.chunks[xfer.index])}")
        return

    # ── Anything else ─────────────────────────────────────────────────────────
    log(f"    Unexpected message type {type_name(msg_type)}, ignored.")


# ── Entry point ───────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="UDP File Transfer Server")
    parser.add_argument("--port",    type=int,   default=DEFAULT_PORT,
                        help=f"UDP port to listen on (default: {DEFAULT_PORT})")
    parser.add_argument("--dir",     type=str,   default=".",
                        help="Directory to serve files from (default: .)")
    parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT,
                        help=f"Retransmit timeout in seconds "
                             f"(default: {DEFAULT_TIMEOUT})")
    args = parser.parse_args()

    serve_dir = os.path.abspath(args.dir)
    if not os.path.isdir(serve_dir):
        print(f"ERROR: '{serve_dir}' is not a directory.")
        sys.exit(1)

    try:
        run_server(args.port, serve_dir, args.timeout)
    except KeyboardInterrupt:
        log("Shutting down.")


if __name__ == "__main__":
    main()