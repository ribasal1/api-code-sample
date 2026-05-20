"""
Tests for NYTimes Data Loader Plugin -  API Code Sample

TDD approach: tests written before implementation.
Tests can only be modified manually. 

Run with: python -m unittest test_nytimes.py -v

Mocking strategy: All API calls are mocked with unittest.mock.patch.
No live API calls - tests run offline and fast.
"""

import argparse
import unittest
from unittest.mock import patch, MagicMock

from nytimes_source import NYTimesSource, flatten_dict


# ---------------------------------------------------------------------------
# Sample API response used across multiple tests
# ---------------------------------------------------------------------------
SAMPLE_ARTICLE = {
    "abstract": "A brisk theatrical thriller, \u201cData\u201d perfectly captures the slick, "
    "grandiose language with which tech titans justify their potentially "
    "totalitarian projects.",
    "byline": {"original": "By Michelle Goldberg"},
    "document_type": "article",
    "headline": {
        "main": "He Studied Cognitive Science at Stanford. Then He Wrote a "
        "Startling Play About A.I. Authoritarianism.",
        "kicker": "Michelle Goldberg",
        "print_headline": "",
    },
    "_id": "nyt://article/63887443-83f5-505c-86be-d0205f23424b",
    "keywords": [
        {"name": "Subject", "value": "Artificial Intelligence", "rank": 1},
        {"name": "Subject", "value": "Theater (Off Broadway)", "rank": 2},
        {"name": "Organization", "value": "Anthropic AI LLC", "rank": 3},
        {"name": "Organization", "value": "Palantir Technologies", "rank": 4},
        {"name": "Person", "value": "Altman, Samuel H", "rank": 5},
        {"name": "Person", "value": "Amodei, Dario", "rank": 6},
        {"name": "Person", "value": "Libby, Matthew (Playwright)", "rank": 7},
        {"name": "Title", "value": "Data (Play)", "rank": 8},
    ],
    "multimedia": {
        "caption": "Karan Brar, who plays Maneesh in \u201cData.\u201d",
        "credit": "Rachel Papo for The New York Times",
        "default": {
            "url": "https://static01.nyt.com/images/2026/02/16/multimedia/"
            "16goldberg-pbvj/16goldberg-pbvj-articleLarge.jpg",
            "height": 400,
            "width": 600,
        },
        "thumbnail": {
            "url": "https://static01.nyt.com/images/2026/02/16/multimedia/"
            "16goldberg-pbvj/16goldberg-pbvj-thumbStandard.jpg",
            "height": 75,
            "width": 75,
        },
    },
    "news_desk": "OpEd",
    "print_page": "",
    "print_section": "",
    "pub_date": "2026-02-16T10:03:05Z",
    "section_name": "Opinion",
    "snippet": "A brisk theatrical thriller, \u201cData\u201d perfectly captures the slick, "
    "grandiose language with which tech titans justify their potentially "
    "totalitarian projects.",
    "source": "The New York Times",
    "subsection_name": "",
    "type_of_material": "Op-Ed",
    "uri": "nyt://article/63887443-83f5-505c-86be-d0205f23424b",
    "web_url": "https://www.nytimes.com/2026/02/16/opinion/"
    "play-ai-authoritarianism.html",
    "word_count": 1090,
}


def _make_api_response(articles, hits=None):
    """Helper to build a mock NYT API JSON response."""
    if hits is None:
        hits = len(articles)
    return {
        "status": "OK",
        "response": {
            "docs": articles,
            "metadata": {
                "hits": hits,
                "offset": 0,
                "time": 25,
            },
        },
    }


def _make_mock_response(articles, status_code=200, hits=None):
    """Helper to build a mock requests. Response object."""
    mock_resp = MagicMock()
    mock_resp.status_code = status_code
    mock_resp.json.return_value = _make_api_response(articles, hits)
    return mock_resp


# ===========================================================================
# Group 1: flatten_dict (7 tests)
# ===========================================================================
class TestFlattenDict(unittest.TestCase):
    """Tests for the flatten_dict function."""

    def test_nested_dict(self):
        """Test 1: Nested dict flattens to dot notation."""
        data = {
            "headline": {"main": "The Title", "kicker": "Sub"},
        }
        result = flatten_dict(data)
        self.assertEqual(result["headline.main"], "The Title")
        self.assertEqual(result["headline.kicker"], "Sub")
        self.assertNotIn("headline", result)

    def test_already_flat(self):
        """Test 2: Already flat dict passes through unchanged."""
        data = {"web_url": "http://example.com", "_id": "123"}
        result = flatten_dict(data)
        self.assertEqual(result, data)

    def test_array_of_objects(self):
        """Test 3: Array of objects flattens with indexed keys.
        Based on real NYT API keywords structure (includes rank field).
        """
        data = {
            "keywords": [
                {"name": "Subject", "value": "Artificial Intelligence", "rank": 1},
                {"name": "Organization", "value": "Anthropic AI LLC", "rank": 3},
            ],
        }
        result = flatten_dict(data)
        self.assertEqual(result["keywords.0.name"], "Subject")
        self.assertEqual(result["keywords.0.value"], "Artificial Intelligence")
        self.assertEqual(result["keywords.0.rank"], 1)
        self.assertEqual(result["keywords.1.name"], "Organization")
        self.assertEqual(result["keywords.1.value"], "Anthropic AI LLC")
        self.assertEqual(result["keywords.1.rank"], 3)

    def test_none_values_preserved(self):
        """Test 4: None values are included, not dropped."""
        data = {
            "headline": {"main": "Title", "kicker": None},
        }
        result = flatten_dict(data)
        self.assertEqual(result["headline.main"], "Title")
        self.assertIn("headline.kicker", result)
        self.assertIsNone(result["headline.kicker"])

    def test_empty_dict_and_empty_list(self):
        """Test 5: Empty dict and empty list are both preserved as values."""
        data = {"byline": {}, "keywords": []}
        result = flatten_dict(data)
        # Empty dict: preserve as-is
        self.assertEqual(result["byline"], {})
        # Empty list: preserve as-is (spec says "all elements")
        self.assertEqual(result["keywords"], [])

    def test_deep_nesting(self):
        """Test 6: 3+ levels deep nesting works.
        Based on real NYT multimedia structure: multimedia.default.url
        """
        data = {
            "multimedia": {
                "caption": "Photo caption",
                "default": {
                    "url": "https://example.com/image.jpg",
                    "height": 400,
                    "width": 600,
                },
            },
        }
        result = flatten_dict(data)
        self.assertEqual(result["multimedia.caption"], "Photo caption")
        self.assertEqual(result["multimedia.default.url"], "https://example.com/image.jpg")
        self.assertEqual(result["multimedia.default.height"], 400)
        self.assertEqual(result["multimedia.default.width"], 600)

    def test_list_of_primitives(self):
        """Test 7: List of primitives (not objects) gets indexed."""
        data = {"tags": ["politics", "usa", "2026"]}
        result = flatten_dict(data)
        self.assertEqual(result["tags.0"], "politics")
        self.assertEqual(result["tags.1"], "usa")
        self.assertEqual(result["tags.2"], "2026")


# ===========================================================================
# Group 2: getDataBatch (2 tests)
# ===========================================================================
class TestGetDataBatch(unittest.TestCase):
    """Tests for batching logic and pagination."""

    def _create_source(self, config=None, inc_column=None, max_inc_value=None):
        """Helper to create and connect a NYTimesSource instance."""
        if config is None:
            config = {"api_key": "test-key", "query": "test"}
        source = NYTimesSource()
        source.args = argparse.Namespace(**config)
        source.connect(inc_column=inc_column, max_inc_value=max_inc_value)
        return source

    @patch("nytimes_source.time.sleep")
    @patch("nytimes_source.requests.Session")
    def test_batch_sizes(self, mock_session_cls, mock_sleep):
        """Test 8: 25 articles across 3 pages → batches of 10, 10, 5."""
        # Build 3 pages: 10, 10, 5 articles, then empty
        articles_page_0 = [{"_id": f"id_{i}", "pub_date": "2026-02-10"} for i in range(10)]
        articles_page_1 = [{"_id": f"id_{i}", "pub_date": "2026-02-10"} for i in range(10, 20)]
        articles_page_2 = [{"_id": f"id_{i}", "pub_date": "2026-02-10"} for i in range(20, 25)]

        mock_session = MagicMock()
        mock_session_cls.return_value = mock_session
        mock_session.get.side_effect = [
            _make_mock_response(articles_page_0),  # page 0
            _make_mock_response(articles_page_1),  # page 1
            _make_mock_response(articles_page_2),  # page 2
            _make_mock_response([]),                # page 3 → empty, stop
        ]

        source = self._create_source()
        batches = list(source.getDataBatch(10))

        self.assertEqual(len(batches), 3)
        self.assertEqual(len(batches[0]), 10)
        self.assertEqual(len(batches[1]), 10)
        self.assertEqual(len(batches[2]), 5)

    @patch("nytimes_source.time.sleep")
    @patch("nytimes_source.requests.Session")
    def test_empty_response(self, mock_session_cls, mock_sleep):
        """Test 9: Zero results → no batches, no crash."""
        mock_session = MagicMock()
        mock_session_cls.return_value = mock_session

        none_docs_resp = MagicMock()
        none_docs_resp.status_code = 200
        none_docs_resp.json.return_value = {
            "status": "OK",
            "response": {"docs": None, "metadata": {"hits": 0, "offset": 0, "time": 5}},
        }

        mock_session.get.side_effect = [
            none_docs_resp, # page 0 → docs is None
        ]

        source = self._create_source()
        batches = list(source.getDataBatch(10))

        self.assertEqual(len(batches), 0)


# ===========================================================================
# Group 3: Incremental loading (2 tests)
# ===========================================================================
class TestIncrementalLoading(unittest.TestCase):
    """Tests for incremental loading"""

    def _create_source(self, config=None, inc_column=None, max_inc_value=None):
        """Helper to create and connect a NYTimesSource instance."""
        if config is None:
            config = {"api_key": "test-key", "query": "test"}
        source = NYTimesSource()
        source.args = argparse.Namespace(**config)
        source.connect(inc_column=inc_column, max_inc_value=max_inc_value)
        return source

    @patch("nytimes_source.time.sleep")
    @patch("nytimes_source.requests.Session")
    def test_first_run_no_begin_date(self, mock_session_cls, mock_sleep):
        """Test 10: When max_inc_value=None, no begin_date is sent to the API.
        Note: callers should pass a date to avoid loading articles from year 1851.
        """
        mock_session = MagicMock()
        mock_session_cls.return_value = mock_session
        mock_session.get.side_effect = [
            _make_mock_response([{"_id": "a1", "pub_date": "2026-01-01"}]),
            _make_mock_response([]),  # stop
        ]

        source = self._create_source(max_inc_value=None)
        list(source.getDataBatch(10))  # consume generator

        # Check the first data fetch call
        data_call = mock_session.get.call_args_list[0]
        params = data_call[1].get("params", {})

        self.assertNotIn("begin_date", params)

    @patch("nytimes_source.time.sleep")
    @patch("nytimes_source.requests.Session")
    def test_incremental_run_with_begin_date(self, mock_session_cls, mock_sleep):
        """Test 11: Subsequent run → begin_date derived from max_inc_value."""
        mock_session = MagicMock()
        mock_session_cls.return_value = mock_session
        mock_session.get.side_effect = [
            _make_mock_response([{"_id": "a1", "pub_date": "2026-02-15"}]),
            _make_mock_response([]),  # stop
        ]

        source = self._create_source(
            inc_column="pub_date",
            max_inc_value="2026-02-14",
        )
        list(source.getDataBatch(10))  # consume generator

        # Check the first data fetch call
        data_call = mock_session.get.call_args_list[0]
        params = data_call[1].get("params", {})

        self.assertIn("begin_date", params)
        self.assertEqual(params["begin_date"], "20260214")


# ===========================================================================
# Group 4: Dynamic schema (1 test)
# ===========================================================================
class TestDynamicSchema(unittest.TestCase):
    """Test for dynamic schema accumulation."""

    @patch("nytimes_source.time.sleep")
    @patch("nytimes_source.requests.Session")
    def test_schema_accumulated_from_data(self, mock_session_cls, mock_sleep):
        """Test 12: Schema builds from all seen keys across batches."""
        # Article 1 has keys A, B
        article_1 = {"_id": "1", "web_url": "http://a.com", "pub_date": "2026-01-01"}
        # Article 2 has keys A, C (web_url missing, abstract added)
        article_2 = {"_id": "2", "abstract": "Summary text", "pub_date": "2026-01-02"}

        mock_session = MagicMock()
        mock_session_cls.return_value = mock_session
        mock_session.get.side_effect = [
            _make_mock_response([article_1, article_2]),
            _make_mock_response([]),  # stop
        ]

        source = NYTimesSource()
        source.args = argparse.Namespace(api_key="test-key", query="test")
        source.connect()
        list(source.getDataBatch(10))  # consume generator

        schema = source.getSchema()

        # Schema should be the UNION of all keys from both articles
        self.assertIn("_id", schema)
        self.assertIn("web_url", schema)
        self.assertIn("abstract", schema)
        self.assertIn("pub_date", schema)


if __name__ == "__main__":
    unittest.main()