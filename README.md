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
├── frontend/
│   ├── app.py
│   ├── requirements.txt
│   └── templates/
│       └── index.html
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

- `REQUEST` payload: 4-byte big-endian segment size followed by UTF-8 filename
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
2. Sends `REQUEST` up to 3 attempts (2s timeout each); the REQUEST payload carries the client-chosen `segment_size` (4 bytes big-endian) followed by the UTF-8 filename
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
4. Reads `segment_size` from the REQUEST payload (client-configured)
5. Splits file into chunks of that size
6. Sends one `DATA` packet and waits for correct `ACK`
7. On timeout (2s): retransmits same `DATA`
8. Sequence number alternates using XOR (`seq ^= 1`)
9. After final packet ACK, holds transfer state for 3 seconds:
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
python3 server.py 9000
```

Run client (new terminal):

```bash
python3 client.py 127.0.0.1 9000 file1.txt --segment-size 512
```

Equivalent shortcut commands are listed in `runme.sh`.

### CLI Arguments

Server:

```bash
python3 server.py <port>
```

Client:

```bash
python3 client.py <server_ip> <port> <filename> --segment-size <bytes>
```

Notes:

- `--segment-size` is configured by the **client** and sent to the server inside the `REQUEST` packet
- `--segment-size` must be greater than 0

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

### Flow
1. Connection setup
The client generates a random 32-bit conn_id, packs a REQUEST packet containing the client-chosen segment_size (4 bytes big-endian) followed by the filename, and sends it to the server. It retries up to 3 times with a 2-second timeout if it doesn't hear back.
2. Server receives the request
The server sits in a blocking loop (settimeout(None)) until a packet arrives. It unpacks it, confirms it's a REQUEST, and looks up the file. If the file doesn't exist, it sends back an ERROR packet and returns to listening. If it does exist, it reads the entire file into memory and splits it into fixed-size chunks based on segment_size.
3. Data transfer (chunk by chunk)
The server sends each chunk as a DATA packet with a sequence number that alternates between 0 and 1 (server_seq_num ^= 1). After sending, it waits for an ACK with the matching sequence number. If the ACK doesn't come within 2 seconds, it retransmits the same DATA packet indefinitely.
On the client side, after receiving the first DATA packet successfully, it enters its own persistent loop. For each packet it validates the conn_id, sender address, message type, and sequence number. If the sequence number matches expected_seq, it writes the payload to the file, sends an ACK, and flips expected_seq. If the sequence number is wrong (duplicate/out-of-order), it still ACKs that sequence number (so the server doesn't get stuck) but doesn't write anything.
The client also tracks consecutive timeouts — if it doesn't receive any data for 5 consecutive timeout periods, it aborts, assuming the server died.
4. Final packet
The last chunk is sent with is_final=True. When the client sees this flag, it writes the data, sends the ACK, and exits.
The server, after receiving the final ACK, enters hold_final_state — it lingers for 3 seconds to handle edge cases. If the client's final ACK was lost and the client retransmits a duplicate ACK or re-sends the original REQUEST, the server re-sends the final DATA packet so the client can complete. After the hold expires, the server goes back to its main loop, ready for the next client.
In short: client requests → server streams chunks one at a time → each chunk is ACK'd before the next is sent → alternating sequence numbers (0, 1, 0, 1…) detect duplicates → final-state hold handles lost last-ACK scenarios.

---

## Web Frontend

A small Flask-based web UI lets you interact with the protocol visually from a browser.

### Features

- **Start / stop** the UDP server with a single click
- **Request file transfers** by selecting a file and setting segment size
- **Live log console** — server and client output streamed in real-time via SSE
- **Packet flow visualiser** — animated dots show REQUEST → DATA → ACK direction
- **Session stats** — counts of DATA packets sent, ACKs, retransmits, and completed transfers

### Screenshot

![UDP Reliable File Transfer – Web Demo](https://github.com/user-attachments/assets/d23d722c-a32a-4a22-b804-f7fed56bfa0f)

### Setup

Install the frontend dependency (Flask):

```bash
pip install -r frontend/requirements.txt
```

Or use a virtual environment:

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r frontend/requirements.txt
```

Make sure the file directories exist:

```bash
mkdir -p files/sent files/received
```

Place at least one file in `files/sent/` to transfer:

```bash
echo "Hello, UDP!" > files/sent/hello.txt
```

### Running the frontend

```bash
python3 frontend/app.py
```

Then open your browser at **http://127.0.0.1:5000**.

Optional flags:

```bash
python3 frontend/app.py --host 0.0.0.0 --port 8080 --debug
```

| Flag | Default | Description |
|------|---------|-------------|
| `--host` | `127.0.0.1` | Bind address for the web server |
| `--port` | `5000` | Port for the web server |
| `--debug` | off | Enable Flask debug/reload mode |

### Usage

1. Open the browser UI at the address above.
2. Under **Server**, set a UDP port and click **Start Server**.
3. Under **Transfer**, choose a file from `files/sent/`, set segment size, and click **Request Transfer**.
4. Watch the **Live Logs** pane and the **Packet Flow** animation update in real time.
5. Received files land in `files/received/` as usual.
