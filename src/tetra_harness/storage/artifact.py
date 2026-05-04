"""storage.artifact — 大对象持久化 (七牛 / 阿里 OSS / 腾讯 COS / 本地).

国产 cloud 优先. AWS S3 不支持 (硬约束).

env ARTIFACT_PROVIDER:  qiniu / oss / cos / local  (默认 local).
"""
from __future__ import annotations

import asyncio
import logging
import os
import shutil
from abc import ABC, abstractmethod
from pathlib import Path
from typing import List, Optional, Union

_log = logging.getLogger("tetra.artifact")


# ---------- 抽象 ----------
class ArtifactStore(ABC):
    """async 大对象存储接口."""

    @abstractmethod
    async def put(
        self,
        key: str,
        content: Union[bytes, "Path"],
        metadata: Optional[dict] = None,
    ) -> str:
        """存对象, 返回可访问 URL."""

    @abstractmethod
    async def get(self, key: str) -> bytes: ...

    @abstractmethod
    async def delete(self, key: str) -> None: ...

    @abstractmethod
    async def list(self, prefix: str) -> List[str]: ...

    @abstractmethod
    async def presign_url(self, key: str, expires_sec: int = 3600) -> str: ...


# ---------- 本地实现 (默认 / 测试 / fallback) ----------
class LocalArtifactStore(ArtifactStore):
    """本地文件系统 — 默认 data/artifacts/."""

    def __init__(self, root: Union[str, Path] = "data/artifacts") -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        # 防止 ../ 越权
        safe = key.lstrip("/").replace("..", "_")
        return self.root / safe

    async def put(
        self,
        key: str,
        content: Union[bytes, Path],
        metadata: Optional[dict] = None,
    ) -> str:
        p = self._path(key)
        p.parent.mkdir(parents=True, exist_ok=True)

        def _write() -> None:
            if isinstance(content, (bytes, bytearray)):
                p.write_bytes(bytes(content))
            elif isinstance(content, Path):
                shutil.copyfile(content, p)
            else:
                raise TypeError(f"unsupported content type: {type(content)}")

        await asyncio.to_thread(_write)
        return f"file://{p.resolve().as_posix()}"

    async def get(self, key: str) -> bytes:
        p = self._path(key)
        return await asyncio.to_thread(p.read_bytes)

    async def delete(self, key: str) -> None:
        p = self._path(key)

        def _del() -> None:
            if p.exists():
                p.unlink()

        await asyncio.to_thread(_del)

    async def list(self, prefix: str) -> List[str]:
        base = self._path(prefix)

        def _list() -> List[str]:
            if base.is_dir():
                return [
                    str(p.relative_to(self.root).as_posix())
                    for p in base.rglob("*")
                    if p.is_file()
                ]
            # 当 prefix 是文件名前缀
            parent = base.parent if base.parent.exists() else self.root
            return [
                str(p.relative_to(self.root).as_posix())
                for p in parent.rglob("*")
                if p.is_file() and p.name.startswith(base.name)
            ]

        return await asyncio.to_thread(_list)

    async def presign_url(self, key: str, expires_sec: int = 3600) -> str:
        # 本地无签名概念, 直接返回 file:// url
        return f"file://{self._path(key).resolve().as_posix()}"


# ---------- 七牛云 (推荐) ----------
class QiniuArtifactStore(ArtifactStore):
    """七牛云 Kodo. 免费 10G/月, 国内推荐."""

    def __init__(
        self,
        access_key: str,
        secret_key: str,
        bucket: str,
        domain: str,
    ) -> None:
        try:
            from qiniu import Auth  # type: ignore[import-not-found]
        except Exception as e:
            raise RuntimeError(f"qiniu SDK 未安装: {e!r}")

        self.bucket = bucket
        self.domain = domain.rstrip("/")
        self.auth = Auth(access_key, secret_key)
        self._access_key = access_key
        self._secret_key = secret_key

    async def put(
        self,
        key: str,
        content: Union[bytes, Path],
        metadata: Optional[dict] = None,
    ) -> str:
        from qiniu import put_data, put_file  # type: ignore[import-not-found]

        token = self.auth.upload_token(self.bucket, key, 3600)

        def _upload() -> None:
            if isinstance(content, (bytes, bytearray)):
                ret, info = put_data(token, key, bytes(content))
            elif isinstance(content, Path):
                ret, info = put_file(token, key, str(content))
            else:
                raise TypeError(f"unsupported content type: {type(content)}")
            if not info or info.status_code != 200:
                raise RuntimeError(f"qiniu put failed: {info}")

        await asyncio.to_thread(_upload)
        return f"https://{self.domain}/{key}"

    async def get(self, key: str) -> bytes:
        import httpx

        url = await self.presign_url(key, 600)
        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.get(url)
            r.raise_for_status()
            return r.content

    async def delete(self, key: str) -> None:
        from qiniu import BucketManager  # type: ignore[import-not-found]

        bm = BucketManager(self.auth)

        def _del() -> None:
            ret, info = bm.delete(self.bucket, key)
            if info.status_code not in (200, 612):  # 612 = not exist, 视为已删
                raise RuntimeError(f"qiniu delete failed: {info}")

        await asyncio.to_thread(_del)

    async def list(self, prefix: str) -> List[str]:
        from qiniu import BucketManager  # type: ignore[import-not-found]

        bm = BucketManager(self.auth)

        def _list() -> List[str]:
            ret, eof, info = bm.list(self.bucket, prefix=prefix, limit=1000)
            if info.status_code != 200 or not ret:
                return []
            return [item["key"] for item in ret.get("items", [])]

        return await asyncio.to_thread(_list)

    async def presign_url(self, key: str, expires_sec: int = 3600) -> str:
        base_url = f"http://{self.domain}/{key}"
        return self.auth.private_download_url(base_url, expires=expires_sec)


# ---------- 阿里云 OSS ----------
class AliyunOSSArtifactStore(ArtifactStore):
    """阿里云 OSS. 标准存储 ¥0.12/GB/月."""

    def __init__(
        self,
        access_key: str,
        secret_key: str,
        bucket: str,
        endpoint: str,
    ) -> None:
        try:
            import oss2  # type: ignore[import-not-found]
        except Exception as e:
            raise RuntimeError(f"oss2 SDK 未安装: {e!r}")

        self._oss2 = oss2
        self.endpoint = endpoint
        self.bucket_name = bucket
        auth = oss2.Auth(access_key, secret_key)
        self.bucket = oss2.Bucket(auth, endpoint, bucket)

    async def put(
        self,
        key: str,
        content: Union[bytes, Path],
        metadata: Optional[dict] = None,
    ) -> str:
        def _upload() -> None:
            headers = None
            if metadata:
                headers = {f"x-oss-meta-{k}": str(v) for k, v in metadata.items()}
            if isinstance(content, (bytes, bytearray)):
                self.bucket.put_object(key, bytes(content), headers=headers)
            elif isinstance(content, Path):
                self.bucket.put_object_from_file(key, str(content), headers=headers)
            else:
                raise TypeError(f"unsupported content type: {type(content)}")

        await asyncio.to_thread(_upload)
        return f"https://{self.bucket_name}.{self.endpoint}/{key}"

    async def get(self, key: str) -> bytes:
        def _read() -> bytes:
            return self.bucket.get_object(key).read()

        return await asyncio.to_thread(_read)

    async def delete(self, key: str) -> None:
        await asyncio.to_thread(self.bucket.delete_object, key)

    async def list(self, prefix: str) -> List[str]:
        def _list() -> List[str]:
            return [
                obj.key
                for obj in self._oss2.ObjectIterator(self.bucket, prefix=prefix)
            ]

        return await asyncio.to_thread(_list)

    async def presign_url(self, key: str, expires_sec: int = 3600) -> str:
        return await asyncio.to_thread(
            self.bucket.sign_url, "GET", key, expires_sec
        )


# ---------- 腾讯云 COS ----------
class TencentCOSArtifactStore(ArtifactStore):
    """腾讯云 COS. 标准存储 ¥0.118/GB/月."""

    def __init__(
        self,
        secret_id: str,
        secret_key: str,
        bucket: str,
        region: str,
    ) -> None:
        try:
            from qcloud_cos import CosConfig, CosS3Client  # type: ignore[import-not-found]
        except Exception as e:
            raise RuntimeError(f"cos-python-sdk-v5 未安装: {e!r}")

        self.bucket = bucket
        self.region = region
        config = CosConfig(Region=region, SecretId=secret_id, SecretKey=secret_key)
        self.client = CosS3Client(config)

    async def put(
        self,
        key: str,
        content: Union[bytes, Path],
        metadata: Optional[dict] = None,
    ) -> str:
        def _upload() -> None:
            extra = {"Metadata": metadata} if metadata else {}
            if isinstance(content, (bytes, bytearray)):
                self.client.put_object(
                    Bucket=self.bucket, Key=key, Body=bytes(content), **extra
                )
            elif isinstance(content, Path):
                self.client.upload_file(
                    Bucket=self.bucket, Key=key, LocalFilePath=str(content)
                )
            else:
                raise TypeError(f"unsupported content type: {type(content)}")

        await asyncio.to_thread(_upload)
        return f"https://{self.bucket}.cos.{self.region}.myqcloud.com/{key}"

    async def get(self, key: str) -> bytes:
        def _read() -> bytes:
            resp = self.client.get_object(Bucket=self.bucket, Key=key)
            body = resp["Body"]
            return body.get_raw_stream().read()

        return await asyncio.to_thread(_read)

    async def delete(self, key: str) -> None:
        await asyncio.to_thread(
            self.client.delete_object, Bucket=self.bucket, Key=key
        )

    async def list(self, prefix: str) -> List[str]:
        def _list() -> List[str]:
            resp = self.client.list_objects(Bucket=self.bucket, Prefix=prefix)
            return [c["Key"] for c in resp.get("Contents", [])]

        return await asyncio.to_thread(_list)

    async def presign_url(self, key: str, expires_sec: int = 3600) -> str:
        def _sign() -> str:
            return self.client.get_presigned_url(
                Method="GET",
                Bucket=self.bucket,
                Key=key,
                Expired=expires_sec,
            )

        return await asyncio.to_thread(_sign)


# ---------- factory ----------
_singleton: Optional[ArtifactStore] = None


def _build_from_env() -> ArtifactStore:
    provider = os.getenv("ARTIFACT_PROVIDER", "local").strip().lower()

    try:
        if provider == "qiniu":
            return QiniuArtifactStore(
                access_key=os.environ["QINIU_AK"],
                secret_key=os.environ["QINIU_SK"],
                bucket=os.getenv("QINIU_BUCKET", "tetra-harness"),
                domain=os.environ["QINIU_DOMAIN"],
            )
        if provider == "oss":
            return AliyunOSSArtifactStore(
                access_key=os.environ["ALIYUN_AK"],
                secret_key=os.environ["ALIYUN_SK"],
                bucket=os.getenv("ALIYUN_BUCKET", "tetra-harness"),
                endpoint=os.getenv("ALIYUN_ENDPOINT", "oss-cn-shenzhen.aliyuncs.com"),
            )
        if provider == "cos":
            return TencentCOSArtifactStore(
                secret_id=os.environ["TENCENT_SECRET_ID"],
                secret_key=os.environ["TENCENT_SECRET_KEY"],
                bucket=os.environ["TENCENT_BUCKET"],
                region=os.getenv("TENCENT_REGION", "ap-guangzhou"),
            )
    except KeyError as e:
        _log.warning(
            "artifact: provider=%s 缺环境变量 %s, fallback local", provider, e
        )
    except Exception as e:
        _log.warning("artifact: provider=%s init 失败 (%s), fallback local", provider, e)

    return LocalArtifactStore(os.getenv("ARTIFACT_LOCAL_PATH", "data/artifacts"))


def get_artifact_store() -> ArtifactStore:
    global _singleton
    if _singleton is None:
        _singleton = _build_from_env()
    return _singleton


def reset_artifact_store() -> None:
    """测试用."""
    global _singleton
    _singleton = None
