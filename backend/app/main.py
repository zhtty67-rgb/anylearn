"""AnyLearn 应用入口：迁移 → 自动安装内容包 → 挂载 API 与前端。

环境变量：
  ANYLEARN_DB_PATH       数据库路径（默认 data/anylearn.db）
  ANYLEARN_CONTENT_ROOT  内容包根目录（默认 ../content-packs）
  ANYLEARN_AUTO_INSTALL  启动时自动安装/升级内容包（默认 1）
"""
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from . import db as db_mod
from .contentpack.loader import install_all
from .routers.api import router

BACKEND_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = BACKEND_ROOT.parent


def _resolve_paths() -> tuple[Path, Path]:
    db_path = Path(os.environ.get('ANYLEARN_DB_PATH', PROJECT_ROOT / 'data' / 'anylearn.db'))
    content_root = Path(os.environ.get('ANYLEARN_CONTENT_ROOT', PROJECT_ROOT / 'content-packs'))
    return db_path, content_root


def create_app(*, db_path: Path | None = None, content_root: Path | None = None,
               auto_install: bool | None = None) -> FastAPI:
    db_path = db_path or _resolve_paths()[0]
    content_root = content_root or _resolve_paths()[1]
    if auto_install is None:
        auto_install = os.environ.get('ANYLEARN_AUTO_INSTALL', '1') not in ('0', 'false', 'no')

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        db_mod.migrate(db_path)
        if auto_install:
            with db_mod.connect(db_path) as db:
                results = install_all(db, content_root)
                for r in results:
                    if r.get('status') == 'error':
                        print(f'[anylearn] 内容包安装失败 {r.get("pack_id")}: {r.get("error")}')
                    elif r.get('status') != 'unchanged':
                        print(f'[anylearn] 内容包{r.get("status")}: {r.get("pack_id")} v{r.get("version")} '
                              f'({r.get("questions")}题/{r.get("nodes")}节点)')
        yield

    app = FastAPI(title='AnyLearn Learning Framework', version='0.1.0', lifespan=lifespan)
    app.state.db_path = str(db_path)
    app.state.content_root = str(content_root)
    app.include_router(router)

    static_dir = BACKEND_ROOT / 'app' / 'static'
    if static_dir.is_dir():
        app.mount('/static', StaticFiles(directory=static_dir), name='static')

        @app.get('/', include_in_schema=False)
        async def index():
            return FileResponse(static_dir / 'index.html')

    @app.get('/api/health')
    def health():
        return {'status': 'ok', 'db': str(db_path), 'content_root': str(content_root)}

    return app


app = create_app()
