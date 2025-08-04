from beanie import Document


def invalidate_cache(model_class: type[Document], document_id):
    if not model_class._cache:
        return
    cache = model_class._cache
    internal_cache_dict = cache.cache
    keys_to_delete = []

    for key, cached_item in internal_cache_dict.items():
        value = cached_item.value
        found = False

        if isinstance(value, dict):
            if value.get("_id") == document_id:
                found = True

        elif isinstance(value, list):
            for doc in value:
                if isinstance(doc, dict) and doc.get("_id") == document_id:
                    found = True
                    break

        if found:
            keys_to_delete.append(key)

    if keys_to_delete:
        for key in keys_to_delete:
            internal_cache_dict.pop(key, None)
