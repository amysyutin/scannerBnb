import json
import os
import time
import requests
from prometheus_client import Counter, Gauge, Histogram, start_http_server


RPC_URL = os.getenv("RPC_URL", "https://data-seed-prebsc-1-s1.bnbchain.org:8545")
CURSOR_FILE = os.getenv("CURSOR_FILE", "cursor.json")
CONFIRMATIONS = int(os.getenv("CONFIRMATIONS", "3"))
SLEEP_SECONDS = int(os.getenv("SLEEP_SECONDS", "3"))
HEAD_REFRESH_SECONDS = int(os.getenv("HEAD_REFRESH_SECONDS", "5"))
FULL_TX = os.getenv("FULL_TX", "false").lower() == "true"

METRICS_PORT = int(os.getenv("METRICS_PORT", "8000"))

CHAIN_HEAD = Gauge(
    "bsc_chain_head_block",
    "Latest block number reported by RPC",
)

SAFE_HEAD = Gauge(
    "bsc_safe_head_block",
    "Latest block number considered safe after confirmations",
)

LAST_PROCESSED_BLOCK = Gauge(
    "bsc_scanner_last_processed_block",
    "Last block successfully processed by scanner",
)

SCANNER_LAG = Gauge(
    "bsc_scanner_lag_blocks",
    "Difference between chain head and last processed block",
)

LAST_BLOCK_TX_COUNT = Gauge(
    "bsc_scanner_last_block_tx_count",
    "Transaction count in the last processed block",
)

CURRENT_BLOCK = Gauge(
    "bsc_scanner_current_block",
    "Block currently being processed by scanner",
)

PROCESSED_BLOCKS = Counter(
    "bsc_scanner_processed_blocks_total",
    "Total number of processed blocks",
)

PROCESSED_TRANSACTIONS = Counter(
    "bsc_scanner_processed_transactions_total",
    "Total number of processed transactions",
)

SCANNER_RPC_FAILURES = Counter(
    "bsc_scanner_rpc_failures_total",
    "Total RPC failures by error type",
    ["error_type"],
)

CURRENT_BLOCK_PROCESSING_SECONDS = Gauge(
    "bsc_scanner_current_block_processing_seconds",
    "Processing duration of the current or last processed block in seconds",
)

LAST_SUCCESS_TIMESTAMP = Gauge(
    "bsc_scanner_last_success_timestamp",
    "Unix timestamp of the last successfully processed block",
)

SCANNER_UP = Gauge(
    "bsc_scanner_up",
    "Whether the scanner process is running",
)

RPC_REQUESTS = Counter(
    "bsc_rpc_requests_total",
    "Total RPC requests",
    ["method", "status"],
)

RPC_ERRORS = Counter(
    "bsc_rpc_errors_total",
    "Total RPC errors",
    ["method"],
)

RPC_LATENCY = Histogram(
    "bsc_rpc_request_duration_seconds",
    "RPC request duration in seconds",
    ["method"],
)

BLOCK_PROCESSING_TIME = Histogram(
    "bsc_scanner_block_processing_duration_seconds",
    "Block processing duration in seconds",
)


def rpc_error_type(exc, status):
    if status == "rpc_error":
        return "rpc_error"
    if isinstance(exc, requests.exceptions.Timeout):
        return "timeout"
    if isinstance(exc, requests.exceptions.HTTPError):
        return "http_error"
    if isinstance(exc, requests.exceptions.ConnectionError):
        return "connection_error"
    if isinstance(exc, requests.exceptions.RequestException):
        return "request_error"
    if isinstance(exc, ValueError):
        return "invalid_json"
    return "unknown"


def rpc(method, params=None):
    payload = {
        "jsonrpc": "2.0",
        "method": method,
        "params": params or [],
        "id": 1,
    }

    start = time.time()
    status = "success"

    try:
        r = requests.post(RPC_URL, json=payload, timeout=10)
        r.raise_for_status()
        data = r.json()

        if "error" in data:
            status = "rpc_error"
            raise RuntimeError(data["error"])

        return data["result"]

    except Exception as exc:
        if status == "success":
            status = "error"
        RPC_ERRORS.labels(method=method).inc()
        SCANNER_RPC_FAILURES.labels(error_type=rpc_error_type(exc, status)).inc()
        raise

    finally:
        RPC_REQUESTS.labels(method=method, status=status).inc()
        RPC_LATENCY.labels(method=method).observe(time.time() - start)


def hex_to_int(value):
    return int(value, 16)


def load_cursor():
    if not os.path.exists(CURSOR_FILE):
        return None

    with open(CURSOR_FILE, "r") as f:
        return json.load(f)["last_processed_block"]


def save_cursor(block_number):
    with open(CURSOR_FILE, "w") as f:
        json.dump({"last_processed_block": block_number}, f)


def get_block(block_number):
    return rpc("eth_getBlockByNumber", [hex(block_number), FULL_TX])


def main():
    start_http_server(METRICS_PORT, addr="0.0.0.0")
    print(f"Metrics server started on 0.0.0.0:{METRICS_PORT}")
    SCANNER_UP.set(1)
    cursor = load_cursor()

    head = hex_to_int(rpc("eth_blockNumber"))
    safe_head = head - CONFIRMATIONS
    last_head_refresh = time.time()
    CHAIN_HEAD.set(head)
    SAFE_HEAD.set(safe_head)

    if cursor is None:
        cursor = head - 10
        save_cursor(cursor)

    print(f"Starting from block: {cursor}")

    while True:
        try:
            now = time.time()

            if cursor >= safe_head or now - last_head_refresh >= HEAD_REFRESH_SECONDS:
                head = hex_to_int(rpc("eth_blockNumber"))
                safe_head = head - CONFIRMATIONS
                last_head_refresh = now

                CHAIN_HEAD.set(head)
                SAFE_HEAD.set(safe_head)

            LAST_PROCESSED_BLOCK.set(cursor)
            SCANNER_LAG.set(head - cursor)

            if cursor >= safe_head:
                print(f"No new safe blocks. head={head}, cursor={cursor}")
                time.sleep(SLEEP_SECONDS)
                continue

            next_block = cursor + 1
            CURRENT_BLOCK.set(next_block)

            block_start = time.time()

            with BLOCK_PROCESSING_TIME.time():
                block = get_block(next_block)
                tx_count = len(block.get("transactions", []))

            block_duration = time.time() - block_start

            save_cursor(next_block)
            cursor = next_block

            LAST_PROCESSED_BLOCK.set(next_block)
            SCANNER_LAG.set(head - next_block)
            LAST_BLOCK_TX_COUNT.set(tx_count)
            PROCESSED_BLOCKS.inc()
            PROCESSED_TRANSACTIONS.inc(tx_count)
            LAST_SUCCESS_TIMESTAMP.set(time.time())
            CURRENT_BLOCK_PROCESSING_SECONDS.set(block_duration)

            print(
                f"processed block={next_block} "
                f"tx_count={tx_count} "
                f"head={head} "
                f"lag={head - next_block}"
            )

        except Exception as e:
            print(f"ERROR: {e}")
            SCANNER_UP.set(0)
            time.sleep(SLEEP_SECONDS)
            SCANNER_UP.set(1)


if __name__ == "__main__":
    main()
