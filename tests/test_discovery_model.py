"""Tests for canonical discovery query/filter model."""

from __future__ import annotations

import pytest

from pcli.core.errors import UsageValidationError
from pcli.models.discovery import (
    DEFAULT_DISCOVERY_SORT,
    DEFAULT_MAX_DOCS,
    DEFAULT_PAGE,
    DEFAULT_PAGE_SIZE,
    canonicalize_document_search,
)


def test_canonicalize_document_search_defaults() -> None:
    model = canonicalize_document_search()
    assert model.query is None
    assert model.custom_field_query is None
    assert model.page == DEFAULT_PAGE
    assert model.page_size == DEFAULT_PAGE_SIZE
    assert model.max_docs == DEFAULT_MAX_DOCS
    assert model.sort == DEFAULT_DISCOVERY_SORT
    assert model.filters == {}


def test_top_alias_maps_to_max_docs() -> None:
    model = canonicalize_document_search(top=25)
    assert model.max_docs == 25


def test_max_docs_wins_over_top_alias() -> None:
    model = canonicalize_document_search(max_docs=12, top=99)
    assert model.max_docs == 12


def test_filter_alias_and_list_normalization() -> None:
    model = canonicalize_document_search(
        query=" invoices ",
        filters={
            "doc_type": [5, 7, 9],
            "tag__id": [1, None, "2"],
            "is_inbox": True,
            "title__icontains": "  Acme  ",
        },
    )
    assert model.query == "invoices"
    assert model.filters["document_type"] == "5,7,9"
    assert model.filters["tag__id"] == "1,2"
    assert model.filters["is_inbox"] == "true"
    assert model.filters["title__icontains"] == "Acme"


def test_to_reduce_params_contains_canonical_values() -> None:
    model = canonicalize_document_search(
        query="contract",
        custom_field_query="field=value",
        page=2,
        page_size=50,
        filters={"correspondent__id": 3},
    )
    params = model.to_reduce_params()
    assert params["query"] == "contract"
    assert params["custom_field_query"] == "field=value"
    assert params["page"] == 2
    assert params["page_size"] == 50
    assert params["sort"] == DEFAULT_DISCOVERY_SORT
    assert params["correspondent__id"] == 3


def test_invalid_integer_fields_raise_validation_error() -> None:
    with pytest.raises(UsageValidationError):
        canonicalize_document_search(page=0)
    with pytest.raises(UsageValidationError):
        canonicalize_document_search(page=1.2)
    with pytest.raises(UsageValidationError):
        canonicalize_document_search(page_size="abc")
    with pytest.raises(UsageValidationError):
        canonicalize_document_search(page_size=10.7)
    with pytest.raises(UsageValidationError):
        canonicalize_document_search(max_docs=False)
    with pytest.raises(UsageValidationError):
        canonicalize_document_search(max_docs=4.5)


def test_empty_filter_key_raises_validation_error() -> None:
    with pytest.raises(UsageValidationError):
        canonicalize_document_search(filters={"  ": "x"})


def test_complex_filter_values_are_serialized_as_json() -> None:
    model = canonicalize_document_search(
        filters={
            "filter_rules": [{"rule_type": 1, "value": "invoice"}],
            "nested": [["a", "b"]],
        }
    )
    assert model.filters["filter_rules"] == '[{"rule_type":1,"value":"invoice"}]'
    assert model.filters["nested"] == '[["a","b"]]'
