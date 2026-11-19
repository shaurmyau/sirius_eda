"""Демо Bidirectional Streaming: чат с курьером."""
import sys

from app.modules.delivery.grpc_client import DeliveryGrpcClient


def main() -> int:
    if len(sys.argv) < 2:
        print("Usage: python chat_demo.py <delivery_id>")
        return 1
    client = DeliveryGrpcClient()
    print("== ChatWithCourier ==")
    print("Введите сообщение (пустая строка — выход)")

    def user_messages():
        for line in sys.stdin:
            line = line.rstrip("\n")
            if not line:
                return
            yield line

    try:
        for resp in client.chat_with_courier(user_messages()):
            print(f"[{resp['sender']}] {resp['text']}")
    except ConnectionError as e:
        print(f"[UNAVAILABLE] {e}")
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
