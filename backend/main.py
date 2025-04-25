# Load environment variables first
from dotenv import load_dotenv

load_dotenv()


from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from routes import screenshot, generate_code, home, evals
from fastapi.staticfiles import StaticFiles
from pathlib import Path
import typing

app = FastAPI(openapi_url=None, docs_url=None, redoc_url=None)

# 获取 backend 目录的绝对路径
static_path = Path(__file__).resolve().parent
outputs_path = static_path / "generated_outputs"

# 挂载静态资源目录：backend/generated_outputs
outputs_path.mkdir(parents=True, exist_ok=True)

# Configure CORS settings
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 添加 COEP 头给 /static 路径的中间件
@app.middleware("http")
async def add_coep_header_for_static(request: Request, call_next: typing.Callable[[Request], typing.Awaitable[Response]]) -> Response:
    response = await call_next(request)
    # 检查请求路径是否以 /static/ 开头
    if request.url.path.startswith("/static/"):
        # 检查响应是否成功并且是 HTML 文件（可选，但更安全）
        # content_type = response.headers.get("content-type")
        # if response.status_code == 200 and content_type and content_type.startswith("text/html"):
        # 设置 COEP 为 credentialless (允许 iframe 加载无 CORP 头的跨域资源)
        response.headers["Cross-Origin-Embedder-Policy"] = "credentialless"
        # 设置 CORP 为 cross-origin (允许主页面嵌入此 iframe)
        response.headers["Cross-Origin-Resource-Policy"] = "cross-origin"
    return response

# 将 StaticFiles 挂载移到中间件之后
app.mount("/static", StaticFiles(directory=outputs_path), name="static")

# Add routes
app.include_router(generate_code.router)
app.include_router(screenshot.router)
app.include_router(home.router)
app.include_router(evals.router)
