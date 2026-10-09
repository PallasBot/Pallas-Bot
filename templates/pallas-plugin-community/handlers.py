from nonebot.matcher import Matcher


async def handle_ping(matcher: Matcher) -> None:
    await matcher.finish("Pong.")
