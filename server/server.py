import pickle
import queue
import socket
import threading
import time
from pathlib import Path
from uuid import UUID

from models.packet import Packet
from models.utils import Message

# ── tunables ──────────────────────────────────────────────────────────────────
RETRANSMIT_TIMEOUT = 2.0   # seconds to wait for ACK before retransmitting DATA
FINAL_LINGER_TIME  = 10.0  # seconds to keep state after the final ACK is received
# ─────────────────────────────────────────────────────────────────────────────


class TransferHandler(threading.Thread):
    """
    Runs in its own thread and drives a single file transfer.

    Protocol (stop-and-wait, alternating bit):
      1. Send DATA[seq]
      2. Wait RETRANSMIT_TIMEOUT seconds for ACK[seq]
         • Timeout  → retransmit DATA[seq]
         • Wrong seq ACK → retransmit DATA[seq]
         • Correct ACK   → advance to next chunk, flip seq bit
      3. After the final ACK: enter linger phase.
         Any ACK or duplicate REQUEST that arrives during linger causes
         the final DATA to be re-sent (client may not have received it).
    """

    def __init__(
        self,
        server_socket: socket.socket,
        conn_id: UUID,
        chunks: list,
        client_address: tuple,
    ):
        super().__init__(daemon=True)
        self.server_socket  = server_socket
        self.conn_id        = conn_id
        self.chunks         = chunks
        self.client_address = client_address

        # ACKs delivered here by the main listener thread
        self._ack_queue: queue.Queue = queue.Queue()
        # Set to True once every chunk has been acknowledged
        self._finished = threading.Event()

        # Pre-compute seq_num of the final packet for use during linger
        self._final_seq: int = (len(chunks) - 1) % 2


    @property
    def is_done(self) -> bool:
        return self._finished.is_set()

    def enqueue_ack(self, packet: Packet) -> None:
        """Deliver an inbound ACK packet to this handler's receive queue."""
        self._ack_queue.put(packet)


    def run(self) -> None:
        seq_num  = 0
        n_chunks = len(self.chunks)

        for idx, chunk in enumerate(self.chunks):
            is_final   = idx == n_chunks - 1
            data_packet = Packet(
                self.conn_id,
                seq_num=seq_num,
                msg_type=Message.DATA,
                payload=chunk,
                final=is_final,
            )
            raw = pickle.dumps(data_packet)

            while True:
                self.server_socket.sendto(raw, self.client_address)
                print(
                    f"[Server] → DATA [{idx + 1}/{n_chunks}] "
                    f"seq={seq_num}  {len(chunk)} B  final={is_final}"
                )

                try:
                    ack = self._ack_queue.get(timeout=RETRANSMIT_TIMEOUT)
                except queue.Empty:
                    print(f"[Server] Timeout — retransmitting DATA seq={seq_num}")
                    continue

                if ack.seq_num == seq_num:
                    print(f"[Server] ✓ ACK seq={seq_num}")
                    break          # correct ACK → advance to next chunk
                else:
                    print(
                        f"[Server] Unexpected ACK seq={ack.seq_num} "
                        f"(expected {seq_num}) — retransmitting"
                    )

            seq_num ^= 1   # flip 0→1 or 1→0

        # ── all chunks delivered and acknowledged ─────────────────────────────
        print(f"[Server] Transfer complete — connection {self.conn_id}")
        self._finished.set()

        # Keep state for FINAL_LINGER_TIME.  If a late duplicate ACK (or a
        # duplicate REQUEST dispatched from the main thread) arrives, re-send
        # the final DATA so the client can finish cleanly.
        final_raw = pickle.dumps(
            Packet(
                self.conn_id,
                seq_num=self._final_seq,
                msg_type=Message.DATA,
                payload=self.chunks[-1],
                final=True,
            )
        )
        deadline = time.monotonic() + FINAL_LINGER_TIME
        while time.monotonic() < deadline:
            remaining = deadline - time.monotonic()
            try:
                self._ack_queue.get(timeout=min(0.5, remaining))
                # A late ACK arrived — the client may have re-sent it because
                # it didn't receive the final DATA, so send it again.
                self.server_socket.sendto(final_raw, self.client_address)
                print("[Server] Linger: re-sent final DATA packet")
            except queue.Empty:
                pass

        print(f"[Server] Linger expired — discarding state for {self.conn_id}")


# ── Server ────────────────────────────────────────────────────────────────────

class Server:
    def __init__(self, server_ip: str, port: int):
        self.server_ip = server_ip
        self.port      = port
        self._transfers: dict = {}          # UUID → TransferHandler
        self._lock = threading.Lock()

    # ── public entry point ────────────────────────────────────────────────────

    def start_listener(self, ready_event: threading.Event = None) -> None:
        """
        Bind the UDP socket and loop forever dispatching inbound packets.
        If *ready_event* is supplied it is set as soon as the socket is bound,
        so the caller can start the client at exactly the right moment.
        """
        server_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        server_socket.bind((self.server_ip, self.port))
        print(f"[Server] Listening on {self.server_ip}:{self.port}")

        if ready_event is not None:
            ready_event.set()

        while True:
            try:
                raw, client_address = server_socket.recvfrom(65535)
                packet: Packet = pickle.loads(raw)
            except Exception as exc:
                print(f"[Server] Receive error: {exc}")
                continue

            self._dispatch(server_socket, packet, client_address)

    # ── internal helpers ──────────────────────────────────────────────────────

    def _dispatch(
        self,
        sock: socket.socket,
        packet: Packet,
        addr: tuple,
    ) -> None:
        """Route an inbound packet to the correct handler."""
        if packet.msg_type == Message.REQUEST:
            self._handle_request(sock, packet, addr)

        elif packet.msg_type == Message.ACK:
            with self._lock:
                handler = self._transfers.get(packet.connection_id)
            if handler is not None:
                handler.enqueue_ack(packet)
            else:
                print(f"[Server] ACK for unknown connection {packet.connection_id}")

    def _handle_request(
        self,
        sock: socket.socket,
        packet: Packet,
        addr: tuple,
    ) -> None:
        conn_id = packet.connection_id

        # ── duplicate REQUEST for an existing transfer ────────────────────────
        with self._lock:
            existing = self._transfers.get(conn_id)

        if existing is not None:
            if existing.is_done:
                # Transfer finished but client re-sent REQUEST (its final ACK
                # may have been lost). Re-send the final DATA packet.
                final_pkt = Packet(
                    conn_id,
                    seq_num=existing._final_seq,
                    msg_type=Message.DATA,
                    payload=existing.chunks[-1],
                    final=True,
                )
                sock.sendto(pickle.dumps(final_pkt), addr)
                print("[Server] Duplicate REQUEST — re-sent final DATA")
            else:
                print("[Server] Duplicate REQUEST for active transfer — ignored")
            return

        # ── new transfer ──────────────────────────────────────────────────────
        payload     = packet.payload
        filename    = payload["filename"]
        max_payload = payload["max_payload"]

        file_path = Path("./files/sent") / filename
        if not file_path.exists():
            err = Packet(
                conn_id,
                seq_num=0,
                msg_type=Message.ERROR,
                payload=f"File not found: {filename}",
            )
            sock.sendto(pickle.dumps(err), addr)
            print(f"[Server] File not found: '{filename}'")
            return

        file_data = file_path.read_bytes()
        chunks = [
            file_data[i: i + max_payload]
            for i in range(0, len(file_data), max_payload)
        ]
        print(
            f"[Server] '{filename}'  {len(file_data)} bytes → "
            f"{len(chunks)} chunk(s) of ≤{max_payload} B"
        )

        handler = TransferHandler(sock, conn_id, chunks, addr)
        with self._lock:
            self._transfers[conn_id] = handler
        handler.start()