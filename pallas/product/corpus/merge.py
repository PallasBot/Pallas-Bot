"""多语料源 Context / Answer 合并。"""

from __future__ import annotations

from pallas.core.foundation.db.modules import Answer, Ban, Context

MergeStrategy = str  # local_first | merge_counts


def answer_key(answer: Answer) -> tuple[int, str]:
    return (int(answer.group_id), str(answer.keywords))


def copy_answer(answer: Answer) -> Answer:
    return Answer(
        keywords=answer.keywords,
        group_id=answer.group_id,
        count=int(answer.count),
        time=int(answer.time),
        messages=list(answer.messages),
    )


def copy_context(context: Context) -> Context:
    return Context.model_construct(
        keywords=context.keywords,
        time=int(context.time),
        trigger_count=int(context.trigger_count),
        answers=[copy_answer(a) for a in context.answers],
        ban=[Ban(keywords=b.keywords, group_id=b.group_id, reason=b.reason, time=b.time) for b in context.ban],
        clear_time=int(context.clear_time),
    )


def merge_contexts(
    base: Context | None,
    extra: Context | None,
    *,
    strategy: MergeStrategy = "local_first",
) -> Context | None:
    if extra is None:
        return base
    if base is None:
        return copy_context(extra)

    answers_map: dict[tuple[int, str], Answer] = {answer_key(a): copy_answer(a) for a in base.answers}
    for incoming in extra.answers:
        key = answer_key(incoming)
        existing = answers_map.get(key)
        if existing is None:
            answers_map[key] = copy_answer(incoming)
            continue
        if strategy == "merge_counts":
            existing.count = int(existing.count) + int(incoming.count)
            existing.time = max(int(existing.time), int(incoming.time))
            for msg in incoming.messages:
                if msg not in existing.messages:
                    existing.messages.append(msg)

    return Context.model_construct(
        keywords=base.keywords,
        time=max(int(base.time), int(extra.time)),
        trigger_count=int(base.trigger_count) + int(extra.trigger_count),
        answers=list(answers_map.values()),
        ban=[Ban(keywords=b.keywords, group_id=b.group_id, reason=b.reason, time=b.time) for b in base.ban],
        clear_time=max(int(base.clear_time), int(extra.clear_time)),
    )
