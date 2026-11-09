"""Conservative, offline English and German spelling correction."""

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
import re

from .editor import Editor


ENGLISH_COMMON = {
    "teh": "the", "hte": "the", "adn": "and", "nad": "and",
    "thier": "their", "thsi": "this", "tihs": "this", "taht": "that",
    "wiht": "with", "wihout": "without", "becuase": "because",
    "beacuse": "because", "becasue": "because", "definately": "definitely",
    "definetly": "definitely", "defiantly": "defiantly",
    "seperate": "separate", "seperately": "separately", "recieve": "receive",
    "recieved": "received", "recieving": "receiving", "wierd": "weird",
    "freind": "friend", "freinds": "friends", "untill": "until",
    "tommorow": "tomorrow", "tommorrow": "tomorrow", "tomorow": "tomorrow",
    "yesturday": "yesterday", "tonigth": "tonight", "thougth": "thought",
    "thougths": "thoughts", "thigns": "things", "thign": "thing",
    "alot": "a lot", "agian": "again", "agaisnt": "against",
    "realy": "really", "reallly": "really", "fianlly": "finally",
    "finaly": "finally", "probaly": "probably", "proabably": "probably",
    "probelm": "problem", "probelms": "problems", "persue": "pursue",
    "ocurred": "occurred", "occured": "occurred", "occuring": "occurring",
    "begining": "beginning", "beleive": "believe", "beleiveing": "believing",
    "belive": "believe", "buisness": "business", "existance": "existence",
    "neccessary": "necessary", "necesary": "necessary", "neccessarily": "necessarily",
    "embarassed": "embarrassed", "embarassing": "embarrassing",
    "dissapointed": "disappointed", "dissapointing": "disappointing",
    "frusterated": "frustrated", "anxiuos": "anxious", "anxeity": "anxiety",
    "overwelmed": "overwhelmed", "overwhelemed": "overwhelmed",
    "struggeling": "struggling", "feelling": "feeling", "feal": "feel",
    "somtimes": "sometimes", "somehting": "something", "everythign": "everything",
    "nothign": "nothing", "jsut": "just", "judgement": "judgement",
    "acheive": "achieve", "acheived": "achieved", "awsome": "awesome",
    "writting": "writing", "langauge": "language", "exmaple": "example",
    "helo": "hello", "helllo": "hello", "pleasent": "pleasant",
    "dont": "don't", "doesnt": "doesn't", "didnt": "didn't", "isnt": "isn't",
    "wasnt": "wasn't", "werent": "weren't", "couldnt": "couldn't",
    "wouldnt": "wouldn't", "shouldnt": "shouldn't", "havent": "haven't",
    "hasnt": "hasn't", "hadnt": "hadn't", "arent": "aren't",
    "im": "I'm", "ive": "I've", "youre": "you're", "theyre": "they're",
    "i": "I",
}

GERMAN_COMMON = {
    "udn": "und", "dei": "die", "nihct": "nicht", "nciht": "nicht",
    "shcon": "schon", "mrogen": "morgen", "heuet": "heute",
    "abeiten": "arbeiten", "vileicht": "vielleicht", "villeicht": "vielleicht",
    "warscheinlich": "wahrscheinlich", "wahrscheindlich": "wahrscheinlich",
    "eigendlich": "eigentlich", "irgentwie": "irgendwie", "irgentwas": "irgendwas",
    "irgentwann": "irgendwann", "irgentwo": "irgendwo", "überhaubt": "überhaupt",
    "trozdem": "trotzdem", "nähmlich": "nämlich", "bischen": "bisschen",
    "entäuscht": "enttäuscht", "entäuschung": "Enttäuschung",
    "entäuschend": "enttäuschend", "standart": "Standard", "addresse": "Adresse",
    "packet": "Paket", "reperatur": "Reparatur", "terasse": "Terrasse",
    "vorraus": "voraus", "vorraussetzung": "Voraussetzung",
    "wiederspiegeln": "widerspiegeln", "hälst": "hältst", "zuruck": "zurück",
    "mude": "müde", "uber": "über", "fuhle": "fühle", "gefuhle": "Gefühle",
}

LANGUAGE_NAMES = {"en": "English", "de": "German"}


def validate_language(language: str) -> str:
    if language not in LANGUAGE_NAMES:
        raise ValueError("Autocorrect language must be 'en' or 'de'.")
    return language


@dataclass
class Correction:
    start: int
    before: str
    after: str

    def undo(self, editor: Editor) -> bool:
        end = self.start + len(self.after)
        if editor.text[self.start:end] != self.after:
            return False
        editor.text = editor.text[:self.start] + self.before + editor.text[end:]
        if editor.cursor >= end:
            editor.cursor += len(self.before) - len(self.after)
        elif editor.cursor > self.start:
            editor.cursor = self.start + len(self.before)
        return True


class Autocorrect:
    def __init__(self, language: str = "en") -> None:
        self.language = validate_language(language)
        self.common = ENGLISH_COMMON if language == "en" else GERMAN_COMMON
        self.words: dict[str, int] = {}
        if language == "en":
            with Path(__file__).with_name("data").joinpath("english.tsv").open(encoding="utf-8") as source:
                for line in source:
                    word, count = line.split()
                    self.words[word] = int(count)

    @staticmethod
    def _case(original: str, replacement: str) -> str:
        if original.isupper() and len(original) > 1:
            return replacement.upper()
        if original.istitle() and replacement != "I'm" and replacement != "I've":
            return replacement[0].upper() + replacement[1:]
        return replacement

    @lru_cache(maxsize=4096)
    def word(self, original: str) -> str:
        word = original.lower()
        if word in self.common:
            return self._case(original, self.common[word])
        if self.language == "de":
            return original
        # Leave real words, contractions, names, acronyms, and mixed case alone.
        if (word in self.words or not word.isascii() or not word.isalpha()
                or not original.islower() or not 4 <= len(word) <= 24):
            return original
        splits = [(word[:i], word[i:]) for i in range(len(word) + 1)]
        alphabet = "abcdefghijklmnopqrstuvwxyz"
        candidates = {left + right[1:] for left, right in splits if right}
        candidates.update(left + right[1] + right[0] + right[2:]
                          for left, right in splits if len(right) > 1)
        candidates.update(left + char + right[1:] for left, right in splits if right for char in alphabet)
        candidates.update(left + char + right for left, right in splits for char in alphabet)
        ranked = sorted(((self.words[c], c) for c in candidates if c in self.words), reverse=True)
        # Prefer leaving ambiguity alone to replacing an intentional word.
        if not ranked or ranked[0][0] < 1_000_000:
            return original
        if len(ranked) > 1 and ranked[0][0] < 5 * ranked[1][0]:
            return original
        return ranked[0][1]

    def correct(self, text: str, *, offset: int = 0) -> tuple[str, list[Correction]]:
        changes: list[Correction] = []
        shift = 0

        def replace(match: re.Match[str]) -> str:
            nonlocal shift
            token = match.group()
            if any(c in token for c in "/\\@_=`") or "://" in token:
                return token
            parts = re.fullmatch(
                r"([^\w]*)([^\W\d_]+(?:['’][^\W\d_]+)*)([^\w]*)", token)
            if not parts:
                return token
            before = parts[2]
            after = self.word(before)
            if before != after:
                changes.append(Correction(offset + match.start() + len(parts[1]) + shift, before, after))
                shift += len(after) - len(before)
            return parts[1] + after + parts[3]

        return re.sub(r"\S+", replace, text), changes

    def at_cursor(self, editor: Editor) -> list[Correction]:
        prefix = editor.text[:editor.cursor]
        match = re.search(r"\S+$", prefix)
        if not match:
            return []
        new, changes = self.correct(match.group(), offset=match.start())
        if changes:
            editor.text = prefix[:match.start()] + new + editor.text[editor.cursor:]
            editor.cursor = match.start() + len(new)
        return changes
