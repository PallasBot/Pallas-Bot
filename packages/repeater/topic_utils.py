def filtered_recent_topics(keywords_list: list[str]) -> list[str]:
    return [k for k in keywords_list if not k.startswith("牛牛")]
