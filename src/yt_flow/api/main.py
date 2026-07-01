import json
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from pydantic import BaseModel

from yt_flow import db
from yt_flow.api.routes import runs
from yt_flow.config import Settings


class ScpEntry(BaseModel):
    id: str
    nickname: str
    object_class: str
    rating: float


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = Settings()
    db.init(f"sqlite:///{settings.db_path}")
    app.state.workspace_path = str(Path(settings.workspace_path).resolve())
    scps_path = Path(__file__).parents[3] / "data" / "scps.json"
    app.state.scps = [ScpEntry(**s) for s in json.loads(scps_path.read_text())]
    yield


app = FastAPI(title="yt.flow API", lifespan=lifespan)
app.include_router(runs.router)
