from sdd_context.retrieval import build_context, render_prompt, task_tokens


def test_task_tokens_include_policy_synonyms():
    tokens = task_tokens("Add a minimum order threshold and cap the discount")
    assert "minimum" in tokens
    assert "threshold" in tokens
    assert "discount" in tokens


def test_context_render_mentions_sources():
    context = {
        "task": "pricing change",
        "specs": [{"path": "spec.md", "line": 3, "symbol": "PRICE-001", "excerpt": "minimum"}],
        "code": [{"path": "pricing.py", "line": 1, "symbol": "apply_discount", "excerpt": "def"}],
        "tests": [{"path": "test.py", "line": 1, "symbol": "test", "excerpt": "assert"}],
        "docs": [],
        "state": None,
    }
    prompt = render_prompt(context)
    assert "spec.md:3" in prompt
    assert "pricing.py:1" in prompt
    assert "test.py:1" in prompt
