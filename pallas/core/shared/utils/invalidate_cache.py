from beanie import Document


def invalidate_cache(model_class: type[Document], document_id=None, clear_all=False):
    if not model_class._cache:
        return 0

    cache = model_class._cache
    internal_cache_dict = cache.cache

    if clear_all:
        keys_to_delete = list(internal_cache_dict.keys())
    else:
        if document_id is None:
            return 0

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

            if not found and key and isinstance(key, tuple) and len(key) > 0:
                key_str = str(key)
                if model_class.__name__ in key_str:
                    found = True

            if found:
                keys_to_delete.append(key)

    deleted_count = 0
    if keys_to_delete:
        for key in keys_to_delete:
            if key in internal_cache_dict:
                internal_cache_dict.pop(key, None)
                deleted_count += 1

    return deleted_count


def clear_model_cache(model_class: type[Document]):
    return invalidate_cache(model_class, clear_all=True)
