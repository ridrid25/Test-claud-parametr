"""Registry of per-client marketplace API credentials.

Each client gives you their own Wildberries and Ozon API keys — those
must never be shared across clients (each key only sees that seller's
own data). Credentials are kept in a local JSON file (git-ignored) or
environment variables, never committed to the repo.
"""
import json
import os
from dataclasses import dataclass
from pathlib import Path

CONFIG_PATH = Path(os.environ.get("MP_CLIENTS_CONFIG", "clients.json"))


@dataclass
class ClientCredentials:
    client_id: str
    wb_api_key: str | None = None
    ozon_client_id: str | None = None
    ozon_api_key: str | None = None


def load_clients() -> list[ClientCredentials]:
    """Load all configured clients from CONFIG_PATH.

    Returns an empty list if the file doesn't exist yet (fresh setup).
    """
    if not CONFIG_PATH.exists():
        return []
    data = json.loads(CONFIG_PATH.read_text())
    return [ClientCredentials(**entry) for entry in data]


def get_client(client_id: str) -> ClientCredentials:
    for client in load_clients():
        if client.client_id == client_id:
            return client
    raise KeyError(f"No credentials configured for client_id={client_id!r}")
