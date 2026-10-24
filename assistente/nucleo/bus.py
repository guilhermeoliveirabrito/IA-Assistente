"""Canal de eventos em tempo real (do servidor para a interface, via SSE)."""
import queue
import threading
import time

MAX_QUEUE = 500


class Bus:
    def __init__(self):
        self._subs = set()
        self._lock = threading.Lock()

    def subscribe(self) -> "queue.Queue":
        q = queue.Queue(maxsize=MAX_QUEUE)
        with self._lock:
            self._subs.add(q)
        return q

    def unsubscribe(self, q):
        with self._lock:
            self._subs.discard(q)

    def publish(self, event: dict):
        event = {**event, "ts": time.time()}
        with self._lock:
            subs = list(self._subs)
        for q in subs:
            try:
                q.put_nowait(event)
            except queue.Full:
                # assinante lento: descarta o evento mais antigo para não travar quem publica
                try:
                    q.get_nowait()
                    q.put_nowait(event)
                except (queue.Empty, queue.Full):
                    pass

    @property
    def subscribers(self) -> int:
        with self._lock:
            return len(self._subs)
