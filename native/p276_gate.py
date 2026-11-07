"""§276 闸门表：L 史莱姆的怪物/动作/升阶/状态/遭遇/计数（全部幂等）。

一张表一个理由：
* `INV_MONSTERS` —— HP 区间与招式清单（roster 的真相）；
* `INV_ACTIONS` —— 每条动作的**事实**（伤害/状态/造牌）；
* `INV_ASC_VARIANTS` —— A2 的伤害档与 A17 的 Lick 档；
* `INV_STATUSES` —— 两条分裂状态；
* `INV_WEAK_POOL` / `INV_ACT_TABLES` —— 两条遭遇；
* `INV_COUNTS` —— 三个数量。
"""
import io

P = 'D:/Vibe/sts-tui/native/sts_content_check.py'


def patch(src, old, new, what, count=1):
    got = src.count(old)
    assert got == count, '%s: %d matches (want %d)' % (what, got, count)
    return src.replace(old, new)


MONSTERS = '''    ("acid_slime_s", 8, 12, ["acid_slime_s.tackle", "acid_slime_s.lick"]),'''

MONSTERS_NEW = '''    ("acid_slime_s", 8, 12, ["acid_slime_s.tackle", "acid_slime_s.lick"]),
    # §276: the L slimes (act 1, wiki.gg `Slimes`). HP 64-70 / 65-69, A7 67-73 / 68-72.
    ("spike_slime_l", 64, 70, ["spike_slime_l.lick", "spike_slime_l.flame_tackle"]),
    ("acid_slime_l", 65, 69, ["acid_slime_l.corrosive_spit", "acid_slime_l.lick",
                              "acid_slime_l.tackle"]),'''

ACTIONS = '''    "spike_slime_m.flame_tackle": ("Attack", [("damage", 8, "event"),'''
ACTIONS_NEW = '''    # §276: the L slimes. Lick's A17 档（3 Frail）与 A2 的伤害档见 INV_ASC_VARIANTS。
    "spike_slime_l.lick": ("Debuff", [("status", "standard.frail", 2, "event")]),
    "spike_slime_l.flame_tackle": ("Attack", [("damage", 16, "event"),
                                              ("card", "slimed", 2, "DiscardPile", "event")]),
    "acid_slime_l.corrosive_spit": ("Attack", [("damage", 11, "event"),
                                               ("card", "slimed", 2, "DiscardPile", "event")]),
    "acid_slime_l.lick": ("Debuff", [("status", "standard.weak", 2, "event")]),
    "acid_slime_l.tackle": ("Attack", [("damage", 16, "event")]),
    "spike_slime_m.flame_tackle": ("Attack", [("damage", 8, "event"),'''

ASC = '''    'acid_slime_m.corrosive_spit': [(2, [('damage', 8, 'event'), ('card', 'slimed', 1, 'DiscardPile', 'event')])],'''
ASC_NEW = '''    # §276: L slimes -- A2 的伤害档 + Spike Lick 的 A17 档。
    'spike_slime_l.flame_tackle': [(2, [('damage', 18, 'event'),
                                       ('card', 'slimed', 2, 'DiscardPile', 'event')])],
    'spike_slime_l.lick': [(17, [('status', 'standard.frail', 3, 'event')])],
    'acid_slime_l.corrosive_spit': [(2, [('damage', 12, 'event'),
                                        ('card', 'slimed', 2, 'DiscardPile', 'event')])],
    'acid_slime_l.tackle': [(2, [('damage', 18, 'event')])],
    'acid_slime_m.corrosive_spit': [(2, [('damage', 8, 'event'), ('card', 'slimed', 1, 'DiscardPile', 'event')])],'''

WEAK = '''    "enc_swarm_of_slimes": ["spike_slime_s", "spike_slime_s", "spike_slime_s",
                            "acid_slime_s", "acid_slime_s"],
}'''
WEAK_NEW = '''    "enc_swarm_of_slimes": ["spike_slime_s", "spike_slime_s", "spike_slime_s",
                            "acid_slime_s", "acid_slime_s"],
    # §276: 原作 `Large Slime` 是"随机 Spike L 或 Acid L"（重量 2）；静态内容拆成两条各 7。
    "enc_spike_slime_l": ["spike_slime_l"],
    "enc_acid_slime_l": ["acid_slime_l"],
}'''

ACT_TABLE = '''             "enc_swarm_of_slimes"],'''
ACT_TABLE_NEW = '''             "enc_swarm_of_slimes",
             # §276：L 史莱姆（原作 `Large Slime` 的两种掷法，拆成两条）。
             "enc_spike_slime_l", "enc_acid_slime_l"],'''


def main():
    s = io.open(P, encoding='utf-8').read()

    s = patch(s, MONSTERS, MONSTERS_NEW, 'INV_MONSTERS')
    s = patch(s, ACTIONS, ACTIONS_NEW, 'INV_ACTIONS')
    s = patch(s, ASC, ASC_NEW, 'INV_ASC_VARIANTS')
    s = patch(s, WEAK, WEAK_NEW, 'INV_WEAK_POOL')
    s = patch(s, ACT_TABLE, ACT_TABLE_NEW, 'INV_ACT_TABLES')

    # 状态清单：两条分裂
    old_status = '    "standard.split": [],'

    assert s.count(old_status) >= 1
    s = s.replace(old_status, old_status + chr(10) +
                  '    # §276: 两条 50% 分裂（L 史莱姆）。阈值是"一半最大血"，spawn 的血量是**当前血**。' + chr(10) +
                  '    "standard.split_spike_l",' + chr(10) +
                  '    "standard.split_acid_l",', 1)

    # 数量
    s = s.replace('    "monsters": 47,', '    "monsters": 49,')
    s = s.replace('    "statuses": 124,', '    "statuses": 126,')
    s = s.replace('    "encounters": 39,', '    "encounters": 41,')
    io.open(P, 'w', encoding='utf-8', newline='\n').write(s)
    print('gate tables updated')


main()
