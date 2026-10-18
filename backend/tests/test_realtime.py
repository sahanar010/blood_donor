"""Hub tests with fake sockets (no FastAPI/Redis needed)."""
import asyncio
import unittest

from app.realtime import Hub


class FakeWS:
    def __init__(self, fail=False):
        self.sent, self.fail = [], fail

    async def send_json(self, data):
        if self.fail:
            raise RuntimeError("closed")
        self.sent.append(data)


async def settle():
    await asyncio.sleep(0.05)


class HubTests(unittest.TestCase):
    def run_async(self, coro):
        return asyncio.run(coro)

    def test_event_reaches_only_the_target_user(self):
        async def go():
            hub, a, b = Hub(), FakeWS(), FakeWS()
            await hub.start()
            await hub.connect(1, a)
            await hub.connect(2, b)
            await asyncio.to_thread(hub.publish, 1, {"type": "request.new", "data": {"x": 1}})
            await settle()
            self.assertEqual(len(a.sent), 1)
            self.assertEqual(a.sent[0]["type"], "request.new")
            self.assertIn("ts", a.sent[0])
            self.assertEqual(b.sent, [])
        self.run_async(go())

    def test_all_tabs_of_one_user_receive(self):
        async def go():
            hub, t1, t2 = Hub(), FakeWS(), FakeWS()
            await hub.start()
            await hub.connect(1, t1)
            await hub.connect(1, t2)
            await asyncio.to_thread(hub.publish, 1, {"type": "x"})
            await settle()
            self.assertEqual((len(t1.sent), len(t2.sent)), (1, 1))
        self.run_async(go())

    def test_dead_socket_is_dropped_and_others_still_get_event(self):
        async def go():
            hub, dead, ok = Hub(), FakeWS(fail=True), FakeWS()
            await hub.start()
            await hub.connect(1, dead)
            await hub.connect(1, ok)
            await asyncio.to_thread(hub.publish, 1, {"type": "x"})
            await settle()
            self.assertEqual(len(ok.sent), 1)
            self.assertNotIn(dead, hub._conns[1])
        self.run_async(go())

    def test_presence_follows_connect_and_disconnect(self):
        async def go():
            hub, ws = Hub(), FakeWS()
            await hub.start()
            self.assertEqual(hub.online_user_ids([1, 2]), set())
            await hub.connect(1, ws)
            self.assertEqual(hub.online_user_ids([1, 2]), {1})
            await hub.disconnect(1, ws)
            self.assertEqual(hub.online_user_ids([1, 2]), set())
        self.run_async(go())

    def test_publish_to_offline_user_is_a_silent_noop(self):
        async def go():
            hub = Hub()
            await hub.start()
            await asyncio.to_thread(hub.publish, 99, {"type": "x"})
            await settle()
        self.run_async(go())

    def test_publish_before_start_never_raises(self):
        Hub().publish(1, {"type": "x"})

    def test_unreachable_redis_falls_back_to_memory(self):
        async def go():
            hub, ws = Hub(), FakeWS()
            await hub.start("redis://127.0.0.1:1/0")   # nothing listens there (or redis not installed)
            self.assertIsNone(hub._redis_pub)
            await hub.connect(1, ws)
            await asyncio.to_thread(hub.publish, 1, {"type": "x"})
            await settle()
            self.assertEqual(len(ws.sent), 1)
            await hub.stop()
        self.run_async(go())


if __name__ == "__main__":
    unittest.main()
