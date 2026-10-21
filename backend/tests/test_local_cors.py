"""Local browser requests work after updating Starlette, with origins restricted."""
import inspect

import pytest
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.testclient import TestClient

from backend.app import _configure_cors


@pytest.mark.parametrize("origin,allowed", [("http://127.0.0.1:5173", True), ("https://untrusted.example", False)])
def test_local_private_network_preflight(origin, allowed):
    if "allow_private_network" not in inspect.signature(CORSMiddleware).parameters:
        pytest.skip("Starlette predates private network preflights")
    app = FastAPI()
    _configure_cors(app)
    with TestClient(app) as client:
        response = client.options('/profiles', headers={
            'Origin': origin,
            'Access-Control-Request-Method': 'GET',
            'Access-Control-Request-Headers': 'content-type',
            'Access-Control-Request-Private-Network': 'true',
        })
    assert response.status_code == (200 if allowed else 400)
    assert response.headers.get('access-control-allow-origin') == (origin if allowed else None)
