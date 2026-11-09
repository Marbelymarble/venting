import unittest

from venting.editor import Editor, cell_width, clip, layout, safe_text, wrap


class EditorTests(unittest.TestCase):
    def test_pairing_places_cursor_inside_and_skips_existing_closer(self):
        for opening, closing in [('(', ')'), ('[', ']'), ('{', '}'), ('"', '"')]:
            with self.subTest(pair=opening + closing):
                draft = Editor()
                draft.type_character(opening)
                self.assertEqual((draft.text, draft.cursor), (opening + closing, 1))
                for char in "hello":
                    draft.type_character(char)
                draft.type_character(closing)
                self.assertEqual(draft.text, opening + "hello" + closing)
                self.assertEqual(draft.cursor, len(draft.text))

    def test_nested_pairs(self):
        draft = Editor()
        for char in '({["hello"]})':
            draft.type_character(char)
        self.assertEqual(draft.text, '({["hello"]})')
        self.assertEqual(draft.cursor, len(draft.text))

    def test_backspace_removes_an_empty_pair(self):
        for opener in '( [{"'.replace(" ", ""):
            draft = Editor()
            draft.type_character(opener)
            draft.backspace(paired=True)
            self.assertEqual((draft.text, draft.cursor), ("", 0))

    def test_backspace_inside_nonempty_pair_only_removes_previous_character(self):
        draft = Editor("(ab)", 3)
        draft.backspace(paired=True)
        self.assertEqual((draft.text, draft.cursor), ("(a)", 2))

    def test_pasted_brackets_and_quotes_are_not_paired(self):
        draft = Editor()
        draft.insert('("unfinished', paste=True)
        self.assertEqual(draft.text, '("unfinished')

    def test_multiline_paste_normalizes_newlines_and_filters_terminal_controls(self):
        draft = Editor()
        draft.insert("first\r\nsecond\rthird\tend\x1b\x00", paste=True)
        self.assertEqual(draft.text, "first\nsecond\nthird    end")

    def test_combining_characters_delete_as_a_cluster(self):
        draft = Editor("e\u0301", 2)
        draft.backspace()
        self.assertEqual(draft.text, "")
        draft = Editor("e\u0301x", 0)
        draft.delete()
        self.assertEqual(draft.text, "x")

    def test_common_emoji_delete_as_a_cluster(self):
        for text in ("👩\u200d💻", "🇬🇧", "👍🏽"):
            with self.subTest(text=text):
                draft = Editor(text, len(text))
                draft.backspace()
                self.assertEqual(draft.text, "")

    def test_editing_in_the_middle(self):
        draft = Editor("some thught", 7)
        draft.insert("o")
        self.assertEqual(draft.text, "some thought")
        draft.cursor = len(draft.text)
        draft.delete_word()
        self.assertEqual(draft.text, "some ")
        draft.clear()
        draft.backspace()
        draft.delete()
        self.assertEqual((draft.text, draft.cursor), ("", 0))

    def test_layout_uses_display_cells(self):
        self.assertEqual(cell_width("Grüße"), 5)
        self.assertEqual(cell_width("e\u0301"), 1)
        self.assertEqual(cell_width("日本"), 4)
        self.assertEqual(cell_width("👩\u200d💻"), 2)
        self.assertEqual(cell_width("👍🏽"), 2)
        self.assertEqual(clip("日a本", 3), "日a")
        self.assertEqual(wrap("日本a", 4, 3), (["日本", "a"], (1, 1)))

    def test_newlines_and_exact_width_have_correct_cursor_positions(self):
        self.assertEqual(wrap("1234", 4, 4), (["1234", ""], (1, 0)))
        self.assertEqual(wrap("ab\ncd", 4, 3), (["ab", "cd"], (1, 0)))
        lines, positions = layout("abcd\nef", 4)
        self.assertEqual(lines, ["abcd", "ef"])
        self.assertEqual(positions[5], (1, 0))

    def test_saved_terminal_controls_are_displayed_as_text(self):
        self.assertEqual(safe_text("a\x1b[31mb\x07"), "a?[31mb?")


if __name__ == "__main__":
    unittest.main()
