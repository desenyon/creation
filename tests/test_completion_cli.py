from creation.completion_cli import _linear_is_complete, _qa_is_clean


def test_clean_qa_requires_a_real_test_run_and_no_browser_errors():
    clean = """## Test run
Command: `pytest -q` · passed 12 · failed 0

## Browser review
No blocking issues detected on checked URLs.
"""
    assert _qa_is_clean(clean)
    assert not _qa_is_clean("No test suite detected or pytest not on PATH.")
    assert not _qa_is_clean(clean + "\n- [error] http://localhost — HTTP 500")


def test_linear_complete_requires_done_items_and_no_open_buckets():
    complete = """### Kanban board

**Done**
- [LOOP-1] [plan] Ship MVP
"""
    assert _linear_is_complete(complete)
    assert not _linear_is_complete(complete + "\n**Todo**\n- [LOOP-2] Fix tests")
    assert not _linear_is_complete("## Project tracking (Composio)")
