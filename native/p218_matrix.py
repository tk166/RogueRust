"""§218 part 2: cards get a `SourceTie` of their own (`wiki:wiki_cards/<id>.txt`)."""
import io

P = 'native/coverage_matrix.py'
text = io.open(P, encoding='utf-8').read()


def one(old, new, what):
    global text
    assert text.count(old) == 1, '%s: expected 1, found %d' % (what, text.count(old))
    text = text.replace(old, new)


# checker 的表名 → 类别（矩阵的 `SourceTie` 靠它判断"有没有被钉住"）
one("""    'INV_NO_ASC_HP': 'monster', 'INV_UNWIRED': 'action',
}""",
    """    'INV_NO_ASC_HP': 'monster', 'INV_UNWIRED': 'action',
    # §218：卡牌的 wiki 对照（表在 `card_wiki_inventory.py`，字段由 `wiki_cards.py` 从 dump 读）
    'CARD_WIKI': 'card',
}""",
    'checker table map')

# 卡牌的 wiki dump：`wiki_cards/<基础 id>.txt`；升级行算"经基础牌继承"
one("""    page_monsters = {}""",
    """    # §218：卡牌的页面按**基础 id** 存一份（升级行没有独立页面）。
    card_wiki = {}
    if hasattr(C, 'load_card_wiki'):
        card_wiki = C.load_card_wiki()

    page_monsters = {}""",
    'load card wiki')

one("""            elif kind == 'action':
                owner = info['owner']""",
    """            elif kind == 'card':
                base_id = eid[:-1] if eid.endswith('+') else eid
                if base_id in card_wiki:
                    source = 'wiki:wiki_cards/%s.txt' % base_id
                    if base_id != eid:
                        source += ' (via %s)' % base_id
            elif kind == 'action':
                owner = info['owner']""",
    'card source tie')

# 卡牌的声明偏差也进 `DeclaredDeviation` 列
one("""            chunks = []
            if eid in C.INV_UNWIRED:""",
    """            chunks = []
            if kind == 'card':
                base_id = eid[:-1] if eid.endswith('+') else eid
                declared = getattr(C, 'CARD_WIKI_DEVIATIONS', {}).get(base_id)
                if declared:
                    chunks.append('wiki 偏差：%s' % declared)
            if eid in C.INV_UNWIRED:""",
    'card deviations')

io.open(P, 'w', encoding='utf-8', newline='\n').write(text)
print('matrix: card ties wired')
