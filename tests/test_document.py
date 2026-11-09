import unittest

from venting.document import DocumentEditor


class DocumentTests(unittest.TestCase):
    def test_editing_multiline_text_and_undo_redo(self):
        editor = DocumentEditor("one\ntwo", 3)
        editor.insert("!\nnew", paste=True)
        self.assertEqual(editor.text, "one!\nnew\ntwo")
        self.assertTrue(editor.undo())
        self.assertEqual((editor.text, editor.cursor), ("one\ntwo", 3))
        self.assertTrue(editor.redo())
        self.assertEqual((editor.text, editor.cursor), ("one!\nnew\ntwo", 8))

    def test_pairing_backspace_and_undo_keep_cursor_positions(self):
        editor = DocumentEditor()
        editor.type_character('"')
        self.assertEqual((editor.text, editor.cursor), ('""', 1))
        editor.undo()
        self.assertEqual((editor.text, editor.cursor), ("", 0))
        editor.redo()
        self.assertEqual((editor.text, editor.cursor), ('""', 1))
        editor.backspace(paired=True)
        editor.undo()
        self.assertEqual((editor.text, editor.cursor), ('""', 1))

    def test_new_edit_clears_redo(self):
        editor = DocumentEditor()
        editor.insert("a")
        editor.undo()
        editor.insert("b")
        self.assertFalse(editor.redo())
        self.assertEqual(editor.text, "b")

    def test_home_end_are_logical_line_boundaries(self):
        editor = DocumentEditor("first\nsecond\nthird", 9)
        editor.home()
        self.assertEqual(editor.cursor, 6)
        editor.end()
        self.assertEqual(editor.cursor, 12)

    def test_movement_handles_newlines_and_unicode_clusters(self):
        editor = DocumentEditor("e\u0301\n👩\u200d💻", 2)
        editor.left()
        self.assertEqual(editor.cursor, 0)
        editor.right()
        self.assertEqual(editor.cursor, 2)
        editor.right()
        self.assertEqual(editor.cursor, 3)
        editor.delete()
        self.assertEqual(editor.text, "e\u0301\n")
        editor.backspace()
        self.assertEqual(editor.text, "e\u0301")

    def test_wrapped_and_blank_lines_map_to_correct_source_positions(self):
        editor = DocumentEditor("abcd\n\n日本abc", 8)
        rows = editor.rows(4)
        self.assertEqual([r.text for r in rows], ["abcd", "", "日本", "abc"])
        self.assertEqual(editor.position(4), (3, 0))
        editor.cursor = 9
        self.assertEqual(editor.position(4), (3, 1))

    def test_vertical_movement_keeps_preferred_column_across_short_lines(self):
        editor = DocumentEditor("123456\nx\nabcdef", 5)
        editor.move_rows(1, 20)
        self.assertEqual(editor.cursor, 8)
        editor.move_rows(1, 20)
        self.assertEqual(editor.cursor, 14)

    def test_layout_cache_is_invalidated_by_undo_and_redo(self):
        editor = DocumentEditor("one", 3)
        self.assertEqual(editor.rows(10)[0].text, "one")
        editor.insert("two")
        self.assertEqual(editor.rows(10)[0].text, "onetwo")
        editor.undo()
        self.assertEqual(editor.rows(10)[0].text, "one")
        editor.redo()
        self.assertEqual(editor.rows(10)[0].text, "onetwo")


if __name__ == "__main__":
    unittest.main()
