import json
import os
import time
import requests

RPC_URL = os.getenv("RPC_URL", "https://data-seed-prebsc-1-s1.bnbchain.org:8545")
CURSOR_FILE = os.getenv("CURSOR_FILE", "cursor.json")
CONFIRMATIONS = int(os.getenv("CONFIRMATIONS", "3"))
SLEEP_SECONDS = int(os.getenv("SLEEP_SECONDS", "3"))



def rpc(method, params=None):
    payload = {
        "jsonrpc": "2.0",
        "method": method,
        "params": params or [],
        "id": 1,
    }

    r = requests.post(RPC_URL, json=payload, timeout=10)
    r.raise_for_status()
    data = r.json()

    if "error" in data:
        raise RuntimeError(data["error"])

    return data["result"]


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
    return rpc("eth_getBlockByNumber", [hex(block_number), True])


def main():
    cursor = load_cursor()

    if cursor is None:
        head = hex_to_int(rpc("eth_blockNumber"))
        cursor = head - 10
        save_cursor(cursor)

    print(f"Starting from block: {cursor}")

    while True:
        head = hex_to_int(rpc("eth_blockNumber"))
        safe_head = head - CONFIRMATIONS

        if cursor >= safe_head:
            print(f"No new safe blocks. head={head}, cursor={cursor}")
            time.sleep(SLEEP_SECONDS)
            continue

        next_block = cursor + 1
        block = get_block(next_block)

        tx_count = len(block.get("transactions", []))

        print(
            f"processed block={next_block} "
            f"tx_count={tx_count} "
            f"head={head} "
            f"lag={head - next_block}"
        )

        save_cursor(next_block)
        cursor = next_block


if __name__ == "__main__":
    main()
