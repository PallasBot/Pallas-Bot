import asyncio

from .config import image_gen_config

image_gen_semaphore = asyncio.Semaphore(image_gen_config.max_concurrency)
