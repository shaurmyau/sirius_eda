#!/usr/bin/env python3
"""Нагрузочные проверки практических треков A (1000 промо-запросов) и B (100 WebSocket)."""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import statistics
import time
from datetime import datetime
from pathlib import Path

import httpx
import websockets


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="mode", required=True)

    promo = sub.add_parser("promo", help="Проверить max_uses=1 конкурентными POST /orders/create")
    promo.add_argument("--base-url", default="http://127.0.0.1:8000")
    promo.add_argument("--tokens", default=os.getenv("TRACK_A_TOKENS", ""))
    promo.add_argument("--token", default=os.getenv("TRACK_TOKEN", ""))
    promo.add_argument("--item-id", type=int, default=int(os.getenv("TRACK_ITEM_ID", "1")))
    promo.add_argument("--promo-code", default=os.getenv("TRACK_PROMO_CODE", "RACE1000"))
    promo.add_argument("--requests", type=int, default=1000)
    promo.add_argument("--concurrency", type=int, default=1000)

    ws = sub.add_parser("ws", help="Открыть 100 WS-соединений и измерить доставку order.cancelled")
    ws.add_argument("--base-url", default="http://127.0.0.1:8000")
    ws.add_argument("--token", default=os.getenv("TRACK_TOKEN", ""))
    ws.add_argument("--order-id", type=int, default=int(os.getenv("TRACK_ORDER_ID", "1")))
    ws.add_argument("--connections", type=int, default=100)
    ws.add_argument("--api-pid", type=int, default=None, help="PID API для замера VmRSS в Linux")

    return parser.parse_args()


async def run_promo(args):
    tokens = [item.strip() for item in args.tokens.split(",") if item.strip()]
    if not tokens and args.token:
        tokens = [args.token]
    if not tokens:
        raise SystemExit("Передайте --token или TRACK_TOKEN (можно --tokens / TRACK_A_TOKENS со списком JWT).")

    limits = httpx.Limits(max_connections=args.concurrency, max_keepalive_connections=args.concurrency)
    semaphore = asyncio.Semaphore(args.concurrency)
    results = []

    async with httpx.AsyncClient(base_url=args.base_url.rstrip("/"), timeout=60, limits=limits) as client:
        async def submit(index):
            async with semaphore:
                headers = {"Authorization": f"Bearer {tokens[index % len(tokens)]}"}
                started = time.perf_counter()
                try:
                    response = await client.post(
                        "/orders/create",
                        headers=headers,
                        json={"item_id": args.item_id, "quantity": 1, "promo_code": args.promo_code},
                    )
                    results.append((response.status_code, (time.perf_counter() - started) * 1000))
                except Exception as exc:
                    results.append(("error", str(exc)))

        await asyncio.gather(*(submit(i) for i in range(args.requests)))

    successes = sum(1 for status, _ in results if status == 200)
    failures = len(results) - successes
    latencies = [value for status, value in results if status != "error" and isinstance(value, float)]
    print(json.dumps({
        "requests": len(results), "successful_orders": successes, "rejected_or_failed": failures,
        "http_statuses": {str(code): sum(1 for status, _ in results if status == code)
                          for code, _ in results if code != "error"},
        "latency_ms_avg": round(statistics.mean(latencies), 2) if latencies else None,
        "latency_ms_p95": round(sorted(latencies)[int(0.95 * (len(latencies) - 1))], 2) if latencies else None,
        "expected_successes_for_max_uses_1": 1,
    }, ensure_ascii=False, indent=2))
    if successes != 1:
        raise SystemExit("Проверка не пройдена: для промокода max_uses=1 ожидается ровно один успешный заказ.")


def api_rss_mb(pid: int | None) -> float | None:
    if not pid:
        return None
    status_path = Path(f"/proc/{pid}/status")
    if not status_path.exists():
        return None
    for line in status_path.read_text().splitlines():
        if line.startswith("VmRSS:"):
            return round(int(line.split()[1]) / 1024, 2)
    return None


async def run_websocket(args):
    if not args.token:
        raise SystemExit("Передайте --token или TRACK_TOKEN.")
    base = args.base_url.rstrip("/")
    ws_base = base.replace("https://", "wss://", 1).replace("http://", "ws://", 1)
    uri = f"{ws_base}/ws/orders/{args.order_id}?token={args.token}"
    all_connected = asyncio.Event()
    received_update = asyncio.Event()
    state = {"connected": 0}
    lock = asyncio.Lock()
    latencies: list[float] = []
    errors: list[str] = []

    async def client_worker(index: int):
        try:
            async with websockets.connect(uri, open_timeout=15, ping_interval=None, max_size=65536) as ws:
                first = json.loads(await asyncio.wait_for(ws.recv(), timeout=15))
                if first.get("type") != "snapshot":
                    raise RuntimeError(f"Ожидался snapshot, получено: {first}")
                async with lock:
                    state["connected"] += 1
                    if state["connected"] == args.connections:
                        all_connected.set()

                while True:
                    raw = await asyncio.wait_for(ws.recv(), timeout=30)
                    message = json.loads(raw)
                    if message.get("type") == "ping":
                        await ws.send(json.dumps({"type": "pong"}))
                    elif message.get("type") == "order.status":
                        emitted = datetime.fromisoformat(message["emitted_at"]).timestamp()
                        latencies.append(max(0.0, (time.time() - emitted) * 1000))
                        received_update.set()
                        return
        except Exception as exc:
            errors.append(f"client {index}: {type(exc).__name__}: {exc}")

    before_rss = api_rss_mb(args.api_pid)
    tasks = [asyncio.create_task(client_worker(i)) for i in range(args.connections)]
    try:
        await asyncio.wait_for(all_connected.wait(), timeout=45)
        async with httpx.AsyncClient(base_url=base, timeout=15) as client:
            response = await client.post(
                f"/orders/{args.order_id}/cancel",
                headers={"Authorization": f"Bearer {args.token}"},
            )
        if response.status_code != 200:
            raise SystemExit(f"Не удалось инициировать тестовое изменение статуса: HTTP {response.status_code}: {response.text}")
        await asyncio.wait_for(received_update.wait(), timeout=20)
        await asyncio.wait_for(asyncio.gather(*tasks), timeout=25)
    finally:
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    after_rss = api_rss_mb(args.api_pid)
    print(json.dumps({
        "requested_connections": args.connections,
        "connected_clients": state["connected"],
        "clients_with_status_update": len(latencies),
        "delivery_latency_ms_avg": round(statistics.mean(latencies), 2) if latencies else None,
        "delivery_latency_ms_p95": round(sorted(latencies)[int(0.95 * (len(latencies) - 1))], 2) if latencies else None,
        "api_rss_mb_before": before_rss,
        "api_rss_mb_after": after_rss,
        "api_rss_delta_mb": round(after_rss - before_rss, 2) if before_rss is not None and after_rss is not None else None,
        "client_errors": errors[:10],
    }, ensure_ascii=False, indent=2))
    if state["connected"] != args.connections or len(latencies) != args.connections:
        raise SystemExit("Проверка WS не пройдена: часть клиентов не подключилась или не получила обновление.")


async def main():
    args = parse_args()
    if args.mode == "promo":
        await run_promo(args)
    else:
        await run_websocket(args)


if __name__ == "__main__":
    asyncio.run(main())
