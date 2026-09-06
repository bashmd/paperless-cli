"""Minimal schema races; no database, server, documents, or credentials needed."""

# ruff: noqa: E402
import gc
import threading
import weakref
from concurrent.futures import ThreadPoolExecutor

import django
from django.conf import settings

if not settings.configured:
    settings.configure(
        SECRET_KEY="local-schema-reproducer",
        INSTALLED_APPS=[
            "django.contrib.auth",
            "django.contrib.contenttypes",
            "rest_framework",
            "drf_spectacular",
        ],
        REST_FRAMEWORK={"DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema"},
        SPECTACULAR_SETTINGS={"TITLE": "Race repro", "VERSION": "1", "POSTPROCESSING_HOOKS": []},
    )
    django.setup()

import pytest
from django.urls import path
from drf_spectacular.generators import SchemaGenerator
from drf_spectacular.openapi import AutoSchema
from drf_spectacular.utils import extend_schema
from rest_framework import serializers, viewsets
from rest_framework.decorators import action


class PayloadSerializer(serializers.Serializer):
    value = serializers.CharField()


def routes(style="class-decorator"):
    class TasksViewSet(viewsets.GenericViewSet):
        serializer_class = PayloadSerializer
        authentication_classes = []
        permission_classes = []

        @action(detail=False, methods=["post"])
        def run(self, request):
            pass

        @extend_schema(description="A decorated method triggers a class schema lookup")
        @action(detail=False, methods=["post"])
        def acknowledge(self, request):
            pass

    if style == "class-decorator":
        TasksViewSet = extend_schema(tags=["tasks"])(TasksViewSet)
    elif style == "explicit-schema":

        class TaskSchema(AutoSchema):
            pass

        TasksViewSet.schema = TaskSchema()

    run = TasksViewSet.as_view({"post": "run"})
    acknowledge = TasksViewSet.as_view({"post": "acknowledge"})
    return [path("tasks/run/", run), path("tasks/acknowledge/", acknowledge)], acknowledge


def wait(event):
    assert event.wait(10), "Reproducer synchronization timed out"


def generate(patterns):
    return SchemaGenerator(patterns=patterns).get_schema(public=True)


@pytest.mark.parametrize("style", ["class-decorator", "explicit-schema", "default"])
def test_class_lookup_during_generation(monkeypatch, style):
    patterns, callback = routes(style)
    inside_auth = threading.Event()
    lookup_finished = threading.Event()
    original_auth = AutoSchema.get_auth

    def paused_auth(self):
        if threading.current_thread().name.startswith("generating") and self.path == "/tasks/run/":
            inside_auth.set()
            wait(lookup_finished)
        return original_auth(self)

    monkeypatch.setattr(AutoSchema, "get_auth", paused_auth)
    with ThreadPoolExecutor(max_workers=1, thread_name_prefix="generating") as pool:
        future = pool.submit(generate, patterns)
        wait(inside_auth)
        try:
            # This is an ordinary step performed by a second schema generator.
            SchemaGenerator().create_view(callback, "POST")
        finally:
            lookup_finished.set()
        schema = future.result()
    assert "/tasks/run/" in schema["paths"]


@pytest.mark.parametrize("style", ["class-decorator", "explicit-schema", "default"])
def test_concurrent_component_registration(monkeypatch, style):
    patterns, _ = routes(style)
    # Use the same single route for both generations; no class lookup needed here.
    patterns = patterns[:1]
    a_mapping = threading.Event()
    b_mapping = threading.Event()
    a_finished = threading.Event()
    original_map = AutoSchema._map_serializer

    def paused_map(self, serializer, direction, bypass_extensions=False):
        if threading.current_thread().name.startswith("generator-a"):
            a_mapping.set()
            wait(b_mapping)
        else:
            b_mapping.set()
            wait(a_finished)
        return original_map(self, serializer, direction, bypass_extensions)

    monkeypatch.setattr(AutoSchema, "_map_serializer", paused_map)
    with (
        ThreadPoolExecutor(max_workers=1, thread_name_prefix="generator-a") as pool_a,
        ThreadPoolExecutor(max_workers=1, thread_name_prefix="generator-b") as pool_b,
    ):
        future_a = pool_a.submit(generate, patterns)
        wait(a_mapping)
        future_b = pool_b.submit(generate, patterns)
        try:
            schema_a = future_a.result(timeout=10)
        finally:
            a_finished.set()
        schema_b = future_b.result(timeout=10)
    assert schema_a == schema_b


@pytest.mark.parametrize("style", ["class-decorator", "explicit-schema", "default"])
def test_inspectors_do_not_accumulate_views(style):
    patterns, _ = routes(style)
    references = []
    for _ in range(10):
        generator = SchemaGenerator(patterns=patterns)
        for pattern in patterns:
            view = generator.create_view(pattern.callback, "POST")
            references.append(weakref.ref(view))
        del view, generator
    gc.collect()
    # DRF's descriptor may retain its most recently bound view, but not all requests.
    assert sum(reference() is not None for reference in references) <= 1
