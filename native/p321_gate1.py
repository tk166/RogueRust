"""§321 内容门：认识 `upgrade_all`、条件 `floor`、以及 `Fight: "boss"`。

这些都是"第二意见"表 —— 第一份在 `rd-core`（`run_expr::KINDS` / `content.rs` 的 `Fight` 映射）
与 `rd-run`（`EventEffect::parse`）。两边漂了就在这里红。
"""

import io

PATH = 'native/sts_content_check.py'


def sub(t, old, new, label):
    n = t.count(old)
    assert n == 1, '%s: %d' % (label, n)
    return t.replace(old, new)


t = io.open(PATH, encoding='utf-8').read()

t = sub(t, """                  # §319：`card_tag` —— "牌组里有一张 <tag> 牌"（`Falling` 的三个选项各自
                  # 按类型上锁）。`Id` 必须是下面 `CARD_KIND_NAMES` 里的一个。
                  "card_tag")""",
        """                  # §319：`card_tag` —— "牌组里有一张 <tag> 牌"（`Falling` 的三个选项各自
                  # 按类型上锁）。`Id` 必须是下面 `CARD_KIND_NAMES` 里的一个。
                  "card_tag",
                  # §321：`floor` —— **本幕内的层号**（`mind_bloom` 的第三个选项按它换）。
                  "floor")""",
        'REQUIRES_KINDS floor')

t = sub(t, """REQUIRES_NUMERIC = ("gold", "health", "max_health", "health_percent", "deck_count", "ascension",
                    "card_damage")""",
        """REQUIRES_NUMERIC = ("gold", "health", "max_health", "health_percent", "deck_count", "ascension",
                    "card_damage", "floor")""",
        'REQUIRES_NUMERIC floor')

t = sub(t, """EVENT_BARE_EFFECTS = ("heal", "gold", "damage", "max_hp", "nothing", "heal_full",
                      "remove_card", "upgrade_card", "transform_card")""",
        """EVENT_BARE_EFFECTS = ("heal", "gold", "damage", "max_hp", "nothing", "heal_full",
                      "remove_card", "upgrade_card", "transform_card",
                      # §321：升级**所有**牌（`mind_bloom` 的 `[I am Awake]`）。
                      "upgrade_all")""",
        'EVENT_BARE_EFFECTS upgrade_all')

io.open(PATH, 'w', encoding='utf-8', newline='\n').write(t)
print('content gate: upgrade_all / floor ok')
