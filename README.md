# UDP Reliable File Transfer

Application-layer reliable file transfer over UDP using a stop-and-wait ARQ protocol.

This project implements a simple but robust sender/receiver pair:

- `server.py` serves files from `files/sent/`
- `client.py` requests files and writes them to `files/received/`
- `common.py` defines the packet format and serialization/deserialization logic

## Features

- Reliable transfer over UDP with retransmissions on timeout
- Alternating-bit sequencing (`0/1`) for stop-and-wait flow control
- Explicit ACK packets
- Basic error signaling (`ERROR` packet when file is not found)
- Duplicate/out-of-order handling
- Short final-state hold on the server to handle duplicate final ACK/REQUEST safely

## Project Structure

```text
.
├── client.py
├── common.py
├── server.py
├── files/
│   ├── sent/
│   └── received/
├── result_validator/
│   └── validator.py
└── tests/
	 ├── segment_100.sh
	 └── segment_512.sh
```

## Protocol Definition

Packets contain a fixed-size header followed by payload.

### Header Layout

Defined in `common.py`:

- `HEADER_FORMAT = "!IIBBH"` (network byte order, big-endian)
- Total header size: 12 bytes

Fields:

1. `connection_id` (`I`, 4 bytes)
2. `sequence_number` (`I`, 4 bytes)
3. `message_type` (`B`, 1 byte)
4. `is_final` (`B`, 1 byte)
5. `payload_length` (`H`, 2 bytes)

Message types (`MESSAGE_TYPES` enum):

- `REQUEST = 1`
- `DATA = 2`
- `ACK = 3`
- `ERROR = 4`

### Packet Rules

- `REQUEST` payload: UTF-8 filename
- `DATA` payload: file bytes for one segment
- `ACK` payload: empty bytes (`b""`)
- `ERROR` payload: UTF-8 error message

`unpack_packet` validates:

- incoming data length is at least header size
- payload size exactly matches `payload_length`

Malformed packets are ignored.

## Stop-and-Wait Behavior

### Client (`client.py`)

1. Generates random 32-bit `connection_id`
2. Sends `REQUEST` up to 3 attempts (2s timeout each)
3. Expects first valid response from server with matching `connection_id`
4. On each `DATA` packet:
	- validates sender and `connection_id`
	- checks expected alternating sequence number (`0 -> 1 -> 0 ...`)
	- writes payload to output file
	- sends matching `ACK`
5. If packet is duplicate/out-of-order, sends ACK for received sequence and continues
6. Stops when `is_final=True` packet is processed

### Server (`server.py`)

1. Listens for `REQUEST` packets
2. Validates requested filename in `files/sent/`
3. If missing: sends `ERROR` (`"file not found"`)
4. Splits file into chunks of `--segment-size`
5. Sends one `DATA` packet and waits for correct `ACK`
6. On timeout (2s): retransmits same `DATA`
7. Sequence number alternates using XOR (`seq ^= 1`)
8. After final packet ACK, holds transfer state for 3 seconds:
	- duplicate final ACK -> resend final DATA
	- duplicate REQUEST for same file and connection -> resend final DATA

## Requirements

- Python 3.10+
- No external Python packages required (standard library only)

`requirements.txt` is intentionally empty.

## Setup

Optional virtual environment:

```bash
python3 -m venv venv
source venv/bin/activate
```

Create data directories if needed:

```bash
mkdir -p files/sent files/received
```

## Usage

Run server:

```bash
python3 server.py 9000 --segment-size 512
```

Run client (new terminal):

```bash
python3 client.py 127.0.0.1 9000 file1.txt --segment-size 512
```

Equivalent shortcut commands are listed in `runme.sh`.

### CLI Arguments

Server:

```bash
python3 server.py <port> --segment-size <bytes>
```

Client:

```bash
python3 client.py <server_ip> <port> <filename> --segment-size <bytes>
```

Notes:

- `--segment-size` must be greater than 0
- Client and server should use the same segment size for expected behavior in this implementation

## Validation

Single file / all files validator:

```bash
python3 result_validator/validator.py
```

`validator.py` compares text content between `files/sent/` and `files/received/`.

## Included Test Scripts

`tests/segment_100.sh`

- Generates ~500-byte test file
- Runs transfer with segment size 100
- Verifies equality with `cmp`

`tests/segment_512.sh`

- Generates same test file
- Runs transfer with segment size 512
- Verifies equality with `cmp`

## Expected Logs (High Level)

- Server logs packet sends, ACK validation, retransmissions, and final-state hold events
- Client logs request attempts, received packet metadata, ACK behavior, and transfer completion

## Limitations

- Single active transfer flow on one socket loop (no per-client session isolation beyond packet checks)
- File validator currently reads files as UTF-8 text (binary-safe comparison is not implemented there)
- Security features (authentication/encryption) are out of scope

## Quick Demo

1. Place a file in `files/sent/`.
2. Start server on chosen port.
3. Run client to request that file.
4. Confirm output in `files/received/`.
5. Run validator or `cmp` for verification.

