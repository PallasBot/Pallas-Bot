from pallas.core.foundation.db.lifecycle_registry import (
    DATASETS,
    PROTECTED_OBJECTS,
    classify_object,
)


def test_registry_contains_the_initial_datasets_with_unique_membership() -> None:
    assert set(DATASETS) == {
        "message_history",
        "repeater_context",
        "image_cache",
        "image_cache_files",
        "sticker_label",
        "llm_chat",
        "llm_memory",
        "background_jobs",
    }

    memberships: dict[str, list[str]] = {}
    for dataset_id, definition in DATASETS.items():
        for object_name in definition.objects:
            memberships.setdefault(object_name, []).append(dataset_id)

    assert memberships["context"] == ["repeater_context"]
    assert memberships["context_answer"] == ["repeater_context"]
    assert all(len(dataset_ids) == 1 for dataset_ids in memberships.values())


def test_llm_memory_only_exposes_expiry_maintenance() -> None:
    definition = DATASETS["llm_memory"]

    assert definition.supports_retention is False
    assert definition.supports_max_bytes is False


def test_repeater_context_does_not_offer_an_inaccurate_capacity_limit() -> None:
    assert DATASETS["repeater_context"].supports_max_bytes is False


def test_configuration_security_and_migration_objects_are_protected() -> None:
    expected = {
        "acl_rules",
        "admin_members",
        "blacklist",
        "bot_config",
        "config",
        "group_config",
        "migration_state",
        "schema_migrations",
        "user_config",
    }

    assert expected <= PROTECTED_OBJECTS
    registered_objects = {name for definition in DATASETS.values() for name in definition.objects}
    assert expected.isdisjoint(registered_objects)


def test_backend_specific_physical_names_share_one_dataset() -> None:
    assert classify_object("background_job").dataset_id == "background_jobs"
    assert classify_object("background_jobs").dataset_id == "background_jobs"


def test_unknown_objects_are_visible_but_protected() -> None:
    classification = classify_object("plugin_owned_table")

    assert classification.dataset_id is None
    assert classification.protected is True
    assert classification.protection_reason == "protected_unknown"


def test_registered_object_resolves_to_its_dataset() -> None:
    classification = classify_object("image_cache")

    assert classification.dataset_id == "image_cache"
    assert classification.protected is False
    assert classification.protection_reason is None
