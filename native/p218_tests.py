"""§218 tests: the two things the card wiki pin changed at runtime.

1. `blur` now really gives its Block (wiki: "Gain 5 (8) Block.") -- it only applied the status before.
2. `apparition`'s rarity is `Special`, and the run layer must therefore **not** offer it as a reward
   (that is the whole reason the bucket exists). This is the regression that broke six wasm tests when
   the rarity landed: `Rarity::from_name("Special")` returned `None`, so `full_pool()` refused the card
   table and *every* `rd_run_choose_start` failed with -2.
"""
import io

W = 'kernel/rd-wasm/src/lib.rs'
S = 'kernel/rd-run/src/state.rs'


def one(path, old, new, what):
    text = io.open(path, encoding='utf-8').read()
    assert text.count(old) == 1, '%s: %s expected 1, found %d' % (path, what, text.count(old))
    io.open(path, 'w', encoding='utf-8', newline='\n').write(text.replace(old, new))
    print('patched', path, '-', what)


one(W, '''    /// §218：''', '''    /// §218：''', 'noop')  # placeholder guard: the anchor below must exist
