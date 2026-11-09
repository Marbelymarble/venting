# Third-party data

`venting/data/english.tsv` is derived from the English frequency dictionary in
[symspellpy](https://github.com/mammothb/symspellpy), itself distributed from
[SymSpell](https://github.com/wolfgarbe/SymSpell).

Source: `symspellpy/frequency_dictionary_en_82_765.txt`, retrieved 2026-10-20.
Transformation: retained ASCII alphabetic entries and their original counts,
one space-separated word/count pair per line. Despite the historical source
filename, this snapshot contains 82,769 retained entries. Venting uses its own
small spelling-correction implementation; it does not bundle either library's
algorithm or require either Python package at runtime.

The upstream dictionary combines Google Books Ngram frequencies with SCOWL
English word lists. Attribution and source links:

- [SymSpell dictionary documentation](https://github.com/wolfgarbe/SymSpell#frequency-dictionary)
- [Google Books Ngram data](https://storage.googleapis.com/books/ngrams/books/datasetsv2.html),
  distributed under [CC BY 3.0](https://creativecommons.org/licenses/by/3.0/)
- [SCOWL](http://wordlist.aspell.net/),
  [copyright notices](http://wordlist.aspell.net/scowl-readme/#copyright)

Upstream MIT notices are included in `venting/data/SymSpell-LICENSE.txt` and
`venting/data/symspellpy-LICENSE.txt`. Additional dictionary source notices are
in `venting/data/SCOWL-LICENSE.txt`.
