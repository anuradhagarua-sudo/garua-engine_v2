import sys
from types import ModuleType

# --- TWISTED MOCK: Bypasses C-Compiler Crashes on Android ---
class MockModule(ModuleType):
    def __getattr__(self, name):
        return MockModule(name)

class DummyReconnectingFactory: pass
class DummyWSFactory: pass
class DummyWSProtocol: pass

sys.modules['twisted'] = MockModule('twisted')
sys.modules['twisted.internet'] = MockModule('twisted.internet')
sys.modules['twisted.internet.protocol'] = MockModule('twisted.internet.protocol')
sys.modules['twisted.internet.protocol'].ReconnectingClientFactory = DummyReconnectingFactory
sys.modules['twisted.python'] = MockModule('twisted.python')

sys.modules['autobahn'] = MockModule('autobahn')
sys.modules['autobahn.twisted'] = MockModule('autobahn.twisted')
sys.modules['autobahn.twisted.websocket'] = MockModule('autobahn.twisted.websocket')
sys.modules['autobahn.twisted.websocket'].WebSocketClientProtocol = DummyWSProtocol
sys.modules['autobahn.twisted.websocket'].WebSocketClientFactory = DummyWSFactory
sys.modules['autobahn.twisted.websocket'].connectWS = lambda *args, **kwargs: None
# -----------------------------------------------------------
