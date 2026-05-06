"""Tests for centralized pipeline resolver with layered matching."""

import pytest

from scatter.pipeline.resolver import (
    STRIPPABLE_SUFFIXES,
    PipelineMatch,
    PipelineResolver,
    _strip_suffix,
)


@pytest.fixture
def sample_map():
    return {
        "GalaxyWorks.Api": "galaxyworks-api-az-cd",
        "GalaxyWorks.WebPortal": "galaxyworks-portal-az-cd",
        "Auth": "auth-az-cd",
        "MyApp": "myapp-az-cd",
        "MyApp.Data": "myapp-data-az-cd",
    }


@pytest.fixture
def resolver(sample_map):
    return PipelineResolver(sample_map)


# ---------------------------------------------------------------------------
# Strategy 1: Exact match
# ---------------------------------------------------------------------------


class TestExactMatch:
    def test_exact_hit(self, resolver):
        m = resolver.resolve("GalaxyWorks.Api")
        assert m is not None
        assert m.pipeline_name == "galaxyworks-api-az-cd"
        assert m.strategy == "exact"
        assert m.matched_key == "GalaxyWorks.Api"

    def test_exact_is_case_sensitive(self, resolver):
        m = resolver.resolve("galaxyworks.api")
        assert m is not None
        assert m.strategy == "case_insensitive"


# ---------------------------------------------------------------------------
# Strategy 2: Case-insensitive match
# ---------------------------------------------------------------------------


class TestCaseInsensitive:
    def test_case_insensitive_hit(self, resolver):
        m = resolver.resolve("galaxyworks.webportal")
        assert m is not None
        assert m.pipeline_name == "galaxyworks-portal-az-cd"
        assert m.strategy == "case_insensitive"
        assert m.matched_key == "GalaxyWorks.WebPortal"

    def test_exact_wins_over_case_insensitive(self):
        r = PipelineResolver({"Foo": "pipe-a", "foo": "pipe-b"})
        m = r.resolve("Foo")
        assert m.pipeline_name == "pipe-a"
        assert m.strategy == "exact"


# ---------------------------------------------------------------------------
# Strategy 3: Suffix-stripped match
# ---------------------------------------------------------------------------


class TestSuffixStripped:
    def test_strip_service(self, resolver):
        m = resolver.resolve("Auth.Service")
        assert m is not None
        assert m.pipeline_name == "auth-az-cd"
        assert m.strategy == "suffix_stripped"
        assert m.matched_key == "Auth"

    def test_strip_host(self, resolver):
        m = resolver.resolve("GalaxyWorks.Api.Host")
        assert m is not None
        assert m.pipeline_name == "galaxyworks-api-az-cd"
        assert m.strategy == "suffix_stripped"
        assert m.matched_key == "GalaxyWorks.Api"

    def test_strip_case_insensitive(self, resolver):
        m = resolver.resolve("auth.service")
        assert m is not None
        assert m.pipeline_name == "auth-az-cd"
        assert m.strategy == "suffix_stripped"

    def test_no_strip_when_exact_exists(self):
        r = PipelineResolver(
            {
                "Auth.Service": "pipe-exact",
                "Auth": "pipe-stripped",
            }
        )
        m = r.resolve("Auth.Service")
        assert m.pipeline_name == "pipe-exact"
        assert m.strategy == "exact"

    def test_no_double_strip(self):
        """Only one suffix is stripped — 'Foo.Service.Host' strips '.Host'
        yielding 'Foo.Service', but does NOT strip again to get 'Foo'."""
        r = PipelineResolver({"Foo": "pipe-foo"})
        result = r.resolve("FooX.Service.Host")
        assert result is None

    def test_webapi_stripped_before_api(self):
        r = PipelineResolver({"MyApp": "pipe-myapp"})
        m = r.resolve("MyApp.WebApi")
        assert m is not None
        assert m.pipeline_name == "pipe-myapp"
        assert m.strategy == "suffix_stripped"


# ---------------------------------------------------------------------------
# Strategy 4: Prefix match
# ---------------------------------------------------------------------------


class TestPrefixMatch:
    def test_prefix_hit(self, resolver):
        m = resolver.resolve("MyApp.Something")
        assert m is not None
        assert m.pipeline_name == "myapp-az-cd"
        assert m.strategy == "prefix"
        assert m.matched_key == "MyApp"

    def test_longest_prefix_wins(self, resolver):
        m = resolver.resolve("MyApp.Data.Migrations")
        assert m is not None
        assert m.pipeline_name == "myapp-data-az-cd"
        assert m.matched_key == "MyApp.Data"

    def test_dot_boundary_required(self, resolver):
        m = resolver.resolve("MyAppExtra")
        assert m is None

    def test_probe_substring_of_key_no_match(self, resolver):
        """'App' does NOT match 'MyApp' — prefix goes the wrong direction."""
        r = PipelineResolver({"MyApp": "pipe"})
        m = r.resolve("My")
        assert m is None


# ---------------------------------------------------------------------------
# Multi-probe
# ---------------------------------------------------------------------------


class TestMultiProbe:
    def test_first_match_wins(self, resolver):
        m = resolver.resolve("GalaxyWorks.Api", "Auth")
        assert m.pipeline_name == "galaxyworks-api-az-cd"
        assert m.probe == "GalaxyWorks.Api"

    def test_fallthrough_to_second_probe(self, resolver):
        m = resolver.resolve("NoMatch", "Auth")
        assert m is not None
        assert m.pipeline_name == "auth-az-cd"
        assert m.probe == "Auth"

    def test_all_fail(self, resolver):
        assert resolver.resolve("X", "Y", "Z") is None

    def test_empty_probes_skipped(self, resolver):
        m = resolver.resolve("", "", "Auth")
        assert m is not None
        assert m.pipeline_name == "auth-az-cd"

    def test_no_probes(self, resolver):
        assert resolver.resolve() is None


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    def test_empty_map(self):
        r = PipelineResolver({})
        assert r.resolve("Anything") is None

    def test_single_entry_map(self):
        r = PipelineResolver({"Foo": "pipe-foo"})
        assert r.resolve("Foo").pipeline_name == "pipe-foo"

    def test_all_suffixes_recognized(self):
        for suffix in STRIPPABLE_SUFFIXES:
            assert _strip_suffix(f"Base{suffix}") == "Base", f"Failed for {suffix}"

    def test_no_suffix_returns_unchanged(self):
        assert _strip_suffix("NoSuffix") == "NoSuffix"


# ---------------------------------------------------------------------------
# Match metadata
# ---------------------------------------------------------------------------


class TestMatchMetadata:
    def test_exact_metadata(self, resolver):
        m = resolver.resolve("Auth")
        assert m == PipelineMatch("auth-az-cd", "exact", "Auth", "Auth")

    def test_fuzzy_metadata(self, resolver):
        m = resolver.resolve("Auth.Service")
        assert m.probe == "Auth.Service"
        assert m.matched_key == "Auth"
        assert m.strategy == "suffix_stripped"
        assert m.pipeline_name == "auth-az-cd"
