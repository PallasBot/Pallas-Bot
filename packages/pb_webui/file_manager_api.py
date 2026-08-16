"""Pallas-Bot WebUI console API: 项目根文件管理。

浏览、查看/编辑文本、新建/重命名/删除、上传/下载与图片预览。
范围限定在项目根内（resolve + 前缀校验），文本读写有大小上限，避免整读大文件。
"""

from __future__ import annotations

import mimetypes
import shutil
from pathlib import Path
from typing import TYPE_CHECKING

from fastapi import APIRouter, File, Header, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field

from pallas.core.foundation.paths import PROJECT_ROOT

from .extended_common import check_pallas_write_token

if TYPE_CHECKING:
    from .config import Config

_MAX_TEXT_BYTES = 1024 * 1024
_MAX_UPLOAD_BYTES = 20 * 1024 * 1024
_MAX_PATH_LEN = 4096

_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".svg", ".ico", ".avif"}
_FORBIDDEN_NAME_CHARS = '<>:"|?*'


class _FilesEntry(BaseModel):
    name: str
    is_dir: bool
    is_image: bool
    size: int
    mtime: float


class _FilesListData(BaseModel):
    path: str
    entries: list[_FilesEntry]


class _FilesListResponse(BaseModel):
    ok: bool = True
    data: _FilesListData


class _FilesReadData(BaseModel):
    path: str
    content: str
    size: int


class _FilesReadResponse(BaseModel):
    ok: bool = True
    data: _FilesReadData


class _FilesWriteBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: str = Field(min_length=1, max_length=_MAX_PATH_LEN)
    content: str


class _FilesCreateBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    parent: str = Field(default="", max_length=_MAX_PATH_LEN)
    name: str = Field(min_length=1, max_length=255)
    is_dir: bool = False


class _FilesRenameBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: str = Field(min_length=1, max_length=_MAX_PATH_LEN)
    new_name: str = Field(min_length=1, max_length=255)


class _FilesDeleteBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: str = Field(default="", max_length=_MAX_PATH_LEN)


class _FilesOkData(BaseModel):
    path: str
    size: int = 0


class _FilesOkResponse(BaseModel):
    ok: bool = True
    data: _FilesOkData


def _allowed_path(raw: str) -> Path:
    """项目根内路径解析，防穿越；空或相对路径视为相对项目根。"""
    if not raw:
        return PROJECT_ROOT
    candidate = Path(raw)
    if not candidate.is_absolute():
        candidate = PROJECT_ROOT / candidate
    path = candidate.resolve()
    if len(str(path)) > _MAX_PATH_LEN:
        raise HTTPException(status_code=400, detail="路径长度超出限制")
    root = PROJECT_ROOT.resolve()
    if path != root and root not in path.parents:
        raise HTTPException(status_code=403, detail="访问路径超出允许范围")
    return path


def _validate_name(name: str) -> None:
    if not name or name in {".", ".."} or "/" in name or "\\" in name or "\x00" in name:
        raise HTTPException(status_code=400, detail="非法文件名")
    if any(ch in name for ch in _FORBIDDEN_NAME_CHARS):
        raise HTTPException(status_code=400, detail="文件名包含非法字符")


def _rel_text(path: Path) -> str:
    if path == PROJECT_ROOT:
        return ""
    return str(path.relative_to(PROJECT_ROOT))


def register_file_manager_router(router: APIRouter, *, x: str, plugin_config: Config) -> None:
    @router.get(f"{x}/files/list", response_model=_FilesListResponse)
    async def _files_list(path: str = Query(default="")) -> _FilesListResponse:
        target = _allowed_path(path)
        if not target.is_dir():
            raise HTTPException(status_code=400, detail="路径不是目录")
        try:
            names = sorted(child.name for child in target.iterdir() if not child.name.startswith("."))
        except OSError as exc:
            raise HTTPException(status_code=403, detail=f"无法读取目录: {exc}") from exc
        entries: list[_FilesEntry] = []
        for name in names:
            child = target / name
            try:
                is_dir = child.is_dir()
                st = child.stat()
            except OSError:
                continue
            entries.append(
                _FilesEntry(
                    name=name,
                    is_dir=is_dir,
                    is_image=child.suffix.lower() in _IMAGE_EXTENSIONS,
                    size=0 if is_dir else int(st.st_size),
                    mtime=float(st.st_mtime),
                )
            )
        return _FilesListResponse(data=_FilesListData(path=_rel_text(target), entries=entries))

    @router.get(f"{x}/files/read", response_model=_FilesReadResponse)
    async def _files_read(path: str = Query(...)) -> _FilesReadResponse:
        target = _allowed_path(path)
        if not target.is_file():
            raise HTTPException(status_code=400, detail="路径不是文件")
        size = int(target.stat().st_size)
        if size > _MAX_TEXT_BYTES:
            raise HTTPException(status_code=413, detail=f"文件过大（{size} 字节），文本查看仅支持 ≤1MB，请下载")
        data = target.read_bytes()
        if b"\x00" in data:
            raise HTTPException(status_code=400, detail="二进制文件不支持文本查看，请下载")
        try:
            content = data.decode("utf-8")
        except UnicodeDecodeError:
            raise HTTPException(status_code=400, detail="非 UTF-8 文本文件，请下载") from None
        return _FilesReadResponse(data=_FilesReadData(path=path, content=content, size=size))

    @router.post(f"{x}/files/write", response_model=_FilesOkResponse)
    async def _files_write(
        body: _FilesWriteBody,
        token: str | None = Query(default=None),
        x_pallas_token: str | None = Header(default=None, alias="X-Pallas-Token"),
    ) -> _FilesOkResponse:
        check_pallas_write_token(plugin_config, x_pallas_token=x_pallas_token, token=token)
        target = _allowed_path(body.path)
        if not target.is_file():
            raise HTTPException(status_code=400, detail="路径不是文件")
        data = body.content.encode("utf-8")
        if len(data) > _MAX_TEXT_BYTES:
            raise HTTPException(status_code=413, detail="内容过大")
        target.write_bytes(data)
        return _FilesOkResponse(data=_FilesOkData(path=_rel_text(target), size=len(data)))

    @router.post(f"{x}/files/create", response_model=_FilesOkResponse)
    async def _files_create(
        body: _FilesCreateBody,
        token: str | None = Query(default=None),
        x_pallas_token: str | None = Header(default=None, alias="X-Pallas-Token"),
    ) -> _FilesOkResponse:
        check_pallas_write_token(plugin_config, x_pallas_token=x_pallas_token, token=token)
        parent = _allowed_path(body.parent)
        if not parent.is_dir():
            raise HTTPException(status_code=400, detail="父目录不存在")
        _validate_name(body.name)
        child = parent / body.name
        if child.exists():
            raise HTTPException(status_code=400, detail="同名文件已存在")
        if body.is_dir:
            child.mkdir(parents=False)
        else:
            child.touch()
        return _FilesOkResponse(data=_FilesOkData(path=_rel_text(child)))

    @router.post(f"{x}/files/rename", response_model=_FilesOkResponse)
    async def _files_rename(
        body: _FilesRenameBody,
        token: str | None = Query(default=None),
        x_pallas_token: str | None = Header(default=None, alias="X-Pallas-Token"),
    ) -> _FilesOkResponse:
        check_pallas_write_token(plugin_config, x_pallas_token=x_pallas_token, token=token)
        target = _allowed_path(body.path)
        if target == PROJECT_ROOT:
            raise HTTPException(status_code=400, detail="不能重命名根目录")
        _validate_name(body.new_name)
        new_path = target.with_name(body.new_name)
        if new_path.exists():
            raise HTTPException(status_code=400, detail="同名文件已存在")
        target.rename(new_path)
        return _FilesOkResponse(data=_FilesOkData(path=_rel_text(new_path)))

    @router.post(f"{x}/files/delete", response_model=_FilesOkResponse)
    async def _files_delete(
        body: _FilesDeleteBody,
        token: str | None = Query(default=None),
        x_pallas_token: str | None = Header(default=None, alias="X-Pallas-Token"),
    ) -> _FilesOkResponse:
        check_pallas_write_token(plugin_config, x_pallas_token=x_pallas_token, token=token)
        target = _allowed_path(body.path)
        if target == PROJECT_ROOT:
            raise HTTPException(status_code=400, detail="不能删除根目录")
        if target.is_dir():
            shutil.rmtree(target)
        elif target.is_file():
            target.unlink()
        else:
            raise HTTPException(status_code=400, detail="路径不存在")
        return _FilesOkResponse(data=_FilesOkData(path=_rel_text(target)))

    @router.post(f"{x}/files/upload", response_model=_FilesOkResponse)
    async def _files_upload(
        path: str = Query(default=""),
        file: UploadFile = File(...),  # noqa: B008
        token: str | None = Query(default=None),
        x_pallas_token: str | None = Header(default=None, alias="X-Pallas-Token"),
    ) -> _FilesOkResponse:
        check_pallas_write_token(plugin_config, x_pallas_token=x_pallas_token, token=token)
        target_dir = _allowed_path(path)
        if not target_dir.is_dir():
            raise HTTPException(status_code=400, detail="目标目录不存在")
        filename = str(file.filename or "").strip()
        _validate_name(filename)
        content = await file.read()
        if len(content) > _MAX_UPLOAD_BYTES:
            raise HTTPException(status_code=413, detail="上传文件过大（≤20MB）")
        dest = target_dir / filename
        dest.write_bytes(content)
        return _FilesOkResponse(data=_FilesOkData(path=_rel_text(dest), size=len(content)))

    @router.get(f"{x}/files/download", include_in_schema=True)
    async def _files_download(path: str = Query(...)) -> FileResponse:
        target = _allowed_path(path)
        if not target.is_file():
            raise HTTPException(status_code=400, detail="路径不是文件")
        return FileResponse(target, filename=target.name)

    @router.get(f"{x}/files/image", include_in_schema=True)
    async def _files_image(path: str = Query(...)) -> FileResponse:
        target = _allowed_path(path)
        if not target.is_file():
            raise HTTPException(status_code=400, detail="路径不是文件")
        media_type = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
        return FileResponse(target, media_type=media_type)
