"""§220 part C fix-up: the exact `INV_CARDS` rows (the earlier patch guessed the shapes wrong)."""
import io

P = 'native/sts_content_check.py'
text = io.open(P, encoding='utf-8').read()


def one(old, new, what):
    global text
    assert text.count(old) == 1, '%s: expected 1, found %d' % (what, text.count(old))
    text = text.replace(old, new)


one('''    "sentinel": {"Cost": 1, "Tags": ["skill", "ethereal"],
                 "Facts": [("block", 5, "source")],
                 "TurnEndHandDestinationZone": "ExhaustPile"},''',
    '''    # §220：wiki 的 "If this card is Exhausted, gain 2 Energy." 现在有载体了
    # （`LifecyclePrograms[Exhausted]`；`ethereal` 标签仍是本内容的简化 —— wiki 没有 Ethereal）。
    "sentinel": {"Cost": 1, "Tags": ["skill", "ethereal"],
                 "Facts": [("block", 5, "source")],
                 "TurnEndHandDestinationZone": "ExhaustPile",
                 "Lifecycle": {"Exhausted": [("gain", "standard.energy", 2, "source")]}},''',
    'sentinel')

one('''    "sentinel+": {"Cost": 1, "Tags": ["skill", "ethereal"],
                  "Facts": [("block", 8, "source")]},''',
    '''    # §220：节目挂在**定义**上，所以升级行有自己的一份（3 点能量）。
    "sentinel+": {"Cost": 1, "Tags": ["skill", "ethereal"],
                  "Facts": [("block", 8, "source")],
                  "Lifecycle": {"Exhausted": [("gain", "standard.energy", 3, "source")]}},''',
    'sentinel+')

one('''    # Awakened One's Sludge adds a Void. The wiki's Void also makes you lose 1 Energy when drawn;
    # nothing here can say "the card that just moved is this one", so that half is absent -- and the
    # card's own text says only what happens.
    "void": {"Cost": 1, "Tags": ["status", "unplayable", "ethereal", "junk"],
             "Facts": []},''',
    '''    # Awakened One's Sludge adds a Void. §220 gave the missing half a carrier:
    # `LifecyclePrograms[Drawn]` fires from `state.move_card` (draw pile -> hand), so
    # "Whenever this card is drawn, lose 1 Energy" is real now. (The old comment here said
    # "nothing here can say 'the card that just moved is this one'" -- that was true until §220.)
    "void": {"Cost": 1, "Tags": ["status", "unplayable", "ethereal", "junk"],
             "Facts": [],
             "Lifecycle": {"Drawn": [("lose", "standard.energy", 1, "source")]}},''',
    'void')

io.open(P, 'w', encoding='utf-8', newline='\n').write(text)
print('INV_CARDS rows patched')
