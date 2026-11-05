"""§221: pin the ten new cards in both inventories (INV_CARDS + card_wiki_inventory).

The `INV_CARDS` rows are generated from the content and then eyeballed against the wiki text; the
wiki side (`card_wiki_inventory.FACTS`) is written from `native/wiki_cards/*.txt` (the `(a;b)` pairs).
Keeping the two independent is the whole point: `check_card_wiki` compares them.
"""
import io

P = 'native/sts_content_check.py'
INV = 'native/card_wiki_inventory.py'
text = io.open(P, encoding='utf-8').read()

ANCHOR = '''    # §219：wiki 是"1 费、可出、Exhaust"'''
assert text.count(ANCHOR) == 1

ROWS = '''    # ---- §221: ten more Ironclad cards (wiki numbers; `native/wiki_cards/<id>.txt`) ----------------
    "cleave": {"Cost": 1, "Tags": ["attack"], "Facts": [("damage", 8, "allEnemies")]},
    "cleave+": {"Cost": 1, "Tags": ["attack"], "Facts": [("damage", 11, "allEnemies")]},
    "pommel_strike": {"Cost": 1, "Tags": ["attack", "strike"],
                      "Facts": [("damage", 9, "event"), ("draw", 1, "source")]},
    "pommel_strike+": {"Cost": 1, "Tags": ["attack", "strike"],
                       "Facts": [("damage", 10, "event"), ("draw", 2, "source")]},
    "shrug_it_off": {"Cost": 1, "Tags": ["skill", "block"],
                     "Facts": [("block", 8, "source"), ("draw", 1, "source")]},
    "shrug_it_off+": {"Cost": 1, "Tags": ["skill", "block"],
                      "Facts": [("block", 11, "source"), ("draw", 1, "source")]},
    "thunderclap": {"Cost": 1, "Tags": ["attack"],
                    "Facts": [("damage", 4, "allEnemies"),
                              ("status", "standard.vulnerable", 1, "allEnemies")]},
    "thunderclap+": {"Cost": 1, "Tags": ["attack"],
                     "Facts": [("damage", 7, "allEnemies"),
                               ("status", "standard.vulnerable", 1, "allEnemies")]},
    "bludgeon": {"Cost": 3, "Tags": ["attack"], "Facts": [("damage", 32, "event")]},
    "bludgeon+": {"Cost": 3, "Tags": ["attack"], "Facts": [("damage", 42, "event")]},
    "impervious": {"Cost": 2, "Tags": ["skill", "block"], "Facts": [("block", 30, "source")],
                   "PlayedCardDestinationZone": "ExhaustPile"},
    "impervious+": {"Cost": 2, "Tags": ["skill", "block"], "Facts": [("block", 40, "source")],
                    "PlayedCardDestinationZone": "ExhaustPile"},
    "pummel": {"Cost": 1, "Tags": ["attack"], "Facts": [("repeat", 4, "damage", 2, "event")],
               "PlayedCardDestinationZone": "ExhaustPile"},
    "pummel+": {"Cost": 1, "Tags": ["attack"], "Facts": [("repeat", 5, "damage", 2, "event")],
                "PlayedCardDestinationZone": "ExhaustPile"},
    "wild_strike": {"Cost": 1, "Tags": ["attack", "strike"],
                    "Facts": [("damage", 12, "event"), ("card", "wound", 1, "DrawPile", "source")]},
    "wild_strike+": {"Cost": 1, "Tags": ["attack", "strike"],
                     "Facts": [("damage", 17, "event"), ("card", "wound", 1, "DrawPile", "source")]},
    "ghostly_armor": {"Cost": 1, "Tags": ["skill", "block", "ethereal"],
                      "Facts": [("block", 10, "source")],
                      "TurnEndHandDestinationZone": "ExhaustPile"},
    "ghostly_armor+": {"Cost": 1, "Tags": ["skill", "block", "ethereal"],
                       "Facts": [("block", 13, "source")],
                       "TurnEndHandDestinationZone": "ExhaustPile"},
    "battle_trance": {"Cost": 0, "Tags": ["skill"],
                      "Facts": [("draw", 3, "source"), ("status", "standard.draw_reduction", 1, "source")]},
    "battle_trance+": {"Cost": 0, "Tags": ["skill"],
                       "Facts": [("draw", 4, "source"), ("status", "standard.draw_reduction", 1, "source")]},
'''
text = text.replace(ANCHOR, ROWS + ANCHOR)
io.open(P, 'w', encoding='utf-8', newline='\n').write(text)
print('INV_CARDS rows added')

# ── wiki 侧的事实（抄自 dump 的 `(a;b)`） ───────────────────────────────────────────────────────
inv = io.open(INV, encoding='utf-8').read()
ANCHOR2 = """    # 没有数字的牌：纯关键字/状态牌。"""
assert inv.count(ANCHOR2) == 1
WIKI = """    # ---- §221: the ten new cards, transcribed from `native/wiki_cards/*.txt` -------------------
    'cleave': ([('damage', 8, 'allEnemies')], [('damage', 11, 'allEnemies')]),
    'pommel_strike': ([('damage', 9, 'event'), ('draw', 1, 'source')],
                      [('damage', 10, 'event'), ('draw', 2, 'source')]),
    'shrug_it_off': ([('block', 8, 'source'), ('draw', 1, 'source')],
                     [('block', 11, 'source'), ('draw', 1, 'source')]),
    'thunderclap': ([('damage', 4, 'allEnemies'),
                     ('status', 'standard.vulnerable', 1, 'allEnemies')],
                    [('damage', 7, 'allEnemies'),
                     ('status', 'standard.vulnerable', 1, 'allEnemies')]),
    'bludgeon': ([('damage', 32, 'event')], [('damage', 42, 'event')]),
    'impervious': ([('block', 30, 'source')], [('block', 40, 'source')]),
    'pummel': ([('repeat', 4, 'damage', 2, 'event')], [('repeat', 5, 'damage', 2, 'event')]),
    'wild_strike': ([('damage', 12, 'event'), ('card', 'wound', 1, 'DrawPile', 'source')],
                    [('damage', 17, 'event'), ('card', 'wound', 1, 'DrawPile', 'source')]),
    'ghostly_armor': ([('block', 10, 'source')], [('block', 13, 'source')]),
    'battle_trance': ([('draw', 3, 'source'),
                       ('status', 'standard.draw_reduction', 1, 'source')],
                      [('draw', 4, 'source'),
                       ('status', 'standard.draw_reduction', 1, 'source')]),
"""
inv = inv.replace(ANCHOR2, WIKI + ANCHOR2)
io.open(INV, 'w', encoding='utf-8', newline='\n').write(inv)
print('card_wiki_inventory rows added')
