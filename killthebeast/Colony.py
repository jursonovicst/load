from threading import Thread, Event, Lock
from multiprocessing.connection import Listener, wait
from killthebeast import Egg


class Msg(object):

    def __init__(self, msg: str):
        self._msg = msg

    def __str__(self):
        return self._msg


class Cmd(object):
    _EXECUTE = 0
    _TERMINATE = 1

    def __init__(self, command):
        self._command = command

    @classmethod
    def kick(cls):
        return cls(cls._EXECUTE)

    def iskick(self):
        return self._command == self._EXECUTE

    @classmethod
    def terminate(cls):
        return cls(cls._TERMINATE)

    def isterminate(self):
        return self._command == self._TERMINATE


class Colony(Thread):

    def __init__(self, address, port=None):
        super().__init__()

        self._conns = []
        self._connptr = 0
        self._connlock = Lock()

        self._stopevent = Event()

        self._listenerthread = Thread(target=self._listen, args=(address, port,))
        self._listenerthread.start()

        self.start()

    def _listen(self, address, port):
        with Listener(address=address if port is None else (address, port),
                      family='AF_UNIX' if port is None else 'AF_INET') as listener:
            self._log("listening on %s" % (address if port is None else ("%s:%d" % (address, port))))

            while not self._stopevent.isSet():
                conn = listener.accept()
                self._log("accepts connection from %s" % listener.last_accepted)
                self._connlock.acquire()
                self._conns.append(conn)
                self._connlock.release()
        self._log("ended listening on %s" % (self.SOCK if address is None else ("%s:%d" % (address, port))))

    def run(self):
        self._log("waiting for messages")
        while not self._stopevent.isSet():
            self._connlock.acquire()
            if self._conns:
                for conn in wait(self._conns, timeout=0.1):
                    try:
                        msg = conn.recv()
                        print(msg)
                    except EOFError:
                        self._log("removes connection")
                        self._conns.remove(conn)
                        if not self._conns:
                            # no more connection
                            self._stopevent.set()

            self._connlock.release()
        self._log("exits")

    def _send(self, o):
        self._conns[self._connptr].send(o)
        self._connptr = (self._connptr + 1) % len(self._conns)

    def _sendtoall(self, o):
        for conn in self._conns:
            conn.send(o)

    def execute(self):
        self._sendtoall(Cmd.kick())

        # wait for the stop event (all nests quit)
        self._stopevent.wait()

    def terminate(self):
        self._sendtoall(Cmd.terminate())

    def addegg(self, egg: Egg):
        self._send(egg)

    def _log(self, msg):
        print("%s: %s" % (self.__class__.__name__, msg))