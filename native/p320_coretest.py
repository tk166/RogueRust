"""§320：`rd-core` 的两处清单（事件数 22 → 24、闭词表加 `offer_cards:`）。"""

import io

PATH = 'kernel/rd-core/src/content.rs'

def sub(t, old, new, label):
    n = t.count(old)
    assert n == 1, '%s: %d' % (label, n)
    return t.replace(old, new)

t = io.open(PATH, encoding='utf-8').read()

t = sub(t, """            content.event_count(),
            22,""", """            content.event_count(),
            24,""", 'event count')

t = sub(t, """             §318 补了 `winding_halls` / `mysterious_sphere`（`scrap_pile` 改成 Scrap Ooze 的 9 段链），
             §319 补了 `falling`。pools 的**位次**比""",
        """             §318 补了 `winding_halls` / `mysterious_sphere`（`scrap_pile` 改成 Scrap Ooze 的 9 段链），
             §319 补了 `falling`，§320 补了 `the_library` / `sensory_stone`。pools 的**位次**比""",
        'event count comment')

t = sub(t, """                // §319：按**类型**随机删一张（`falling` 的 `remove_card_random:skill`）。
                || prefix(effect, "remove_card_random:")""",
        """                // §319：按**类型**随机删一张（`falling` 的 `remove_card_random:skill`）。
                || prefix(effect, "remove_card_random:")
                // §320：事件候选列表（`The Library` 的 20 选 1、`Sensory Stone` 的无色牌）。
                || prefix(effect, "offer_cards:")""",
        'effect vocabulary')

t = sub(t, """                "dead_adventurer",
                // §319
                "falling",""",
        """                "dead_adventurer",
                // §319
                "falling",""", 'sanity') if False else t

t = sub(t, """                "scrap_pile",
                "shining_light",
                "the_cleric",""",
        """                // §320
                "sensory_stone",
                "scrap_pile",
                "shining_light",
                "the_cleric",
                "the_library",""",
        'event id list')

io.open(PATH, 'w', encoding='utf-8', newline='\n').write(t)
print('rd-core test lists patched')
