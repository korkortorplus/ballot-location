"""FastAPI server – entry point for map_tool.

Run with: uv run python -m map_tool.server
"""

from __future__ import annotations

import asyncio
import json
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .browser import HeadlessBrowser
from .handlers import Dispatcher
from .layers import LayerStore

logger = logging.getLogger("map_tool")
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s"
)

STATIC_DIR = Path(__file__).parent / "static"

# ---- Shared state ----
store = LayerStore()
browser = HeadlessBrowser()
browser_clients: list[WebSocket] = []


async def broadcast(msg: dict) -> None:
    """Send a message to all connected browser WebSocket clients."""
    data = json.dumps(msg, default=str)
    stale: list[WebSocket] = []
    for ws in browser_clients:
        try:
            await ws.send_text(data)
        except Exception:
            stale.append(ws)
    for ws in stale:
        browser_clients.remove(ws)


dispatcher = Dispatcher(store, browser, broadcast)


# ---- Lifespan ----
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Start headless browser after a short delay so the server is up
    async def _start_browser():
        await asyncio.sleep(2)
        try:
            await browser.start()
            logger.info("Headless browser started")
        except Exception:
            logger.exception("Failed to start headless browser")

    task = asyncio.create_task(_start_browser())
    yield
    task.cancel()
    await browser.stop()


app = FastAPI(title="Map Tool", lifespan=lifespan)

# Mount static files
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


# ---- Routes ----
@app.get("/")
async def index():
    return FileResponse(STATIC_DIR / "index.html")


@app.websocket("/ws/agent")
async def ws_agent(websocket: WebSocket):
    """Agent WebSocket – JSON-RPC request/response."""
    await websocket.accept()
    logger.info("Agent connected")
    try:
        while True:
            raw = await websocket.receive_text()
            response = await dispatcher.dispatch(raw)
            await websocket.send_text(response)
    except WebSocketDisconnect:
        logger.info("Agent disconnected")


@app.websocket("/ws/browser")
async def ws_browser(websocket: WebSocket):
    """Browser WebSocket – receives broadcast events."""
    await websocket.accept()
    browser_clients.append(websocket)
    logger.info("Browser client connected (%d total)", len(browser_clients))

    # Send full sync of current state
    layers_data = [store.serialize_for_browser(ly) for ly in store.list_all()]
    await websocket.send_text(json.dumps({"type": "sync", "layers": layers_data}))

    try:
        while True:
            raw = await websocket.receive_text()
            # Handle browser-initiated messages (toggle, remove)
            try:
                msg = json.loads(raw)
                if msg.get("type") == "toggle":
                    layer_id = msg.get("layer_id", "")
                    store.toggle(layer_id)
                elif msg.get("type") == "remove":
                    layer_id = msg.get("layer_id", "")
                    if store.remove(layer_id):
                        await broadcast({"type": "layer_removed", "layer_id": layer_id})
            except Exception:
                pass
    except WebSocketDisconnect:
        browser_clients.remove(websocket)
        logger.info("Browser client disconnected (%d remaining)", len(browser_clients))


# ---- Main ----
def main():
    import uvicorn

    uvicorn.run(
        "map_tool.server:app",
        host="0.0.0.0",
        port=3000,
        log_level="info",
    )


if __name__ == "__main__":
    main()
