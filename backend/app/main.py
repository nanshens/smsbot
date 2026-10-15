import logging
import asyncio
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from sqlalchemy.exc import IntegrityError
from . import auth, admin, devices, sim_api
from .db import engine, one
from .scheduler import start_scheduler
from .migrate import migrate


@asynccontextmanager
async def lifespan(app):
    # Uvicorn waits for lifespan startup before accepting HTTP requests.
    await asyncio.to_thread(migrate)
    scheduler = start_scheduler()
    app.state.scheduler = scheduler
    try:
        yield
    finally:
        # Stop scheduling, then let in-flight deliveries commit before exit.
        await asyncio.to_thread(scheduler.shutdown, wait=True)

app = FastAPI(title='SMSBot', version='0.1.0', lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
app.include_router(auth.router)
app.include_router(admin.router)
app.include_router(devices.router)
app.include_router(sim_api.management)
app.include_router(sim_api.router)


@app.middleware('http')
async def headers(request: Request, call_next):
    try:
        length = int(request.headers.get('content-length', '0') or 0)
    except ValueError:
        return JSONResponse({'detail': '无效的请求长度'}, 400)
    if length > 128 * 1024:
        return JSONResponse({'detail': '请求内容过大'}, 413)
    response = await call_next(request)
    response.headers['Cache-Control'] = 'no-store'
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['X-Frame-Options'] = 'DENY'
    response.headers['Referrer-Policy'] = 'no-referrer'
    return response


@app.exception_handler(RequestValidationError)
async def validation_error(request, exc):
    # Pydantic errors may include passwords in their input field.
    return JSONResponse({'detail': '请求参数无效', 'fields': [str(e['loc'][-1]) for e in exc.errors()]}, 422)


@app.exception_handler(IntegrityError)
async def integrity_error(request, exc):
    return JSONResponse({'detail': '数据发生冲突，请刷新后重试'}, 409)


@app.exception_handler(Exception)
async def server_error(request, exc):
    logging.getLogger('smsbot').error('Request failed (%s)', type(exc).__name__)
    return JSONResponse({'detail': '服务暂时不可用，请稍后重试'}, 500)


@app.get('/api/health')
def health():
    with engine().connect() as db:
        one(db, 'SELECT 1 FROM users LIMIT 1')
    return {'status': 'ok'}


@app.get('/api/openapi.json', include_in_schema=False)
def schema(request: Request):
    from .security import current
    with engine().begin() as db:
        current(db, request)
    return app.openapi()
