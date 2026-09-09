"""Regression tests for playbook classification, added after a review pass found
that bare "flag"/"config" substrings and check ordering could misclassify a
dependency alert whose stack trace happens to mention a config file path."""
from __future__ import annotations

from app.orchestrator.playbooks import PlaybookKey, classify


def test_resource_keywords_classify_as_resource():
    p = classify("OOMKilled: report-worker", "pods OOMKilled 6 times", None)
    assert p.key == PlaybookKey.resource


def test_dependency_keywords_classify_as_dependency():
    p = classify(
        "P99 latency SLO breach",
        "latency spike",
        "TimeoutError: request to shipping-rates-api timed out",
    )
    assert p.key == PlaybookKey.dependency


def test_dependency_stack_trace_mentioning_config_path_is_not_misclassified():
    """A dependency-timeout alert whose stack trace happens to pass through a file
    named .../config/... must not be classified as a config-change incident just
    because "config" is a substring."""
    p = classify(
        "P99 latency SLO breach",
        "checkout-api latency at 4.8s",
        'TimeoutError: request timed out\n  File "app/config/db.py", line 10',
    )
    assert p.key == PlaybookKey.dependency


def test_no_deploy_classifies_as_config():
    p = classify(
        "Elevated error rate: search-api",
        "search-api 5xx rate reached 6.2%. No deploy detected in the last 2 hours.",
        None,
    )
    assert p.key == PlaybookKey.config


def test_generic_error_defaults_to_code_change():
    p = classify("High error rate: payments-api", "5xx error rate exceeded threshold", None)
    assert p.key == PlaybookKey.code_change
