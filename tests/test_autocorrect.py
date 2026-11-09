import unittest

from venting.autocorrect import Autocorrect, validate_language
from venting.editor import Editor


class AutocorrectTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.corrector = Autocorrect()

    def test_common_typos_and_contractions(self):
        text, changes = self.corrector.correct('im realy tired becuase teh day was wierd.')
        self.assertEqual(text, "I'm really tired because the day was weird.")
        self.assertEqual(len(changes), 5)

    def test_case_preservation(self):
        self.assertEqual(self.corrector.correct("Teh TEH thier")[0], "The THE their")

    def test_frequency_dictionary_corrects_beyond_the_override_list(self):
        self.assertEqual(self.corrector.word("strugling"), "struggling")
        self.assertEqual(self.corrector.word("accomodate"), "accommodate")

    def test_valid_words_names_acronyms_and_mixed_case_are_preserved(self):
        text = "their there they're ill well cant Marvin ADHD iPhone fuuuck"
        self.assertEqual(self.corrector.correct(text)[0], text)

    def test_complete_urls_email_paths_and_code_are_preserved(self):
        text = "https://exmaple.com teh@example.com /tmp/teh.txt snake_teh_case `teh`"
        self.assertEqual(self.corrector.correct(text)[0], text)

    def test_punctuation_pairing_and_multiline_text(self):
        text = '(teh) [wierd] {thier}\n"becuase"'
        self.assertEqual(self.corrector.correct(text)[0], '(the) [weird] {their}\n"because"')

    def test_word_boundary_correction_and_undo_preserve_surrounding_text(self):
        draft = Editor("this is becuase", 15)
        changes = self.corrector.at_cursor(draft)
        self.assertEqual(draft.text, "this is because")
        draft.insert(" I am tired")
        self.assertTrue(changes[-1].undo(draft))
        self.assertEqual(draft.text, "this is becuase I am tired")
        self.assertEqual(draft.cursor, len(draft.text))

    def test_undo_does_not_replace_an_edited_word(self):
        draft = Editor("teh", 3)
        changes = self.corrector.at_cursor(draft)
        draft.text = "ten"
        self.assertFalse(changes[-1].undo(draft))

    def test_multiple_correction_offsets_account_for_length_changes(self):
        text, changes = self.corrector.correct("im definately alot")
        draft = Editor(text, len(text))
        self.assertTrue(changes[-1].undo(draft))
        self.assertEqual(draft.text, "I'm definitely alot")

    def test_german_common_typos_umlauts_and_case(self):
        corrector = Autocorrect("de")
        text, changes = corrector.correct(
            "Vileicht bin ich mude udn eigendlich trozdem entäuscht."
        )
        self.assertEqual(
            text, "Vielleicht bin ich müde und eigentlich trotzdem enttäuscht."
        )
        self.assertEqual(len(changes), 6)

    def test_german_mode_avoids_ambiguous_grammar_and_english_corrections(self):
        corrector = Autocorrect("de")
        text = "das dass seit seid wäre währe teh wierd Straße weiss"
        self.assertEqual(corrector.correct(text)[0], text)

    def test_language_must_be_supported(self):
        self.assertEqual(validate_language("de"), "de")
        with self.assertRaises(ValueError):
            Autocorrect("fr")


if __name__ == "__main__":
    unittest.main()
