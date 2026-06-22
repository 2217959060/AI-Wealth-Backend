from fastapi import Request, HTTPException
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from fastapi.encoders import jsonable_encoder  # 🔥 新增导入这个
from schemas import ResponseModel

async def validation_exception_handler(request: Request, exc: RequestValidationError):
    return JSONResponse(
        status_code=400,
        # 🔥 使用 jsonable_encoder 包裹 exc.errors()，解决序列化报错
        content=ResponseModel(code=400, msg="参数错误", data=jsonable_encoder(exc.errors())).model_dump()
    )

async def http_exception_handler(request: Request, exc: HTTPException):
    return JSONResponse(
        status_code=exc.status_code,
        content=ResponseModel(code=exc.status_code, msg=exc.detail, data=None).model_dump()
    )

async def global_exception_handler(request: Request, exc: Exception):
    return JSONResponse(
        status_code=500,
        content=ResponseModel(code=500, msg=f"服务器错误: {str(exc)}", data=None).model_dump()
    )