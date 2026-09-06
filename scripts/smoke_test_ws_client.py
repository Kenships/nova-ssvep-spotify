"""Throwaway smoke-test client: connects to the backend's command WebSocket
and prints every message for a fixed duration. Used to verify the
simulator -> LSL -> detector -> command_bus -> WS pipeline end-to-end.
"""
import asyncio
import sys

import websockets


async def main(duration_sec: float):
    uri = "ws://127.0.0.1:8000/ws/commands"
    async with websockets.connect(uri) as ws:
        try:
            async with asyncio.timeout(duration_sec):
                async for message in ws:
                    print(message)
        except TimeoutError:
            pass


if __name__ == "__main__":
    asyncio.run(main(float(sys.argv[1]) if len(sys.argv) > 1 else 20.0))
