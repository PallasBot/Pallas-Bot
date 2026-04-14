from src.common.db import repository as repo_protocols
from src.plugins.repeater import ban_manager, learner, message_store, model, responder


def test_repository_instances_conform_to_protocols():
    assert isinstance(learner._context_repo, repo_protocols.ContextRepository)
    assert isinstance(responder._context_repo, repo_protocols.ContextRepository)
    assert isinstance(model._context_repo, repo_protocols.ContextRepository)
    assert isinstance(message_store._message_repo, repo_protocols.MessageRepository)
    assert isinstance(ban_manager._context_repo, repo_protocols.ContextRepository)
    assert isinstance(ban_manager._blacklist_repo, repo_protocols.BlackListRepository)


def test_repository_wiring_shared_implementation_types():
    learner_repo_type = type(learner._context_repo)
    assert isinstance(responder._context_repo, learner_repo_type)
    assert isinstance(model._context_repo, learner_repo_type)
