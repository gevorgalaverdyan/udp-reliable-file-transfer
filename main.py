import argparse
import sys
import threading

from client.client import Client
from server.server import Server

def main():
    print("***************")
    print("* UDP program *")
    print("***************\n")

    parser = argparse.ArgumentParser(description="UDP Client Program")
    parser.add_argument("-i", "--server_ip",                   required=True, metavar="IP",    help="IP address of the server")
    parser.add_argument("-p", "--port",        type=int,       required=True, metavar="PORT",  help="Port number (1-65535)")
    parser.add_argument("-f", "--filename",                    required=True, metavar="FILE",  help="Name of the file to transfer")
    parser.add_argument("-m", "--max_payload", type=int,       required=True, metavar="BYTES", help="Maximum payload size in bytes")

    args = parser.parse_args()

    if not (1 <= args.port <= 65535):
        parser.error(f"Port must be between 1 and 65535, got {args.port}")
    if args.max_payload <= 0:
        parser.error(f"Max payload must be a positive integer, got {args.max_payload}")

    client = Client(args.server_ip, args.port, args.filename, args.max_payload)
    server = Server(args.server_ip, args.port)

    server_thread = threading.Thread(target=server.start_listener, daemon=True)
    server_thread.start()

    client.start_sending() 

    return 0


if __name__ == "__main__":
    sys.exit(main())