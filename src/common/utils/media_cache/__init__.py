import asyncio
import base64
import re
from datetime import datetime, timedelta

import httpx
from nonebot.adapters.onebot.v11 import MessageSegment

from src.common.db import ImageCache
from src.common.utils import HTTPXClient


async def insert_image(image_seg: MessageSegment):
    cq_code = re.sub(r"\.image,.+?\]", ".image]", str(image_seg))
    cache = await ImageCache.find_one(ImageCache.cq_code == cq_code)
    if not cache:
        cache = ImageCache(cq_code=cq_code)
        await cache.insert()
        return
    cache.ref_times += 1
    # 不是经常收到的图不缓存，不然会占用大量空间
    if cache.ref_times > 2 and cache.base64_data is None:
        url = image_seg.data["url"]
        rsp = await HTTPXClient.get(url)
        if not rsp or rsp.status_code != httpx.codes.OK:
            return
        base64_data = base64.b64encode(rsp.content).decode()
        cache.base64_data = base64_data
    await cache.save()


async def get_image(cq_code) -> bytes | None:
    cache = await ImageCache.find_one(ImageCache.cq_code == cq_code)
    if not cache:
        return None
    if cache.base64_data is None:
        return None
    return base64.b64decode(cache.base64_data)


async def clear_image_cache(days: int = 5, times: int = 3):
    idate = int(str((datetime.now() - timedelta(days=days)).date()).replace("-", ""))
    await ImageCache.find(ImageCache.date < idate).delete()
    await ImageCache.find(ImageCache.ref_times < times).delete()


if __name__ == "__main__":
    asyncio.run(clear_image_cache(5, 3))
