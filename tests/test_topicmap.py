import json
import os
import struct
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from venting.kitty_graphics import cell_size, kitty_palette, render_graph
from venting.settings import Settings
from venting.topicmap import (_combine_topics, _parse_graph, build_topic_graph, graph_positions,
                              validate_days, Topic, TopicGraph, TopicReference)


class TopicMapTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.config = self.root / "config.json"

    def test_timeframe_setting_is_validated_and_persisted(self):
        settings = Settings(self.config)
        self.assertEqual(settings.topic_map_days, 30)
        for days in (7, 30, 90, 0):
            settings.set_topic_map_days(days)
            self.assertEqual(Settings.load(self.config).topic_map_days, days)
        for value in (1, -1, True, "30"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                validate_days(value)

    def test_model_references_must_be_exact_quotes_from_known_sources(self):
        path = self.root / "vent.txt"
        documents = [{"source": "v1", "file": path.name,
                      "text": "Work feels blocked by unclear priorities.", "_path": str(path)}]
        raw = {"topics": [
            {"name": "Work priorities", "references": [
                {"source": "v1", "excerpt": "blocked by unclear priorities"},
                {"source": "v1", "excerpt": "a sentence the model invented"}]},
            {"name": "Ungrounded", "references": [
                {"source": "missing", "excerpt": "anything"}]},
        ], "edges": [{"source": 0, "target": 1, "strength": 0.8}]}
        graph = _parse_graph(raw, documents, 30)
        self.assertEqual([topic.name for topic in graph.topics], ["Work priorities"])
        self.assertEqual(graph.topics[0].references[0].excerpt,
                         "blocked by unclear priorities")
        self.assertEqual(graph.edges, ())

    def test_build_uses_local_model_and_reuses_revision_cache(self):
        path = self.root / "vent.txt"
        path.write_text("Work feels blocked by unclear priorities and changing plans.\n")
        response = {"topics": [{"name": "Work priorities", "references": [
            {"source": "v1", "excerpt": "blocked by unclear priorities"}]}], "edges": []}
        tags = {"models": [{"name": "gemma3:1b", "size": 10,
                            "details": {"format": "gguf"}}]}
        with patch("venting.topicmap.ollama_json", side_effect=[tags, {
                "response": json.dumps(response)}]) as request:
            graph = build_topic_graph(self.root, self.config, 0, "gemma3:1b")
        self.assertEqual(graph.file_count, 1)
        payload = request.call_args_list[1].args[1]
        self.assertEqual(payload["format"], "json")
        self.assertIn("untrusted data", payload["system"])
        with patch("venting.topicmap.ollama_json") as request:
            cached = build_topic_graph(self.root, self.config, 0, "gemma3:1b")
        request.assert_not_called()
        self.assertEqual(cached.topics, graph.topics)

    def test_layout_stays_inside_canvas(self):
        documents = [{"source": "v1", "file": "one.txt", "text": "alpha beta gamma",
                      "_path": str(self.root / "one.txt")}]
        raw = {"topics": [
            {"name": "Alpha", "references": [{"source": "v1", "excerpt": "alpha"}]},
            {"name": "Beta", "references": [{"source": "v1", "excerpt": "beta"}]},
        ], "edges": [{"source": 0, "target": 1, "strength": 0.6}]}
        points = graph_positions(_parse_graph(raw, documents, 7), 40, 12)
        self.assertEqual(len(points), 2)
        self.assertTrue(all(0 <= x < 40 and 0 <= y < 12 for x, y in points))

        singleton = _parse_graph({"topics": [raw["topics"][0]], "edges": []},
                                 documents, 7)
        self.assertEqual(graph_positions(singleton, 40, 12), [(20, 6)])

    def test_build_extracts_each_vent_before_consolidating_and_caches_result(self):
        (self.root / "one.txt").write_text("work pressure and sleep")
        (self.root / "two.txt").write_text("work pressure and friends")
        extracted = []

        def respond(endpoint, payload=None):
            if endpoint == "/api/tags":
                return {"models": [{"name": "local:latest", "size": 10,
                                    "details": {"format": "gguf"}}]}
            if payload["prompt"].startswith("UNTRUSTED_JOURNAL_DOCUMENTS_JSON:"):
                documents = json.loads(payload["prompt"].split("\n", 1)[1])
                self.assertEqual(len(documents), 1)
                document = documents[0]
                extracted.append(document["file"])
                return {"response": json.dumps({"topics": [
                    {"name": concern, "references": [{"source": document["source"], "excerpt": concern}]}
                    for concern in document["text"].split(" and ")], "edges": []})}
            candidates = json.loads(payload["prompt"])
            return {"response": json.dumps({"groups": [
                {"name": item["name"], "members": [index]}
                for index, item in enumerate(candidates)], "edges": []})}

        with patch("venting.topicmap.ollama_json", side_effect=respond) as request:
            graph = build_topic_graph(self.root, self.config, 0, "local")
        self.assertEqual(set(extracted), {"one.txt", "two.txt"})
        self.assertEqual(request.call_count, 4)  # tags, two extractions, consolidation
        self.assertEqual({topic.name: topic.frequency for topic in graph.topics},
                         {"work pressure": 2, "sleep": 1, "friends": 1})
        with patch("venting.topicmap.ollama_json") as request:
            cached = build_topic_graph(self.root, self.config, 0, "local")
        request.assert_not_called()
        self.assertEqual(cached, graph)

    def test_graph_is_real_rgba_and_uses_included_kitty_palette(self):
        kitty = self.root / "kitty"
        kitty.mkdir()
        (kitty / "kitty.conf").write_text("include colors.conf\n")
        (kitty / "colors.conf").write_text(
            "foreground #f0e0d0\nbackground #102030\ncolor6 #12aBcD\n")
        with patch.dict(os.environ, {"KITTY_CONFIG_DIRECTORY": str(kitty)}):
            palette = kitty_palette()
        self.assertEqual(palette, ((240, 224, 208), (16, 32, 48), (18, 171, 205)))

        documents = [{"source": "v1", "file": "one.txt", "text": "alpha beta",
                      "_path": str(self.root / "one.txt")}]
        raw = {"topics": [
            {"name": "Alpha", "references": [{"source": "v1", "excerpt": "alpha"}]},
            {"name": "Beta", "references": [{"source": "v1", "excerpt": "beta"}]},
        ], "edges": [{"source": 0, "target": 1, "strength": 0.9}]}
        graph = _parse_graph(raw, documents, 7)
        pixels = render_graph(graph, [(2, 2), (8, 4)], 12, 7, 0, palette=palette)
        self.assertEqual(len(pixels), 12 * 9 * 7 * 18 * 4)
        self.assertGreater(sum(pixels[3::4]), 0)  # transparent canvas contains drawn pixels

    def test_cell_pixels_follow_terminal_dimensions_and_have_a_fallback(self):
        with patch("venting.kitty_graphics.fcntl.ioctl",
                   return_value=struct.pack("HHHH", 40, 120, 1680, 1120)):
            self.assertEqual(cell_size(), (14, 28))
        with patch("venting.kitty_graphics.fcntl.ioctl",
                   return_value=struct.pack("HHHH", 40, 120, 0, 0)):
            self.assertEqual(cell_size(), (9, 18))
        with patch("venting.kitty_graphics.fcntl.ioctl", side_effect=OSError):
            self.assertEqual(cell_size(), (9, 18))

    def test_frequency_counts_repeated_passages_without_duplicate_or_overlapping_quotes(self):
        documents = [{"source": "v1", "file": "one.txt", "text": "work pressure then work pressure",
                      "_path": str(self.root / "one.txt")}]
        raw = {"topics": [{"name": "Work", "references": [
            {"source": "v1", "excerpt": "work pressure"},
            {"source": "v1", "excerpt": "work pressure"},
            {"source": "v1", "excerpt": "pressure"}]}]}
        topic = _parse_graph(raw, documents, 7).topics[0]
        self.assertEqual(topic.frequency, 2)
        self.assertEqual(len(topic.references), 4)

    def test_consolidation_retains_evidence_and_single_occurrence_topics(self):
        documents = [{"source": f"v{index}", "file": f"{index}.txt", "text": text,
                      "_path": str(self.root / f"{index}.txt")}
                     for index, text in enumerate(("work pressure and sleep", "job stress and friends"), 1)]
        graphs = []
        for document, names in zip(documents, (("Work", "Sleep"), ("Job stress", "Friends"))):
            excerpts = document["text"].split(" and ")
            graphs.append(_parse_graph({"topics": [
                {"name": name, "references": [{"source": document["source"], "excerpt": excerpt}]}
                for name, excerpt in zip(names, excerpts)]}, [document], 7))
        # The model omitted Friends: it must still survive consolidation.
        with patch("venting.topicmap.ollama_json", return_value={"response": json.dumps({
                "groups": [{"name": "Work pressure", "members": [0, 2, 2]},
                           {"name": "Sleep", "members": [1]}], "edges": []})}):
            raw = _combine_topics("local", graphs, documents)
        graph = _parse_graph(raw, documents, 7)
        self.assertEqual([topic.name for topic in graph.topics], ["Work pressure", "Sleep", "Friends"])
        self.assertEqual([topic.frequency for topic in graph.topics], [2, 1, 1])

    def test_bubble_area_tracks_passage_frequency(self):
        path = self.root / "one.txt"
        frequent = Topic("Frequent", tuple(TopicReference(path, "quote", index * 10)
                                           for index in range(9)))
        rare = Topic("Rare", (TopicReference(path, "quote"),))
        graph = TopicGraph((frequent, rare), (), 1, 7)
        pixels = render_graph(graph, [(5, 3), (20, 3)], 26, 7, -1,
                              palette=((220, 225, 230), (18, 20, 24), (90, 190, 210)))
        width = 26 * 9
        areas = [sum(pixels[(y * width + x) * 4 + 3]
                     for y in range(7 * 18) for x in range(start, end))
                 for start, end in ((0, width // 2), (width // 2, width))]
        self.assertGreater(areas[0] / areas[1], 8)
        self.assertLess(areas[0] / areas[1], 10)


if __name__ == "__main__":
    unittest.main()
