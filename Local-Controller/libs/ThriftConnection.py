from thrift.transport import TSocket
from thrift.transport import TTransport
from thrift.protocol import TBinaryProtocol, TMultiplexedProtocol


class ThriftConnection:
    def __init__(self, ip=None, port=9090):
        self.transport = TTransport.TBufferedTransport(
            TSocket.TSocket(ip, port))
        self.protocol = TBinaryProtocol.TBinaryProtocol(self.transport)

        self.transport.open()

    def end(self):
        pass
