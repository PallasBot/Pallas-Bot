from __future__ import annotations

from pallas.product.persona.corpus_expression_habits import infer_expression_affect_stance


def test_infer_expression_affect_stance_distinguishes_common_reaction_shapes() -> None:
    assert infer_expression_affect_stance("这也太离谱了吧？？？") == "complain"
    assert infer_expression_affect_stance("谢谢你呀") == "warm"
    assert infer_expression_affect_stance("那确实") == "echo"
