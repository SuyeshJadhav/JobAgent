import sys
from unittest.mock import MagicMock

sys.modules["scrapling"] = MagicMock()
sys.modules["scrapling.fetchers"] = MagicMock()
sys.modules["scrapling.fetchers"].DynamicFetcher = MagicMock()
sys.modules["scrapling.fetchers"].StealthyFetcher = MagicMock()

# Mock chromadb to prevent real SQLite files from being created in tests
sys.modules["chromadb"] = MagicMock()
sys.modules["chromadb.utils"] = MagicMock()
sys.modules["chromadb.utils.embedding_functions"] = MagicMock()
