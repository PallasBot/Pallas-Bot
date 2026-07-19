from packages.repeater import ban_manager, learner, message_store, model, responder
from pallas.core.foundation.db import repository as repo_protocols
from pallas.core.foundation.db.context_repo_access import LazyContextRepository


def test_repository_instances_conform_to_protocols():
    for repo in (learner.context_repo, responder.context_repo, model.context_repo, ban_manager.context_repo):
        assert isinstance(repo, LazyContextRepository)
    assert isinstance(message_store.message_repo, repo_protocols.MessageRepository)
    assert isinstance(ban_manager.blacklist_repo, repo_protocols.BlackListRepository)


def test_repository_wiring_shared_implementation_types():
    learner_repo_type = type(learner.context_repo)
    assert isinstance(responder.context_repo, learner_repo_type)
    assert isinstance(model.context_repo, learner_repo_type)
