import argparse
import sys
import threading

from client.client import Client
from server.server import Server


def main() -> int:
    print("***************")
    print("* UDP program *")
    print("***************\n")

    parser = argparse.ArgumentParser(
        description="Stop-and-Wait UDP File Transfer",
        formatter_class=argparse.RawTextHelpFormatter,
    )
    parser.add_argument(
        "-i", "--server_ip",
        required=True, metavar="IP",
        help="IP address of the server (e.g. 127.0.0.1)",
    )
    parser.add_argument(
        "-p", "--port",
        required=True, metavar="PORT", type=int,
        help="UDP port number (1-65535)",
    )
    parser.add_argument(
        "-f", "--filename",
        required=True, metavar="FILE",
        help="Name of the file to retrieve from the server",
    )
    parser.add_argument(
        "-m", "--max_payload",
        required=True, metavar="BYTES", type=int,
        help="Maximum payload size in bytes per DATA packet",
    )

    args = parser.parse_args()

    if not (1 <= args.port <= 65535):
        parser.error(f"Port must be 1-65535, got {args.port}")
    if args.max_payload <= 0:
        parser.error(f"Max payload must be a positive integer, got {args.max_payload}")

    server = Server(args.server_ip, args.port)
    client = Client(args.server_ip, args.port, args.filename, args.max_payload)

    ready = threading.Event()
    server_thread = threading.Thread(
        target=server.start_listener,
        args=(ready,),
        daemon=True,
    )
    server_thread.start()

    ready.wait()
    print()

    client.start_sending()
    return 0


if __name__ == "__main__":
    sys.exit(main())