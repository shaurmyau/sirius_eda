"""Демо Server Streaming: подписка на TrackDelivery."""
import sys

from app.modules.delivery.grpc_client import DeliveryGrpcClient


def main() -> int:
    if len(sys.argv) < 2:
        print("Usage: python track_delivery.py <delivery_id>")
        return 1
    did = int(sys.argv[1])
    client = DeliveryGrpcClient()
    print(f"== TrackDelivery for delivery_id={did} ==")
    try:
        for upd in client.track_delivery(did):
            print(f"[{upd['timestamp_ms']}] {upd['status']}: {upd['message']}")
    except ConnectionError as e:
        print(f"[UNAVAILABLE] {e}"); return 2
    except TimeoutError as e:
        print(f"[TIMEOUT] {e}");     return 3
    return 0


if __name__ == "__main__":
    sys.exit(main())
