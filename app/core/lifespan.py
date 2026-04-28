from contextlib import asynccontextmanager
import logging

import httpx
from fastapi import FastAPI

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("app.lifespan.start")
    app.state.http_client = httpx.AsyncClient()
    try:
        yield
    finally:
        logger.info("app.lifespan.shutdown")
        await app.state.http_client.aclose()
