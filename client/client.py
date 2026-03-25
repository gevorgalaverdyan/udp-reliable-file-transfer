import pickle
import socket
from pathlib import Path
from uuid import UUID, uuid4

from models.packet import Packet
from models.utils import Message

# ── tunables ──────────────────────────────────────────────────────────────────
TIMEOUT     = 2.0   # seconds per recvfrom attempt
MAX_RETRIES = 10    # consecutive timeouts before giving up
# ─────────────────────────────────────────────────────────────────────────────


class Client:
    """
    Stop-and-wait UDP client.

    Protocol
    --------
    1. Send REQUEST{filename, max_payload} with connection_id.
       Retransmit on timeout until a DATA or ERROR reply is received.

    2. For each DATA packet:
         • Validate connection_id and seq_num.
         • If seq matches expected  → write payload, send ACK, advance seq.
         • If seq is a duplicate    → re-send last ACK (do NOT write again).
         • If final flag is set     → close file and exit.

    3. While waiting for the next DATA: retransmit the last ACK on each
       timeout.  This prods the server to retransmit when its DATA was lost
       or when the server is waiting for an ACK that never arrived.
    """

    def __init__(
        self,
        server_ip: str,
        port: int,
        filename: str,
        max_payload: int,
    ):
        self.server_ip   = server_ip
        self.port        = port
        self.filename    = filename
        self.max_payload = max_payload
        self.connection_id: UUID = uuid4()


    def start_sending(self) -> None:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.settimeout(TIMEOUT)
        server_addr = (self.server_ip, self.port)

        print(f"[Client] Connection ID : {self.connection_id}")
        print(f"[Client] File          : '{self.filename}'")
        print(f"[Client] Max payload   : {self.max_payload} B")
        print(f"[Client] Server        : {self.server_ip}:{self.port}\n")

        # ── Step 1: send REQUEST, wait for first reply ────────────────────────
        request = Packet(
            self.connection_id,
            seq_num=0,
            msg_type=Message.REQUEST,
            payload={"filename": self.filename, "max_payload": self.max_payload},
        )
        raw_request = pickle.dumps(request)

        first = self._send_and_receive(sock, raw_request, server_addr)
        if first is None:
            print("[Client] No response from server — aborting.")
            sock.close()
            return

        if first.msg_type == Message.ERROR:
            print(f"[Client] Server error: {first.payload}")
            sock.close()
            return

        # ── Step 2: receive DATA packets with stop-and-wait ───────────────────
        output_path  = Path(f"./files/received/{self.filename}")
        expected_seq = 0
        last_ack_raw = None   # raw bytes of last ACK we sent (ready for retransmit)
        count        = 0      # number of valid DATA packets written

        with open(output_path, "wb") as f:
            incoming = first   # first DATA packet already in hand

            while True:
                # ── validate ──────────────────────────────────────────────────
                if incoming.connection_id != self.connection_id:
                    print("[Client] Wrong connection ID — ignoring")

                elif incoming.msg_type != Message.DATA:
                    print(f"[Client] Unexpected type {incoming.msg_type} — ignoring")

                elif incoming.seq_num == expected_seq:
                    # ── valid new DATA ────────────────────────────────────────
                    f.write(incoming.payload)
                    count += 1
                    print(
                        f"[Client] ← DATA [{count}] "
                        f"seq={incoming.seq_num}  {len(incoming.payload)} B  "
                        f"final={incoming.final}"
                    )

                    ack = Packet(
                        self.connection_id,
                        seq_num=incoming.seq_num,
                        msg_type=Message.ACK,
                        payload=None,
                    )
                    last_ack_raw = pickle.dumps(ack)
                    sock.sendto(last_ack_raw, server_addr)
                    print(f"[Client] → ACK  seq={incoming.seq_num}")

                    if incoming.final:
                        print("\n[Client] Final packet received — transfer complete!")
                        break

                    expected_seq ^= 1   # advance only on a valid new packet

                else:
                    # ── duplicate / out-of-order DATA ─────────────────────────
                    print(
                        f"[Client] Duplicate DATA seq={incoming.seq_num} "
                        f"(expected {expected_seq}) — re-sending last ACK"
                    )
                    if last_ack_raw is not None:
                        sock.sendto(last_ack_raw, server_addr)

                # ── wait for next DATA ────────────────────────────────────────
                incoming = self._recv_with_retransmit(sock, last_ack_raw, server_addr)
                if incoming is None:
                    print("[Client] Max retries exceeded — transfer failed.")
                    break

        print(f"\n[Client] Saved to '{output_path}'  ({count} data packet(s))")
        sock.close()

    # HELPERS

    def _send_and_receive(
        self,
        sock: socket.socket,
        raw_packet: bytes,
        server_addr: tuple,
    ) -> "Packet | None":
        """
        Send *raw_packet* then wait up to MAX_RETRIES x TIMEOUT for a reply.
        Re-sends the packet on each timeout.
        """
        for attempt in range(1, MAX_RETRIES + 1):
            sock.sendto(raw_packet, server_addr)
            print(f"[Client] → REQUEST  (attempt {attempt}/{MAX_RETRIES})")
            try:
                raw, _ = sock.recvfrom(65535)
                return pickle.loads(raw)
            except socket.timeout:
                print("[Client]   Timeout — retrying…")
        return None

    def _recv_with_retransmit(
        self,
        sock: socket.socket,
        retransmit_raw: "bytes | None",
        server_addr: tuple,
    ) -> "Packet | None":
        """
        Wait for the next inbound packet.
        On each timeout, re-send *retransmit_raw* (last ACK) so the server
        knows we're still alive and will retransmit its DATA if needed.
        """
        for _ in range(MAX_RETRIES):
            try:
                raw, _ = sock.recvfrom(65535)
                return pickle.loads(raw)
            except socket.timeout:
                print("[Client]   Timeout waiting for DATA — retransmitting last ACK")
                if retransmit_raw is not None:
                    sock.sendto(retransmit_raw, server_addr)
        return None