import random
import signal
import sys
import time
from threading import Condition

from tminterface.client import Client, run_client
from tminterface.constants import DEFAULT_SERVER_SIZE
from tminterface.interface import TMInterface

condition = Condition()


inputs = [
    {
        "left": True,
        "right": False,
        "accelerate": False,
        "brake": False,
    },
    {
        "left": True,
        "right": False,
        "accelerate": True,
        "brake": False,
    },
    {
        "left": True,
        "right": False,
        "accelerate": False,
        "brake": True,
    },
    {
        "left": False,
        "right": True,
        "accelerate": False,
        "brake": False,
    },
    {
        "left": False,
        "right": True,
        "accelerate": True,
        "brake": False,
    },
    {
        "left": False,
        "right": True,
        "accelerate": False,
        "brake": True,
    },
    {
        "left": False,
        "right": False,
        "accelerate": False,
        "brake": False,
    },
    {
        "left": False,
        "right": False,
        "accelerate": True,
        "brake": False,
    },
    {
        "left": False,
        "right": False,
        "accelerate": False,
        "brake": True,
    },
]


class MainClient(Client):
    def __init__(self) -> None:
        super(MainClient, self).__init__()
        self.clock = 0

    def on_registered(self, iface: TMInterface) -> None:
        print(f"Registered to {iface.server_name}")

    def on_run_step(self, iface: TMInterface, _time: int):
        print("on_run_step")
        self.clock += 1
        if self.clock % 10 == 0:
            iface.set_speed(0)
            with condition:
                condition.notify_all()


def main():
    server_name = f"TMInterface{sys.argv[1]}" if len(sys.argv) > 1 else "TMInterface0"
    print(f"Connecting to {server_name}...")

    iface = TMInterface(server_name, DEFAULT_SERVER_SIZE)

    def handler(signum, frame):
        iface.close()

    if sys.platform == "win32":
        signal.signal(signal.SIGBREAK, handler)
    signal.signal(signal.SIGINT, handler)

    iface.register(MainClient())

    while not iface.registered:
        time.sleep(0)

    while iface.running:
        with condition:
            condition.wait()
            time.sleep(1)
            iface.set_input_state(random.choice(inputs))
            iface.set_speed(1)
            print("Set Speed 1")


if __name__ == "__main__":
    main()