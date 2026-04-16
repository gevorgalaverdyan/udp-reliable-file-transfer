"""
Flask web frontend for the UDP Reliable File Transfer demo.

Provides a browser UI to:
  - Start / stop the UDP server
  - Request a file transfer from the UDP client
  - Stream live logs from both processes back to the browser via SSE
"""

import argparse
import json
import queue
import subprocess
import sys
import threading
from pathlib import Path

from flask import Flask, Response, jsonify, render_template, request

app = Flask(__name__)

# ---------------------------------------------------------------------------
# Paths – resolve relative to this file so the app can be launched from any cwd
# ---------------------------------------------------------------------------
ROOT = Path(__file__).parent.parent.resolve()
SENT_DIR = ROOT / "files" / "sent"
RECEIVED_DIR = ROOT / "files" / "received"
SERVER_SCRIPT = ROOT / "server.py"
CLIENT_SCRIPT = ROOT / "client.py"

# ---------------------------------------------------------------------------
# Global server process state
# ---------------------------------------------------------------------------
_server_proc: subprocess.Popen | None = None
_server_lock = threading.Lock()

# ---------------------------------------------------------------------------
# Log broadcast: every SSE subscriber gets its own queue
# ---------------------------------------------------------------------------
_log_subscribers: list[queue.Queue] = []
_subscribers_lock = threading.Lock()


def _broadcast(line: str):
    """Push a log line to every active SSE subscriber."""
    with _subscribers_lock:
        for q in _log_subscribers:
            q.put(line)


def _stream_process(proc: subprocess.Popen, label: str):
    """Read stdout of *proc* line-by-line and broadcast each line."""
    for raw in proc.stdout:
        line = raw.rstrip("\n")
        _broadcast(json.dumps({"label": label, "line": line}))


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/files")
def list_files():
    """Return the list of files available in files/sent/."""
    SENT_DIR.mkdir(parents=True, exist_ok=True)
    files = sorted(
        f.name for f in SENT_DIR.iterdir() if f.is_file()
    )
    return jsonify({"files": files})


@app.route("/api/server/start", methods=["POST"])
def start_server():
    global _server_proc

    data = request.get_json(silent=True) or {}
    port = int(data.get("port", 9000))

    with _server_lock:
        if _server_proc and _server_proc.poll() is None:
            return jsonify({"status": "already_running", "port": port})

        SENT_DIR.mkdir(parents=True, exist_ok=True)

        _server_proc = subprocess.Popen(
            [sys.executable, str(SERVER_SCRIPT), str(port)],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            cwd=str(ROOT),
        )

        threading.Thread(
            target=_stream_process,
            args=(_server_proc, "SERVER"),
            daemon=True,
        ).start()

    return jsonify({"status": "started", "port": port, "pid": _server_proc.pid})


@app.route("/api/server/stop", methods=["POST"])
def stop_server():
    global _server_proc

    with _server_lock:
        if _server_proc is None or _server_proc.poll() is not None:
            return jsonify({"status": "not_running"})

        _server_proc.terminate()
        try:
            _server_proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            _server_proc.kill()

        _server_proc = None

    _broadcast(json.dumps({"label": "SYSTEM", "line": "Server stopped"}))
    return jsonify({"status": "stopped"})


@app.route("/api/server/status")
def server_status():
    with _server_lock:
        running = _server_proc is not None and _server_proc.poll() is None
    return jsonify({"running": running})


@app.route("/api/transfer", methods=["POST"])
def start_transfer():
    """Run the UDP client for one file transfer and stream its logs."""
    data = request.get_json(silent=True) or {}
    server_ip = data.get("server_ip", "127.0.0.1")
    port = int(data.get("port", 9000))
    filename = data.get("filename", "")
    segment_size = int(data.get("segment_size", 512))

    if not filename:
        return jsonify({"error": "filename is required"}), 400
    if segment_size <= 0:
        return jsonify({"error": "segment_size must be > 0"}), 400

    RECEIVED_DIR.mkdir(parents=True, exist_ok=True)

    def run_client():
        proc = subprocess.Popen(
            [
                sys.executable,
                str(CLIENT_SCRIPT),
                server_ip,
                str(port),
                filename,
                "--segment-size",
                str(segment_size),
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            cwd=str(ROOT),
        )
        _stream_process(proc, "CLIENT")
        proc.wait()
        _broadcast(
            json.dumps(
                {
                    "label": "SYSTEM",
                    "line": f"Transfer finished (exit code {proc.returncode})",
                }
            )
        )

    threading.Thread(target=run_client, daemon=True).start()
    return jsonify({"status": "transfer_started"})


@app.route("/api/logs")
def log_stream():
    """Server-Sent Events endpoint – streams log lines to the browser."""
    q: queue.Queue = queue.Queue()

    with _subscribers_lock:
        _log_subscribers.append(q)

    def generate():
        try:
            while True:
                try:
                    item = q.get(timeout=25)
                    yield f"data: {item}\n\n"
                except queue.Empty:
                    # send a heartbeat comment so the connection stays alive
                    yield ": heartbeat\n\n"
        finally:
            with _subscribers_lock:
                try:
                    _log_subscribers.remove(q)
                except ValueError:
                    pass

    return Response(
        generate(),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main():
    parser = argparse.ArgumentParser(description="UDP File Transfer – Web Demo")
    parser.add_argument(
        "--host", default="127.0.0.1", help="Web server host (default: 127.0.0.1)"
    )
    parser.add_argument(
        "--port", type=int, default=5000, help="Web server port (default: 5000)"
    )
    parser.add_argument(
        "--debug", action="store_true", help="Enable Flask debug mode"
    )
    args = parser.parse_args()

    app.run(host=args.host, port=args.port, debug=args.debug)


if __name__ == "__main__":
    main()
