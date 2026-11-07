#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""sts_content_check.py -- the gate for `tools/contentc/packages/sts/**`.

WHY THREE LAYERS (each one alone is a false green)
--------------------------------------------------
1. INV    every number in the content is compared against the number in
          `docs/spec/sts-act1-inventory.md`.  The table in this file is
          hand-written (each row carries its `inv:§x`), so this is the layer
          that catches "the source document and the image agree, and both are
          wrong".  A round-trip-only gate can never catch that.
2. ROUND  every entity (4 row tables + every root key) is read back out of BOTH
          images with `reader.py` and compared per key against the source
          document -- **key presence included**, and a key the source does not
          have is a mismatch too (so "the image grew a fact nobody re-checked"
          is red, not silent).  The one exception is the compiler's own
          `DOC_ROOT_KEYS` (build metadata: `InertKeys`, `Notes`): those are
          stored in neither image, and the gate *asserts* that absence.
          The core image's expectation is derived with `compile.py`'s own
          `strip_presentation`, not with a second copy of that rule: a copy is
          the classic "second source of truth rots" bug (`contentc-audit.md` §7).
3. XREF   the cross references resolve and are consistent: deck -> cards,
          encounter -> monster roster (field by field, because the roster is a
          duplicate of the encounter's inline record), roster -> enemy actions,
          every status a program names -> a STAT row, every id -> the right
          entity kind in `SEC_IDX`.
4. INERT  a key the kernel never reads must be *declared* inert in the
          document's `InertKeys` block, with the reason it can stay.  The
          round-trip layer is blind to this class: "the image agrees with the
          source" is true for a key nobody consumes.  Derivation and the rot
          directions are in §2b.  A `root:` declaration may name a **sub-key**
          (`root:Start.MaxHealth`, `root:Characters[].UnlockFlag`) because the
          unit of the fact is "which field of that object is unused", not "the
          whole object is unused" -- root-key granularity lost five facts the
          moment the kernel learned to read `Start.Deck`.

Plus two failure modes that are cheap to forget:
* an image older than its source document is red (`build.py --package sts`),
  because a stale image is the most expensive kind of green;
* every effect program is mechanically reduced to a list of *facts*
  (`damage 6 to event` / `status standard.weak 1 to event` / ...) and compared
  against the expected fact list -- a fact that is present but not expected is
  a failure (the inventory says "extra also counts as failure").

Exit codes: 0 all green, 1 a check failed, 2 precondition missing (no image,
no source, stale image).
"""

import argparse
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
CONTENTC = os.path.join(ROOT, "tools", "contentc")
sys.path.insert(0, CONTENTC)

import rdcfmt as F            # noqa: E402  (the frozen on-disk vocabulary)
import reader as rdcf_reader  # noqa: E402  (the reference reader)
import compile as contentc_compile  # noqa: E402  (strip_presentation + DOC_ROOT_KEYS)
import program_audit as audit   # noqa: E402  (§249: 内容用到的表达式 kind 是否可实现)

PKG_DIR = os.path.join(CONTENTC, "packages", "sts")
SRC_PATH = os.path.join(PKG_DIR, "sts.roguedeck.json")
FULL_PATH = os.path.join(PKG_DIR, "out", "content.sts.rdcf")
CORE_PATH = os.path.join(PKG_DIR, "out", "content.sts.core.rdcf")

# =============================================================================
# 1.  inv -- the numbers, each row carrying the section it came from
# =============================================================================
# `docs/spec/sts-act1-inventory.md` is the only source of numbers.  Nothing in
# this file may be "tuned to make the content pass": if a number here disagrees
# with the content, one of the two is wrong and a human has to look.

# inv:§1 -- the counts this milestone promises (the task's quantity gate).
INV_COUNTS = {
    # 10 tier-A monsters + three sentry **rows** (one per instance: a combatant id must be unique
    # and the encounter record has no instance number, inv:§4.2) + the boss.
    # §173: +3 (Lagavulin / Book of Stabbing / Taskmaster); §175: +3 (Nemesis / Reptomancer / Dagger).
    # §201: +1 (Looter).
    "monsters": 47,
    # 3 weak-pool encounters + 1 elite (`enc_three_sentries`) + 1 boss (`enc_slime_boss`).
    # §173: +3 (lagavulin / book of stabbing / slavers); §175: +2 (nemesis / reptomancer).
    # §201: +1 (`enc_looter`, the solo Looter).
    # §258: +1 (`enc_two_louses` -- the green louse was unreachable).
    "encounters": 35,
    "deck": 10,          # inv:§2   "10 张：strike x5、defend x4、bash x1"
    # §175: +1 -- `standard.phantom_veil`, the carrier for Nemesis's "intangible every other turn".
    # It is the first content row that uses a `TurnStarted` trigger.
    # §180: +1 -- `standard.fairy_in_a_bottle`, the first row that uses `DeathPrevention`.
    # §181: +1 -- `standard.duplication`, the first `UsesCharges` status the kernel consumes.
    # §208: +1 (`standard.flying`); §209: +1 (`standard.curl_up`); §213: +1 (`standard.hex`).
    # §227: +1 (`standard.nightmare_pending`, Nightmare 的"下一回合"载体).
    # §231: +1 (`standard.no_draw`, Battle Trance 的"本回合不能再抽").
    # §235: +1 (`standard.demon_form`, Demon Form 的每回合加力量).
    # §236: +2 (`standard.brutality` / `standard.rupture`).
    # §237: +5 (five trigger-hook powers).
    # §238: +1 (`standard.double_tap`, the second duplication scope).
    # §242: +1 (`standard.corruption`).
    # §244: +2 (`standard.mayhem` / `standard.magnetism`).
    # §245: +1 (`standard.no_block_from_cards`).
    # §248: +1 (`standard.cap_cost_at`).
    # §249: +5 (`omega` / `panache` / `sadistic_nature` / `the_bomb` + its damage twin).
    # §256: +1 (`painful_stabs`).
    # §257: +1 (`lagavulin_asleep`).
    # §260: +8 (the eight relic carrier statuses).
    # §261: +4 (`lantern` / `bag_of_preparation` / `ice_cream` / `calipers` -- `du_vu_doll`
    # grants plain Strength, so it needs no carrier).
    # §262: +8 (seven carriers + `double_damage`).
    # §263: +5 (enemy-death pair + three damage rewrites) +1 (`standard.poison`, the first
    # damage-over-time status this content has -- The Specimen needs it).
    # §264: +3 (two `AppliesToStatusId` rewriters + `champion_belt`).
    # §265: +3 (`snecko_skull` / `ginger` / `turnip`).
    # §266: +2 (`red_skull` / `odd_mushroom`).
    # §267: +13 (the zero-infrastructure relic batch).
    # §268: +5 (the zero-infrastructure tail).
    # §269: +2 (`slavers_collar` / `busted_crown` energy carriers).
    # §270: +1 (`ectoplasm`'s energy carrier).
    "statuses": 122,
}

# inv:§2 / §2.1 -- the hero.
INV_HERO = {
    "HeroName": "Ironclad",
    "MaxHealth": 80,
    "StartingHealth": 80,
    "EnergyCurrent": 3,          # inv:§2 起始能量 3
    "EnergyMax": 3,
    "CardsDrawnPerTurn": 5,      # inv:§2 起手抽牌 5（通用规则）
}
INV_DECK = {"strike": 5, "defend": 4, "bash": 1}   # inv:§2.1

# inv:§3.1 -- the 3 basic cards, as mechanically derived facts.
INV_CARDS = {
    # ---- §255：Conjure Blade / Conjure Blade+（2 行）----------------------------------------
    "conjure_blade": {"Cost": 0, "Tags": ["skill", "x_cost", "watcher"], "Facts": [["card", "expunger", 1, "DrawPile", "source"]]},
    "conjure_blade+": {"Cost": 0, "Tags": ["skill", "x_cost", "watcher"], "Facts": [["card", "expunger", 1, "DrawPile", "source"]]},
    # ---- §254：Wish / Wish+（2 行）----------------------------------------------------------
    "wish": {"Cost": 3, "Tags": ["skill", "watcher"], "Facts": [["offerList", ["become_almighty", "live_forever", "fame_and_fortune"], 1, 1, "PlayChosen"]]},
    "wish+": {"Cost": 3, "Tags": ["skill", "watcher"], "Facts": [["offerList", ["become_almighty+", "live_forever+", "fame_and_fortune+"], 1, 1, "PlayChosen"]]},
    # ---- §252：剩下 6 张 / 12 行 ------------------------------------------------------------
    "through_violence": {"Cost": 0, "Tags": ["attack", "colorless", "retain"], "Facts": [["damage", 20, "event"]]},
    "through_violence+": {"Cost": 0, "Tags": ["attack", "colorless", "retain"], "Facts": [["damage", 30, "event"]]},
    "j.a.x.": {"Cost": 0, "Tags": ["skill", "colorless"], "Facts": [["loseHp", 3, "source"], ["status", "standard.strength", 2, "source"]]},
    "j.a.x.+": {"Cost": 0, "Tags": ["skill", "colorless"], "Facts": [["loseHp", 3, "source"], ["status", "standard.strength", 3, "source"]]},
    "safety": {"Cost": 1, "Tags": ["skill", "colorless", "retain"], "Facts": [["block", 12, "source"]]},
    "safety+": {"Cost": 1, "Tags": ["skill", "colorless", "retain"], "Facts": [["block", 16, "source"]]},
    "become_almighty": {"Cost": 1, "Tags": ["power", "colorless", "unplayable"], "Facts": [["status", "standard.strength", 3, "source"]]},
    "become_almighty+": {"Cost": 1, "Tags": ["power", "colorless", "unplayable"], "Facts": [["status", "standard.strength", 4, "source"]]},
    "live_forever": {"Cost": 1, "Tags": ["power", "colorless", "unplayable"], "Facts": [["status", "standard.plated_armor", 6, "source"]]},
    "live_forever+": {"Cost": 1, "Tags": ["power", "colorless", "unplayable"], "Facts": [["status", "standard.plated_armor", 8, "source"]]},
    "fame_and_fortune": {"Cost": 1, "Tags": ["skill", "colorless", "unplayable"], "Facts": [["gold", 25]]},
    "fame_and_fortune+": {"Cost": 1, "Tags": ["skill", "colorless", "unplayable"], "Facts": [["gold", 30]]},
    # ---- §251：A 组（5 张 / 10 行）---------------------------------------------------------
    "bite": {"Cost": 1, "Tags": ["attack", "colorless"], "Facts": [["damage", 7, "event"], ["heal", 2, "source"]]},
    "bite+": {"Cost": 1, "Tags": ["attack", "colorless"], "Facts": [["damage", 8, "event"], ["heal", 3, "source"]]},
    "expunger": {"Cost": 1, "Tags": ["attack", "colorless"], "Facts": [["repeat", ["cardCounter", "standard.expunger_x"], "damage", 9, "event"]]},
    "expunger+": {"Cost": 1, "Tags": ["attack", "colorless"], "Facts": [["repeat", ["cardCounter", "standard.expunger_x"], "damage", 15, "event"]]},
    "shiv": {"Cost": 0, "Tags": ["attack", "colorless"], "Facts": [["damage", 4, "event"]]},
    "shiv+": {"Cost": 0, "Tags": ["attack", "colorless"], "Facts": [["damage", 6, "event"]]},
    "smite": {"Cost": 1, "Tags": ["attack", "colorless", "retain"], "Facts": [["damage", 12, "event"]]},
    "smite+": {"Cost": 1, "Tags": ["attack", "colorless", "retain"], "Facts": [["damage", 16, "event"]]},
    "beta": {"Cost": 2, "Tags": ["skill", "colorless"], "Facts": [["card", "omega", 1, "DrawPile", "source"]]},
    "beta+": {"Cost": 1, "Tags": ["skill", "colorless"], "Facts": [["card", "omega", 1, "DrawPile", "source"]]},
    # ---- §250：B/C/D/F 四组（14 张牌 / 18 行）-----------------------------
    "ritual_dagger": {"Cost": 1, "Tags": ["attack", "colorless"], "Facts": [["damage", ["add", 15, ["multiply", ["cardCounter", "standard.ritual_dagger_bonus"], 3]], "event"], ["fatal", "cardCounter", "cardInstance.resolving", "standard.ritual_dagger_bonus", 3, "Add"]]},
    "ritual_dagger+": {"Cost": 1, "Tags": ["attack", "colorless"], "Facts": [["damage", ["add", 15, ["multiply", ["cardCounter", "standard.ritual_dagger_bonus"], 5]], "event"], ["fatal", "cardCounter", "cardInstance.resolving", "standard.ritual_dagger_bonus", 5, "Add"]]},
    "hand_of_greed": {"Cost": 2, "Tags": ["attack", "colorless"], "Facts": [["damage", 20, "event"], ["fatal", "gold", 20]]},
    "hand_of_greed+": {"Cost": 2, "Tags": ["attack", "colorless"], "Facts": [["damage", 25, "event"], ["fatal", "gold", 25]]},
    "discovery": {"Cost": 1, "Tags": ["skill", "colorless"], "Facts": [["offer", 3, 1, 1, "ToHandFree"]]},
    "discovery+": {"Cost": 1, "Tags": ["skill", "colorless"], "Facts": [["offer", 3, 1, 1, "ToHandFree"]]},
    "forethought": {"Cost": 0, "Tags": ["skill", "colorless"], "Facts": [["choose", "source", "Hand", [], 1, 1, "ToDrawPileBottomFree"]]},
    "forethought+": {"Cost": 0, "Tags": ["skill", "colorless"], "Facts": [["choose", "source", "Hand", [], 0, 10, "ToDrawPileBottomFree"]]},
    "clumsy": {"Cost": 1, "Tags": ["curse", "unplayable", "ethereal"], "Facts": []},
    "curse_of_the_bell": {"Cost": 1, "Tags": ["curse", "unplayable"], "Facts": []},
    "decay": {"Cost": 1, "Tags": ["curse", "unplayable"], "Facts": [], "Lifecycle": {"TurnEndInHand": [["damage", 2, "source"]]}},
    "necronomicurse": {"Cost": 1, "Tags": ["curse", "unplayable"], "Facts": [], "Lifecycle": {"Exhausted": [["copySelf", "necronomicurse", "Hand", "Bottom", 1]]}},
    "normality": {"Cost": 1, "Tags": ["curse", "unplayable"], "Facts": [], "Lifecycle": {"Drawn": [["counter", "card_play_cap", 3, False, "source"]], "TurnEndInHand": [["counter", "card_play_cap", 0, False, "source"]]}},
    "pain": {"Cost": 1, "Tags": ["curse", "unplayable"], "Facts": [], "Lifecycle": {"CardPlayedInHand": [["loseHp", 1, "source"]]}},
    "parasite": {"Cost": 1, "Tags": ["curse", "unplayable"], "Facts": []},
    "pride": {"Cost": 1, "Tags": ["curse", "innate"], "Facts": [], "Lifecycle": {"TurnEndInHand": [["copySelf", "pride", "DrawPile", "Top", 1]]}},
    "regret": {"Cost": 1, "Tags": ["curse", "unplayable"], "Facts": [], "Lifecycle": {"TurnEndInHand": [["loseHp", ["expr", "combatantZoneCount"], "source"]]}},
    "shame": {"Cost": 1, "Tags": ["curse", "unplayable"], "Facts": [], "Lifecycle": {"TurnEndInHand": [["status", "standard.frail", 1, "source"]]}},
    "strike": {"Cost": 1, "Tags": ["attack", "basic", "strike"],
               "Facts": [("damage", 6, "event")]},
    "defend": {"Cost": 1, "Tags": ["skill", "basic", "defend"],
               "Facts": [("block", 5, "source")]},
    "bash": {"Cost": 2, "Tags": ["attack", "basic"],
             "Facts": [("damage", 8, "event"), ("status", "standard.vulnerable", 2, "event")]},
    # inv:§10 -- a status card created by two enemies (not part of the deck).
    # ---- §225：整手牌逐张消耗（Second Wind / Fiend Fire） -------------------------------------
    # 循环体的事实包在 `("each", zone, (...))` 里：`move` 是"把**当前迭代的那张牌**送进消耗堆"，
    # 后面那条是"每张牌换来的效果"。
    "second_wind": {"Cost": 1, "Tags": ["skill"],
                    "Facts": [("each", "Hand", "PileOrder", None, (("move", "cardInstance.iterated", "ExhaustPile"),
                                                ("block", 5, "source")))],
                    "PlayedCardDestinationZone": "ExhaustPile"},
    "second_wind+": {"Cost": 1, "Tags": ["skill"],
                     "Facts": [("each", "Hand", "PileOrder", None, (("move", "cardInstance.iterated", "ExhaustPile"),
                                                 ("block", 7, "source")))],
                     "PlayedCardDestinationZone": "ExhaustPile"},
    # ---- §226：复制载体（Dual Wield） ----------------------------------------------------------
    # 落区是 **DiscardPile**：`native/wiki_cards/dual_wield.txt` 的 Infobox 里没有 Exhaust，
    # 正文也只说 "add 1 copy (2 copies if upgraded) of that card into your hand"。
    # §227: the fact gained the `Then` (and, for `Copy`, where the copies land).
    "dual_wield": {"Cost": 1, "Tags": ["skill"],
                   "Facts": [("choose", "source", "Hand", ("attack", "power"), 1, 1, "Copy",
                              "Hand", 1)],
                   "PlayedCardDestinationZone": "DiscardPile"},
    "dual_wield+": {"Cost": 1, "Tags": ["skill"],
                    "Facts": [("choose", "source", "Hand", ("attack", "power"), 1, 1, "Copy",
                               "Hand", 2)],
                    "PlayedCardDestinationZone": "DiscardPile"},
    # ---- §227：选完再改它 / 延后复制 ---------------------------------------------------------
    # `armaments+` 的 `upgradeCards` 没有 `CardDefinitionId`（"整片手牌"）—— 这一条事实里
    # 那个字段是 `None`，所以"升级了哪张"与"升级了整片"在清单上不可能被混起来。
    "armaments": {"Cost": 1, "Tags": ["skill"],
                  "Facts": [("block", 5, "source"),
                            ("choose", "source", "Hand", (), 1, 1, "Upgrade")],
                  "PlayedCardDestinationZone": "DiscardPile"},
    "armaments+": {"Cost": 1, "Tags": ["skill"],
                   "Facts": [("block", 5, "source"),
                             ("upgrade", "source", None, "Hand", None)],
                   "PlayedCardDestinationZone": "DiscardPile"},
    "warcry": {"Cost": 0, "Tags": ["skill"],
               "Facts": [("draw", 1, "source"),
                         ("choose", "source", "Hand", (), 1, 1, "ToDrawPileTop")],
               "PlayedCardDestinationZone": "ExhaustPile"},
    "warcry+": {"Cost": 0, "Tags": ["skill"],
                "Facts": [("draw", 2, "source"),
                          ("choose", "source", "Hand", (), 1, 1, "ToDrawPileTop")],
                "PlayedCardDestinationZone": "ExhaustPile"},
    # ---- §233：Entrench（格挡翻倍 = set 而不是 gain） ----------------------------------------
    "entrench": {"Cost": 2, "Tags": ["skill"],
                 "Facts": [("setPool", "standard.block",
                            ("multiply", 2, ("pool", "standard.block", "source")), "source")]},
    "entrench+": {"Cost": 1, "Tags": ["skill"],
                  "Facts": [("setPool", "standard.block",
                             ("multiply", 2, ("pool", "standard.block", "source")), "source")]},
    # ---- §232：两张 X 费牌（载体全在：`repeat` + `x.cost`） -----------------------------------
    "skewer": {"Cost": 0, "Tags": ["attack", "x_cost"],
               "Facts": [("repeat", ("expr", "x.cost"), "damage", 7, "event")]},
    "skewer+": {"Cost": 0, "Tags": ["attack", "x_cost"],
                "Facts": [("repeat", ("expr", "x.cost"), "damage", 10, "event")]},
    "malaise": {"Cost": 0, "Tags": ["skill", "x_cost"],
                "Facts": [("modify", "standard.strength", ("expr", "subtract"), "event"),
                          ("status", "standard.weak", ("expr", "x.cost"), "event")],
                "PlayedCardDestinationZone": "ExhaustPile"},
    "malaise+": {"Cost": 0, "Tags": ["skill", "x_cost"],
                 "Facts": [("modify", "standard.strength", ("expr", "subtract"), "event"),
                           ("status", "standard.weak", ("expr", "add"), "event")],
                 "PlayedCardDestinationZone": "ExhaustPile"},
    # ---- §231：True Grit（格挡 + 随机消耗一张）/ Reaper（打全体 + 按掉血回血） -----------------
    # `True Grit`：数值只有格挡那一半；"随机消耗一张手牌"是 §195.4 的 `selectCards` 事实。
    "true_grit": {"Cost": 1, "Tags": ["skill"],
                  "Facts": [("block", 7, "source"),
                            ("select", "source", "Hand", None, "Random", 1, "ExhaustPile")],
                  "PlayedCardDestinationZone": "ExhaustPile"},
    "true_grit+": {"Cost": 1, "Tags": ["skill"],
                   "Facts": [("block", 9, "source"),
                             ("choose", "source", "Hand", (), 1, 1, "Exhaust")],
                   "PlayedCardDestinationZone": "ExhaustPile"},
    "reaper": {"Cost": 2, "Tags": ["attack"],
               "Facts": [("damageHealLoss", 4, "allEnemies")],
               "PlayedCardDestinationZone": "ExhaustPile"},
    "reaper+": {"Cost": 2, "Tags": ["attack"],
                "Facts": [("damageHealLoss", 5, "allEnemies")],
                "PlayedCardDestinationZone": "ExhaustPile"},
    # ---- §230：临时力量 / 力量翻倍 / 按 tag 数牌加伤 ------------------------------------------
    # `Flex`：加 2(4) 层力量，**同时**挂 2(4) 层 `standard.lose_strength`（回合末扣掉并自摘）。
    "flex": {"Cost": 0, "Tags": ["skill"],
             "Facts": [("status", "standard.strength", 2, "source"),
                       ("status", "standard.lose_strength", 2, "source")]},
    "flex+": {"Cost": 0, "Tags": ["skill"],
              "Facts": [("status", "standard.strength", 4, "source"),
                        ("status", "standard.lose_strength", 4, "source")]},
    # `Limit Break`：增量 = 当前层数 ⇒ 翻倍。基础版**自消耗**，`+` 版不消耗（wiki 的括号是
    # 「基础;升级」：`Double your Strength.(<br>Exhaust.;)`）。
    "limit_break": {"Cost": 1, "Tags": ["skill"],
                    "Facts": [("modify", "standard.strength", ("expr", "combatantStatusStacks"),
                               "source")],
                    "PlayedCardDestinationZone": "ExhaustPile"},
    "limit_break+": {"Cost": 1, "Tags": ["skill"],
                     "Facts": [("modify", "standard.strength", ("expr", "combatantStatusStacks"),
                                "source")],
                     "PlayedCardDestinationZone": "DiscardPile"},
    # `Perfected Strike`：6 + 2(3) × 手牌+抽牌堆+弃牌堆里带 `strike` tag 的牌数。
    "perfected_strike": {"Cost": 2, "Tags": ["attack", "strike"],
                         "Facts": [("damagePerTag", 6, 2, "strike", "event")]},
    "perfected_strike+": {"Cost": 2, "Tags": ["attack", "strike"],
                          "Facts": [("damagePerTag", 6, 3, "strike", "event")]},
    # ---- §229：可无限升级（内容把行写够） ---------------------------------------------------
    # 八行 = 基础 + 7 次升级（12/16/20/…/40）。`+` 能叠几次**由行数决定**，内核不认识这张牌。
    "searing_blow": {"Cost": 2, "Tags": ["attack"],
                "Facts": [("damage", 12, "event")]},
    "searing_blow+": {"Cost": 2, "Tags": ["attack"],
                 "Facts": [("damage", 16, "event")]},
    "searing_blow++": {"Cost": 2, "Tags": ["attack"],
                  "Facts": [("damage", 20, "event")]},
    "searing_blow+++": {"Cost": 2, "Tags": ["attack"],
                   "Facts": [("damage", 24, "event")]},
    "searing_blow++++": {"Cost": 2, "Tags": ["attack"],
                    "Facts": [("damage", 28, "event")]},
    "searing_blow+++++": {"Cost": 2, "Tags": ["attack"],
                     "Facts": [("damage", 32, "event")]},
    "searing_blow++++++": {"Cost": 2, "Tags": ["attack"],
                      "Facts": [("damage", 36, "event")]},
    "searing_blow+++++++": {"Cost": 2, "Tags": ["attack"],
                       "Facts": [("damage", 40, "event")]},
    # ---- §229：随机双击（§228 载体的第二个用户）/ 每副本计数器 ------------------------------
    "rip_and_tear": {"Cost": 1, "Tags": ["attack"],
                     "Facts": [("damageRandom", 7, "allEnemies", 2)]},
    "rip_and_tear+": {"Cost": 1, "Tags": ["attack"],
                      "Facts": [("damageRandom", 9, "allEnemies", 2)]},
    # 伤害是 `8 + card.counter`，然后给这份副本加 5(8) —— 两件事都在事实里。
    "rampage": {"Cost": 1, "Tags": ["attack"],
                "Facts": [("damage", ("add", 8, ("cardCounter", "standard.rampage_bonus")), "event"),
                          ("cardCounter", "cardInstance.resolving", "standard.rampage_bonus", 5, "Add")]},
    "rampage+": {"Cost": 1, "Tags": ["attack"],
                 "Facts": [("damage", ("add", 8, ("cardCounter", "standard.rampage_bonus")), "event"),
                           ("cardCounter", "cardInstance.resolving", "standard.rampage_bonus", 8, "Add")]},
    # ---- §228：随机目标 / 按格挡打伤害 -------------------------------------------------------
    # 升级改的是**次数**（wiki: "(3;4) times"），不是伤害 —— 所以两行只差最后一个字段。
    "sword_boomerang": {"Cost": 1, "Tags": ["attack"],
                        "Facts": [("damageRandom", 3, "allEnemies", 3)]},
    "sword_boomerang+": {"Cost": 1, "Tags": ["attack"],
                         "Facts": [("damageRandom", 3, "allEnemies", 4)]},
    "body_slam": {"Cost": 1, "Tags": ["attack"],
                  "Facts": [("damage", ("pool", "standard.block", "source"), "event")]},
    "body_slam+": {"Cost": 0, "Tags": ["attack"],
                   "Facts": [("damage", ("pool", "standard.block", "source"), "event")]},
    "nightmare": {"Cost": 3, "Tags": ["skill"],
                  "Facts": [("choose", "source", "Hand", (), 1, 1, "Copy", "SetAsidePile", 3),
                            ("status", "standard.nightmare_pending", 1, "source")],
                  "PlayedCardDestinationZone": "ExhaustPile"},
    "nightmare+": {"Cost": 2, "Tags": ["skill"],
                   "Facts": [("choose", "source", "Hand", (), 1, 1, "Copy", "SetAsidePile", 3),
                             ("status", "standard.nightmare_pending", 1, "source")],
                   "PlayedCardDestinationZone": "ExhaustPile"},
    "fiend_fire": {"Cost": 2, "Tags": ["attack"],
                   "Facts": [("each", "Hand", "PileOrder", None, (("move", "cardInstance.iterated", "ExhaustPile"),
                                               ("damage", 7, "event")))],
                   "PlayedCardDestinationZone": "ExhaustPile"},
    "fiend_fire+": {"Cost": 2, "Tags": ["attack"],
                    "Facts": [("each", "Hand", "PileOrder", None, (("move", "cardInstance.iterated", "ExhaustPile"),
                                                ("damage", 10, "event")))],
                    "PlayedCardDestinationZone": "ExhaustPile"},
    # ---- §221: ten more Ironclad cards (wiki numbers; `native/wiki_cards/<id>.txt`) ----------------
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
                      "Facts": [("draw", 3, "source"), ("status", "standard.no_draw", 1, "source")]},
    "battle_trance+": {"Cost": 0, "Tags": ["skill"],
                       "Facts": [("draw", 4, "source"), ("status", "standard.no_draw", 1, "source")]},
    # §221：两张事件诅咒。Doubt 的"回合末 +1 Weak"是 `LifecyclePrograms[TurnEndInHand]`
    # （§220 的载体；手牌里过回合才付账）。Writhe 只有关键字，没有节目。
    "doubt": {"Cost": 1, "Tags": ["curse", "unplayable"], "Facts": [],
              "Lifecycle": {"TurnEndInHand": [("status", "standard.weak", 1, "source")]}},
    "writhe": {"Cost": 1, "Tags": ["curse", "unplayable", "innate"], "Facts": []},
    # §219：wiki 是"1 费、可出、Exhaust"。落区现在写得出来了（`PlayedCardDestinationZone`），
    # 所以不再需要 `unplayable` 这个简化。
    "slimed": {"Cost": 1, "Tags": ["status", "junk"], "Facts": [],
               "PlayedCardDestinationZone": "ExhaustPile"},
    # §183: the colorless pool. The Colorless Potion offers three of them; **no deck can hold them**,
    # which is why they have no `+` row (see NOT_UPGRADABLE_TAGS). Wiki values, base.
    # §189 `A10`：开局诅咒（wiki: Unplayable. Ethereal. Cannot be removed）。
    "ascenders_bane": {"Cost": 0, "Tags": ["curse", "unplayable", "ethereal"], "Facts": []},
    # §191：Sentry 的 Bolt 塞的就是这张（wiki: Unplayable. Ethereal.）。第三张 junk 卡，
    # 与 `slimed` / `wound` 同形 —— 唯一区别是它离手即烧掉。
    "dazed": {"Cost": 1, "Tags": ["status", "unplayable", "ethereal", "junk"], "Facts": []},
    "bandage_up": {"Cost": 0, "Tags": ["skill", "colorless"],
                   "Facts": [("heal", 4, "sourceDowned")]},
    "blind": {"Cost": 0, "Tags": ["skill", "colorless"],
              "Facts": [("status", "standard.weak", 2, "allEnemies")]},
    # §219：wiki 是"Enemy loses 9 Strength **this turn**"。原来的程序给敌人施
    # `standard.strength` **-9 层**，而内核禁止负层数（`exec.rs:4063`）⇒ **打出即 `Effect(Modifier)`**。
    # 现在换成"立刻 modify -9（钳在 0，参考行为）+ 回合末由 `regain_strength` 还回 9"。
    "dark_shackles": {"Cost": 0, "Tags": ["skill", "colorless"],
                      "Facts": [("modify", "standard.strength", -9, "event"),
                                ("status", "standard.regain_strength", 9, "event")]},
    # inv:§2.1 "升级后" -- the upgraded rows. They are **separate CARD rows**, not a flag on the base
    # card (`sts-act1-plan.md` §6.5-2), and their numbers are the inventory's second column:
    # strike+ 9 damage, defend+ 8 Block, bash+ 10 damage + 3 Vulnerable.
    "strike+": {"Cost": 1, "Tags": ["attack", "basic", "strike"],
                "Facts": [("damage", 9, "event")]},
    "defend+": {"Cost": 1, "Tags": ["skill", "basic", "defend"],
                "Facts": [("block", 8, "source")]},
    "bash+": {"Cost": 2, "Tags": ["attack", "basic"],
              "Facts": [("damage", 10, "event"), ("status", "standard.vulnerable", 3, "event")]},
    # The first **non-Basic** cards: the deck has to be able to grow, and an act-1 boss cannot be
    # beaten with ten starter cards (see docs/port-plan.md §72.5).
    "twin_strike": {"Cost": 1, "Tags": ["attack", "strike"],
                    "Facts": [("damage", 5, "event"), ("damage", 5, "event")]},
    "iron_wave": {"Cost": 1, "Tags": ["attack", "block"],
                  "Facts": [("block", 5, "source"), ("damage", 5, "event")]},
    "clothesline": {"Cost": 2, "Tags": ["attack"],
                    "Facts": [("damage", 12, "event"), ("status", "standard.weak", 2, "event")]},
    "anger": {"Cost": 0, "Tags": ["attack"],
              "Facts": [("damage", 6, "event"), ("card", "anger", 1, "DiscardPile", "source")]},
    "uppercut": {"Cost": 2, "Tags": ["attack"],
                 "Facts": [("damage", 13, "event"), ("status", "standard.weak", 1, "event"),
                           ("status", "standard.vulnerable", 1, "event")]},
    # §143: the first **Curse**. It is not in the deck and never a reward; an event hands it to
    # you (`curse:injury`), and the only thing it does is sit in the way -- `unplayable`.
    "injury": {"Cost": 1, "Tags": ["curse", "unplayable", "junk"], "Facts": []},
    # §173: the junk the act-2 elites hand out (Taskmaster's whip, and the Daggers that come later).
    # Same shape as `slimed`: a status card, unplayable, no program.
    "wound": {"Cost": 1, "Tags": ["status", "unplayable", "junk"], "Facts": []},
    # §175: Burn is the first card in this package with a `LifecyclePrograms[TurnEndInHand]` program
    # ("at the end of your turn, take 2 damage"). `Facts` is the **card's own** program (empty); the
    # lifecycle program is checked by the card-lifecycle test, not by this table.
    "burn": {"Cost": 1, "Tags": ["status", "unplayable", "junk"], "Facts": [],
             "Lifecycle": {"TurnEndInHand": [("damage", 2, "source")]}},
    # §144: the keyword cards. `sentinel` is a **real** Ironclad card (5 Block, Ethereal); the other
    # two are **fixtures** on purpose -- the Ironclad has no Retain and no Innate card in StS, so
    # the keyword has to be exercised by a card this package owns. Their numbers are this package's,
    # not the wiki's, and that is why they are named here rather than silently mixed in.
    # §220：wiki 的 "If this card is Exhausted, gain 2 Energy." 现在有载体了
    # （`LifecyclePrograms[Exhausted]`；`ethereal` 标签仍是本内容的简化 —— wiki 没有 Ethereal）。
    "sentinel": {"Cost": 1, "Tags": ["skill", "ethereal"],
                 "Facts": [("block", 5, "source")],
                 "TurnEndHandDestinationZone": "ExhaustPile",
                 "Lifecycle": {"Exhausted": [("gain", "standard.energy", 2, "source")]}},
    "patient_guard": {"Cost": 1, "Tags": ["skill", "retain"],
                      "Facts": [("block", 5, "source")],
                      "RetainInHandOnTurnEnd": True},
    "swift_strike": {"Cost": 1, "Tags": ["attack", "strike", "innate", "colorless"],
                     "Facts": [("damage", 6, "event")]},
    # §146：第一张 **X 费**牌（Whirlwind，真卡：X 费，"Deal 5 damage to ALL enemies X times"）。
    # 它的费用是"当前全部能量"，`Cost` 在这里记 0 —— 印刷价格**不参与**结算，内容门下面会查
    # 这一格必须是 0 或缺失。Facts 里的 `("repeat", ("expr", "x.cost"), ...)` 说明"这一条伤害
    # **每 X 一次**"，而不是被展开成 32 条。
    # §149: cards that hand out the damage-pipeline statuses (they exist so the statuses are
    # reachable in a run; `buffer` is a Defect power in StS, modelled here as a skill).
    # §223：wiki —— 基础带 Ethereal、升级**去掉** Ethereal，两层都只给 1 层无形 + Exhaust。
    "apparition": {"Cost": 1, "Tags": ["skill", "intangible", "ethereal", "colorless"],
                   "Facts": [("status", "standard.intangible", 1, "source")],
                   "TurnEndHandDestinationZone": "ExhaustPile",
                   "PlayedCardDestinationZone": "ExhaustPile"},
    # §223：跟 wiki 走 —— **Power** / Rare / 2 费（旧基线是 Skill / Uncommon / 1 费）。
    "buffer": {"Cost": 2, "Tags": ["power", "buffer"],
               "Facts": [("status", "standard.buffer", 1, "source")]},
    # §147: the upgraded row -- same X mechanics, 8 damage per hit instead of 5.
    # §154: the ten `+` rows that were missing. The run upgrades by appending `+` to the card id, so
    # a card without one becomes an id the image does not contain -- and the next fight refuses to
    # build (`UnknownCard(CardDefinitionId("iron_wave+"))`, reported from the browser).
    "anger+": {"Cost": 0, "Tags": ["attack"],
               "Facts": [("damage", 8, "event"), ("card", "anger+", 1, "DiscardPile", "source")]},
    "twin_strike+": {"Cost": 1, "Tags": ["attack", "strike"],
                     "Facts": [("damage", 7, "event"), ("damage", 7, "event")]},
    "iron_wave+": {"Cost": 1, "Tags": ["attack", "block"],
                   "Facts": [("block", 7, "source"), ("damage", 7, "event")]},
    "clothesline+": {"Cost": 2, "Tags": ["attack"],
                     "Facts": [("damage", 14, "event"), ("status", "standard.weak", 3, "event")]},
    "uppercut+": {"Cost": 2, "Tags": ["attack"],
                  "Facts": [("damage", 13, "event"), ("status", "standard.weak", 2, "event"),
                            ("status", "standard.vulnerable", 2, "event")]},
    # §220：节目挂在**定义**上，所以升级行有自己的一份（3 点能量）。
    "sentinel+": {"Cost": 1, "Tags": ["skill", "ethereal"],
                  "Facts": [("block", 8, "source")],
                  "Lifecycle": {"Exhausted": [("gain", "standard.energy", 3, "source")]}},
    "patient_guard+": {"Cost": 1, "Tags": ["skill", "retain"],
                       "Facts": [("block", 8, "source")]},
    "swift_strike+": {"Cost": 1, "Tags": ["attack", "strike", "innate", "colorless"],
                      "Facts": [("damage", 9, "event")]},
    "apparition+": {"Cost": 1, "Tags": ["skill", "intangible", "colorless"],
                    "Facts": [("status", "standard.intangible", 1, "source")],
                    "PlayedCardDestinationZone": "ExhaustPile"},
    "buffer+": {"Cost": 2, "Tags": ["power", "buffer"],
                "Facts": [("status", "standard.buffer", 2, "source")]},
    "whirlwind+": {"Cost": 0, "Tags": ["attack", "x_cost"],
                   "Facts": [("repeat", ("expr", "x.cost"), "damage", 8, "allEnemies")]},
    "whirlwind": {"Cost": 0, "Tags": ["attack", "x_cost"],
                  "Facts": [("repeat", ("expr", "x.cost"), "damage", 5, "allEnemies")]},
    # §161.7: the three **Power** cards (inv:§2 rows 178/183/184). They exist so that
    # `choice_offered:power` has three cards to offer -- and every number here is the inventory's
    # second column (5->7, 2->3, 3->4), not a guess.
    #
    # ⚠️ These are the content's first cards whose whole effect is a **status that keeps working
    # after the card is played**. Two statuses had to be fixed for them to be honest:
    # `standard.metallicize` had no trigger at all, and `standard.combust`'s trigger skipped the
    # "lose 1 HP" its own description promises.
    "inflame": {"Cost": 1, "Tags": ["power"],
                "Facts": [("status", "standard.strength", 2, "source")]},
    "inflame+": {"Cost": 1, "Tags": ["power"],
                 "Facts": [("status", "standard.strength", 3, "source")]},
    "metallicize": {"Cost": 1, "Tags": ["power"],
                    "Facts": [("status", "standard.metallicize", 3, "source")]},
    "metallicize+": {"Cost": 1, "Tags": ["power"],
                     "Facts": [("status", "standard.metallicize", 4, "source")]},
    "combust": {"Cost": 1, "Tags": ["power"],
                "Facts": [("status", "standard.combust", 5, "source")]},
    # §197: the two block-retention cards. Facts are the status they apply; the retention itself is
    # the status' tag (checked by the kernel test, not by this table).
    # §199: wiki `Berserk` -- 0 cost, Rare Power: "Gain (2;1) Vulnerable. At the start of your turn,
    # gain 1 Energy." (`native/wiki_asc/berserk.txt`).
    "berserk": {"Cost": 0, "Tags": ["power"],
                "Facts": [("status", "standard.vulnerable", 2, "source"),
                          ("status", "standard.berserk", 1, "source")]},
    "berserk+": {"Cost": 0, "Tags": ["power"],
                 "Facts": [("status", "standard.vulnerable", 1, "source"),
                           ("status", "standard.berserk", 1, "source")]},
    "barricade": {"Cost": 3, "Tags": ["power"],
                  "Facts": [("status", "standard.barricade", 1, "source")]},
    "barricade+": {"Cost": 2, "Tags": ["power"],
                   "Facts": [("status", "standard.barricade", 1, "source")]},
    # §218：wiki `Blur` 是"Gain 5 (8) Block. Block is not removed at the start of your next turn."
    # —— 内容一直只给了状态、漏了格挡（卡牌 wiki 对照抓到的第一处真错）。
    "blur": {"Cost": 1, "Tags": ["skill"],
             "Facts": [("block", 5, "source"), ("status", "standard.blur", 1, "source")]},
    "blur+": {"Cost": 0, "Tags": ["skill"],
              "Facts": [("block", 8, "source"), ("status", "standard.blur", 1, "source")]},
    "combust+": {"Cost": 1, "Tags": ["power"],
                 "Facts": [("status", "standard.combust", 7, "source")]},

    # ================= §194: the two junk cards the new bosses add =================
    # Hexaghost's Inferno shuffles **upgraded** Burns in (wiki: "Adds 3 Burns+"): 4 damage at turn
    # end instead of 2.
    # §220：`burn+` 的回合末伤害**早就**是 4（wiki 的升级值），但一直没有被 pin ——
    # 这条新闸门（`check_card_lifecycle`）第一次跑就把这个旧账翻出来了。
    "burn+": {"Cost": 1, "Tags": ["status", "unplayable", "junk"],
              "Facts": [],
              "Lifecycle": {"TurnEndInHand": [("damage", 4, "source")]}},
    # Awakened One's Sludge adds a Void. §220 gave the missing half a carrier:
    # `LifecyclePrograms[Drawn]` fires from `state.move_card` (draw pile -> hand), so
    # "Whenever this card is drawn, lose 1 Energy" is real now. (The old comment here said
    # "nothing here can say 'the card that just moved is this one'" -- that was true until §220.)
    "void": {"Cost": 1, "Tags": ["status", "unplayable", "ethereal", "junk"],
             "Facts": [],
             "Lifecycle": {"Drawn": [("lose", "standard.energy", 1, "source")]}},
    # ---- §249：Omega / Panache / Sadistic Nature / The Bomb（4 张 / 8 行）-------------------
    "omega": {"Cost": 3, "Tags": ["power", "colorless"],
                   "Facts": [('status', 'standard.omega', 50, 'source')]},
    "omega+": {"Cost": 3, "Tags": ["power", "colorless"],
                    "Facts": [('status', 'standard.omega', 60, 'source')]},
    "panache": {"Cost": 0, "Tags": ["power", "colorless"],
                     "Facts": [('status', 'standard.panache', 10, 'source')]},
    "panache+": {"Cost": 0, "Tags": ["power", "colorless"],
                      "Facts": [('status', 'standard.panache', 14, 'source')]},
    "sadistic_nature": {"Cost": 0, "Tags": ["power", "colorless"],
                             "Facts": [('status', 'standard.sadistic_nature', 5, 'source')]},
    "sadistic_nature+": {"Cost": 0, "Tags": ["power", "colorless"],
                              "Facts": [('status', 'standard.sadistic_nature', 7, 'source')]},
    "the_bomb": {"Cost": 2, "Tags": ["skill", "colorless"],
                      "Facts": [('status', 'standard.the_bomb_damage', 40, 'source'), ('status', 'standard.the_bomb', 3, 'source')]},
    "the_bomb+": {"Cost": 2, "Tags": ["skill", "colorless"],
                       "Facts": [('status', 'standard.the_bomb_damage', 50, 'source'), ('status', 'standard.the_bomb', 3, 'source')]},
    # ---- §248：Enlightenment / Madness（2 张 / 4 行）----------------------------------------
    # ---- §248：Enlightenment / Madness（2 张 / 4 行）----------------------------------------
    "enlightenment": {"Cost": 0, "Tags": ["skill", "colorless"],
                           "Facts": [('status', 'standard.cap_cost_at', 1, 'source')]},
    "enlightenment+": {"Cost": 0, "Tags": ["skill", "colorless"],
                            "Facts": [('status', 'standard.cap_cost_at', 1, 'source')]},
    "madness": {"Cost": 1, "Tags": ["skill", "colorless"],
                     "Facts": [('each', 'Hand', 'Random', 1, (('cardCounter', 'cardInstance.iterated', 'standard.card_cost_override', 0, 'Set'),))]},
    "madness+": {"Cost": 0, "Tags": ["skill", "colorless"],
                      "Facts": [('each', 'Hand', 'Random', 1, (('cardCounter', 'cardInstance.iterated', 'standard.card_cost_override', 0, 'Set'),))]},
    # ---- §247：Mind Blast / Enlightenment（2 张 / 4 行）-------------------------------------
    "mind_blast": {"Cost": 2, "Tags": ["attack", "innate", "colorless"],
                        "Facts": [('damage', ('expr', 'combatantZoneCount'), 'event')]},
    "mind_blast+": {"Cost": 1, "Tags": ["attack", "innate", "colorless"],
                         "Facts": [('damage', ('expr', 'combatantZoneCount'), 'event')]},
    # ---- §246：Thinking Ahead（1 张 / 2 行）-------------------------------------------------
    "thinking_ahead": {"Cost": 0, "Tags": ["skill", "colorless"],
                            "Facts": [('draw', 2, 'source'), ('choose', 'source', 'Hand', (), 1, 1, 'ToDrawPileTop')]},
    "thinking_ahead+": {"Cost": 0, "Tags": ["skill", "colorless"],
                             "Facts": [('draw', 2, 'source'), ('choose', 'source', 'Hand', (), 1, 1, 'ToDrawPileTop')]},
    # ---- §245：无色「既有载体」第一批（3 张 / 6 行）------------------------------------------
    "apotheosis": {"Cost": 2, "Tags": ["skill", "colorless"],
                        "Facts": [('upgrade', 'source', None, None, None)]},
    "apotheosis+": {"Cost": 1, "Tags": ["skill", "colorless"],
                         "Facts": [('upgrade', 'source', None, None, None)]},
    "panic_button": {"Cost": 0, "Tags": ["skill", "colorless"],
                          "Facts": [('block', 30, 'source'), ('status', 'standard.no_block_from_cards', 1, 'source')]},
    "panic_button+": {"Cost": 0, "Tags": ["skill", "colorless"],
                           "Facts": [('block', 40, 'source'), ('status', 'standard.no_block_from_cards', 1, 'source')]},
    # ---- §244：无色 B 档（10 张 / 20 行）---------------------------------------------------
    "mayhem": {"Cost": 2, "Tags": ["power", "colorless"],
                    "Facts": [('status', 'standard.mayhem', 1, 'source')]},
    "mayhem+": {"Cost": 1, "Tags": ["power", "colorless"],
                     "Facts": [('status', 'standard.mayhem', 1, 'source')]},
    "magnetism": {"Cost": 2, "Tags": ["power", "colorless"],
                       "Facts": [('status', 'standard.magnetism', 1, 'source')]},
    "magnetism+": {"Cost": 1, "Tags": ["power", "colorless"],
                        "Facts": [('status', 'standard.magnetism', 1, 'source')]},
    "chrysalis": {"Cost": 2, "Tags": ["skill", "colorless"],
                       "Facts": [('createRandom', 'skill', 'DrawPile', 3, True)]},
    "chrysalis+": {"Cost": 2, "Tags": ["skill", "colorless"],
                        "Facts": [('createRandom', 'skill', 'DrawPile', 5, True)]},
    "metamorphosis": {"Cost": 2, "Tags": ["skill", "colorless"],
                           "Facts": [('createRandom', 'attack', 'DrawPile', 3, True)]},
    "metamorphosis+": {"Cost": 2, "Tags": ["skill", "colorless"],
                            "Facts": [('createRandom', 'attack', 'DrawPile', 5, True)]},
    "jack_of_all_trades": {"Cost": 0, "Tags": ["skill", "colorless"],
                                "Facts": [('createRandom', 'colorless', 'Hand', 1, True)]},
    "jack_of_all_trades+": {"Cost": 0, "Tags": ["skill", "colorless"],
                                 "Facts": [('createRandom', 'colorless', 'Hand', 2, True)]},
    "transmutation": {"Cost": 0, "Tags": ["skill", "x_cost", "colorless"],
                           "Facts": [('createRandom', 'colorless', 'Hand', ('expr', 'x.cost'), True)]},
    "transmutation+": {"Cost": 0, "Tags": ["skill", "x_cost", "colorless"],
                            "Facts": [('createRandom', 'colorless', 'Hand', ('expr', 'x.cost'), True)]},
    "secret_technique": {"Cost": 0, "Tags": ["skill", "colorless"],
                              "Facts": [('choose', 'source', 'DrawPile', ('skill',), 1, 1, 'ToHand')]},
    "secret_technique+": {"Cost": 0, "Tags": ["skill", "colorless"],
                               "Facts": [('choose', 'source', 'DrawPile', ('skill',), 1, 1, 'ToHand')]},
    "secret_weapon": {"Cost": 0, "Tags": ["skill", "colorless"],
                           "Facts": [('choose', 'source', 'DrawPile', ('attack',), 1, 1, 'ToHand')]},
    "secret_weapon+": {"Cost": 0, "Tags": ["skill", "colorless"],
                            "Facts": [('choose', 'source', 'DrawPile', ('attack',), 1, 1, 'ToHand')]},
    "violence": {"Cost": 0, "Tags": ["skill", "colorless"],
                      "Facts": [('select', 'source', 'DrawPile', None, 'Random', 3, 'Hand')]},
    "violence+": {"Cost": 0, "Tags": ["skill", "colorless"],
                       "Facts": [('select', 'source', 'DrawPile', None, 'Random', 4, 'Hand')]},
    "purity": {"Cost": 0, "Tags": ["skill", "colorless"],
                    "Facts": [('choose', 'source', 'Hand', (), 1, 3, 'Exhaust')]},
    "purity+": {"Cost": 0, "Tags": ["skill", "colorless"],
                     "Facts": [('choose', 'source', 'Hand', (), 1, 5, 'Exhaust')]},
    # ---- §243：无色 A 档（11 张 / 22 行）----------------------------------------------------
    "trip": {"Cost": 0, "Tags": ["skill", "colorless"],
                  "Facts": [('status', 'standard.vulnerable', 2, 'event')]},
    "trip+": {"Cost": 0, "Tags": ["skill", "colorless"],
                   "Facts": [('status', 'standard.vulnerable', 2, 'allEnemies')]},
    "panacea": {"Cost": 0, "Tags": ["skill", "colorless"],
                     "Facts": [('status', 'standard.artifact', 1, 'source')]},
    "panacea+": {"Cost": 0, "Tags": ["skill", "colorless"],
                      "Facts": [('status', 'standard.artifact', 2, 'source')]},
    "finesse": {"Cost": 0, "Tags": ["skill", "colorless"],
                     "Facts": [('block', 2, 'source'), ('draw', 1, 'source')]},
    "finesse+": {"Cost": 0, "Tags": ["skill", "colorless"],
                      "Facts": [('block', 4, 'source'), ('draw', 1, 'source')]},
    "flash_of_steel": {"Cost": 0, "Tags": ["attack", "colorless"],
                            "Facts": [('damage', 3, 'event'), ('draw', 1, 'source')]},
    "flash_of_steel+": {"Cost": 0, "Tags": ["attack", "colorless"],
                             "Facts": [('damage', 6, 'event'), ('draw', 1, 'source')]},
    "good_instincts": {"Cost": 0, "Tags": ["skill", "colorless"],
                            "Facts": [('block', 6, 'source')]},
    "good_instincts+": {"Cost": 0, "Tags": ["skill", "colorless"],
                             "Facts": [('block', 9, 'source')]},
    "master_of_strategy": {"Cost": 0, "Tags": ["skill", "colorless"],
                                "Facts": [('draw', 3, 'source')]},
    "master_of_strategy+": {"Cost": 0, "Tags": ["skill", "colorless"],
                                 "Facts": [('draw', 4, 'source')]},
    "dramatic_entrance": {"Cost": 0, "Tags": ["attack", "innate", "colorless"],
                               "Facts": [('damage', 8, 'allEnemies')]},
    "dramatic_entrance+": {"Cost": 0, "Tags": ["attack", "innate", "colorless"],
                                "Facts": [('damage', 12, 'allEnemies')]},
    "impatience": {"Cost": 0, "Tags": ["skill", "colorless"],
                        "Facts": [('when', None, 'draw', 2, 'source')]},
    "impatience+": {"Cost": 0, "Tags": ["skill", "colorless"],
                         "Facts": [('when', None, 'draw', 3, 'source')]},
    "deep_breath": {"Cost": 0, "Tags": ["skill", "colorless"],
                         "Facts": [('shuffleDiscard', 'source'), ('draw', 1, 'source')]},
    "deep_breath+": {"Cost": 0, "Tags": ["skill", "colorless"],
                          "Facts": [('shuffleDiscard', 'source'), ('draw', 2, 'source')]},
    "insight": {"Cost": 0, "Tags": ["skill", "retain", "colorless"],
                     "Facts": [('draw', 2, 'source')]},
    "insight+": {"Cost": 0, "Tags": ["skill", "retain", "colorless"],
                      "Facts": [('draw', 3, 'source')]},
    "miracle": {"Cost": 0, "Tags": ["skill", "retain", "colorless"],
                     "Facts": [('gain', 'standard.energy', 1, 'source')]},
    "miracle+": {"Cost": 0, "Tags": ["skill", "retain", "colorless"],
                      "Facts": [('gain', 'standard.energy', 2, 'source')]},
    # ---- §242：最后三张红卡（3 张） -------------------------------------------------------
    "spot_weakness": {"Cost": 1, "Tags": ["skill"],
                           "Facts": [('when', None, 'status', 'standard.strength', 3, 'source')]},
    "spot_weakness+": {"Cost": 1, "Tags": ["skill"],
                            "Facts": [('when', None, 'status', 'standard.strength', 4, 'source')]},
    "blood_for_blood": {"Cost": 4, "Tags": ["attack", "hp_loss_cost"],
                             "Facts": [('damage', 18, 'event')]},
    "blood_for_blood+": {"Cost": 3, "Tags": ["attack", "hp_loss_cost"],
                              "Facts": [('damage', 22, 'event')]},
    "corruption": {"Cost": 3, "Tags": ["power"],
                        "Facts": [('status', 'standard.corruption', 1, 'source')]},
    "corruption+": {"Cost": 2, "Tags": ["power"],
                         "Facts": [('status', 'standard.corruption', 1, 'source')]},
    # ---- §241：强制出牌（1 张） -----------------------------------------------------------
    "havoc": {"Cost": 1, "Tags": ["skill"],
              "Facts": [('playTopOfDrawPile', 'ExhaustPile')]},
    "havoc+": {"Cost": 0, "Tags": ["skill"],
               "Facts": [('playTopOfDrawPile', 'ExhaustPile')]},
    # ---- §240：随机造牌（1 张） -----------------------------------------------------------
    "infernal_blade": {"Cost": 1, "Tags": ["skill"],
                            "Facts": [('createRandom', 'attack', 'Hand', 1, True)]},
    "infernal_blade+": {"Cost": 0, "Tags": ["skill"],
                             "Facts": [('createRandom', 'attack', 'Hand', 1, True)]},
    # ---- §239：clash 之后的两张（burning_pact） -------------------------------------------
    "burning_pact": {"Cost": 1, "Tags": ["skill"],
                          "Facts": [('choose', 'source', 'Hand', (), 1, 1, 'Exhaust'), ('draw', 2, 'source')]},
    "burning_pact+": {"Cost": 1, "Tags": ["skill"],
                           "Facts": [('choose', 'source', 'Hand', (), 1, 1, 'Exhaust'), ('draw', 3, 'source')]},
    # ---- §239：PlayCondition 的第一张（1 张） ---------------------------------------------
    "clash": {"Cost": 0, "Tags": ["attack"], "PlayCondition": "handIsAllAttacks",
                   "Facts": [('damage', 14, 'event')]},
    "clash+": {"Cost": 0, "Tags": ["attack"], "PlayCondition": "handIsAllAttacks",
                    "Facts": [('damage', 18, 'event')]},
    # ---- §238：余额基建的第一批（4 张） ---------------------------------------------------
    "double_tap": {"Cost": 1, "Tags": ["skill"],
                        "Facts": [('status', 'standard.double_tap', 1, 'source')]},
    "double_tap+": {"Cost": 1, "Tags": ["skill"],
                         "Facts": [('status', 'standard.double_tap', 2, 'source')]},
    "exhume": {"Cost": 1, "Tags": ["skill"],
                    "Facts": [('choose', 'source', 'ExhaustPile', (), 1, 1, 'ToHand')]},
    "exhume+": {"Cost": 0, "Tags": ["skill"],
                     "Facts": [('choose', 'source', 'ExhaustPile', (), 1, 1, 'ToHand')]},
    "feed": {"Cost": 1, "Tags": ["attack"],
                  "Facts": [('damage', 10, 'event'), ('ifFatalGainMaxHealth', 3)]},
    "feed+": {"Cost": 1, "Tags": ["attack"],
                   "Facts": [('damage', 12, 'event'), ('ifFatalGainMaxHealth', 4)]},
    "heavy_blade": {"Cost": 2, "Tags": ["attack"],
                         "Facts": [('damage', ('expr', 'add'), 'event')]},
    "heavy_blade+": {"Cost": 2, "Tags": ["attack"],
                          "Facts": [('damage', ('expr', 'add'), 'event')]},
    # ---- §237：触发器钩子的第一批（5 张 Power） -------------------------------------------
    "dark_embrace": {"Cost": 2, "Tags": ["power"],
                          "Facts": [('status', 'standard.dark_embrace', 1, 'source')]},
    "dark_embrace+": {"Cost": 1, "Tags": ["power"],
                           "Facts": [('status', 'standard.dark_embrace', 1, 'source')]},
    "evolve": {"Cost": 1, "Tags": ["power"],
                    "Facts": [('status', 'standard.evolve', 1, 'source')]},
    "evolve+": {"Cost": 1, "Tags": ["power"],
                     "Facts": [('status', 'standard.evolve', 2, 'source')]},
    "feel_no_pain": {"Cost": 1, "Tags": ["power"],
                          "Facts": [('status', 'standard.feel_no_pain', 3, 'source')]},
    "feel_no_pain+": {"Cost": 1, "Tags": ["power"],
                           "Facts": [('status', 'standard.feel_no_pain', 4, 'source')]},
    "fire_breathing": {"Cost": 1, "Tags": ["power"],
                            "Facts": [('status', 'standard.fire_breathing', 6, 'source')]},
    "fire_breathing+": {"Cost": 1, "Tags": ["power"],
                             "Facts": [('status', 'standard.fire_breathing', 10, 'source')]},
    "juggernaut": {"Cost": 2, "Tags": ["power", "block"],
                        "Facts": [('status', 'standard.juggernaut', 5, 'source')]},
    "juggernaut+": {"Cost": 2, "Tags": ["power", "block"],
                         "Facts": [('status', 'standard.juggernaut', 7, 'source')]},
    # ---- §236：失去生命（Lose HP 不是伤害） -------------------------------------------
    "bloodletting": {"Cost": 0, "Tags": ["skill"],
                          "Facts": [('loseHp', 3, 'source'), ('gain', 'standard.energy', 2, 'source')]},
    "bloodletting+": {"Cost": 0, "Tags": ["skill"],
                           "Facts": [('loseHp', 3, 'source'), ('gain', 'standard.energy', 3, 'source')]},
    "brutality": {"Cost": 0, "Tags": ["power"],
                       "Facts": [('status', 'standard.brutality', 1, 'source')]},
    "brutality+": {"Cost": 0, "Tags": ["power", "innate"],
                        "Facts": [('status', 'standard.brutality', 1, 'source')]},
    "hemokinesis": {"Cost": 1, "Tags": ["attack"],
                         "Facts": [('loseHp', 2, 'source'), ('damage', 15, 'event')]},
    "hemokinesis+": {"Cost": 1, "Tags": ["attack"],
                          "Facts": [('loseHp', 2, 'source'), ('damage', 20, 'event')]},
    "offering": {"Cost": 0, "Tags": ["skill"],
                      "Facts": [('loseHp', 6, 'source'), ('gain', 'standard.energy', 2, 'source'), ('draw', 3, 'source')]},
    "offering+": {"Cost": 0, "Tags": ["skill"],
                       "Facts": [('loseHp', 6, 'source'), ('gain', 'standard.energy', 2, 'source'), ('draw', 5, 'source')]},
    "rupture": {"Cost": 1, "Tags": ["power"],
                     "Facts": [('status', 'standard.rupture', 1, 'source')]},
    "rupture+": {"Cost": 1, "Tags": ["power"],
                      "Facts": [('status', 'standard.rupture', 2, 'source')]},
    # ---- §235：35 张红卡的第一批（14 张：纯内容，内核零改动） -----------------------------
    "carnage": {"Cost": 2, "Tags": ["attack", "ethereal"],
                     "Facts": [('damage', 20, 'event')]},
    "carnage+": {"Cost": 2, "Tags": ["attack", "ethereal"],
                      "Facts": [('damage', 28, 'event')]},
    "demon_form": {"Cost": 3, "Tags": ["power"],
                        "Facts": [('status', 'standard.demon_form', 2, 'source')]},
    "demon_form+": {"Cost": 3, "Tags": ["power"],
                         "Facts": [('status', 'standard.demon_form', 3, 'source')]},
    "disarm": {"Cost": 1, "Tags": ["skill"],
                    "Facts": [('modify', 'standard.strength', -2, 'event')]},
    "disarm+": {"Cost": 1, "Tags": ["skill"],
                     "Facts": [('modify', 'standard.strength', -3, 'event')]},
    "dropkick": {"Cost": 1, "Tags": ["attack"],
                      "Facts": [('damage', 5, 'event'), ('when', None, 'gain', 'standard.energy', 1, 'source'), ('when', None, 'draw', 1, 'source')]},
    "dropkick+": {"Cost": 1, "Tags": ["attack"],
                       "Facts": [('damage', 8, 'event'), ('when', None, 'gain', 'standard.energy', 1, 'source'), ('when', None, 'draw', 1, 'source')]},
    "flame_barrier": {"Cost": 2, "Tags": ["skill", "block"],
                           "Facts": [('block', 12, 'source'), ('status', 'standard.flame_barrier', 4, 'source')]},
    "flame_barrier+": {"Cost": 2, "Tags": ["skill", "block"],
                            "Facts": [('block', 16, 'source'), ('status', 'standard.flame_barrier', 6, 'source')]},
    "headbutt": {"Cost": 1, "Tags": ["attack"],
                      "Facts": [('damage', 9, 'event'), ('choose', 'source', 'DiscardPile', (), 1, 1, 'ToDrawPileTop')]},
    "headbutt+": {"Cost": 1, "Tags": ["attack"],
                       "Facts": [('damage', 12, 'event'), ('choose', 'source', 'DiscardPile', (), 1, 1, 'ToDrawPileTop')]},
    "immolate": {"Cost": 2, "Tags": ["attack"],
                      "Facts": [('damage', 21, 'allEnemies'), ('card', 'burn', 1, 'DiscardPile', 'source')]},
    "immolate+": {"Cost": 2, "Tags": ["attack"],
                       "Facts": [('damage', 28, 'allEnemies'), ('card', 'burn', 1, 'DiscardPile', 'source')]},
    "intimidate": {"Cost": 0, "Tags": ["skill"],
                        "Facts": [('status', 'standard.weak', 1, 'allEnemies')]},
    "intimidate+": {"Cost": 0, "Tags": ["skill"],
                         "Facts": [('status', 'standard.weak', 2, 'allEnemies')]},
    "power_through": {"Cost": 1, "Tags": ["skill", "block"],
                           "Facts": [('card', 'wound', 2, 'Hand', 'source'), ('block', 15, 'source')]},
    "power_through+": {"Cost": 1, "Tags": ["skill", "block"],
                            "Facts": [('card', 'wound', 2, 'Hand', 'source'), ('block', 20, 'source')]},
    "rage": {"Cost": 0, "Tags": ["skill"],
                  "Facts": [('status', 'standard.rage', 3, 'source')]},
    "rage+": {"Cost": 0, "Tags": ["skill"],
                   "Facts": [('status', 'standard.rage', 5, 'source')]},
    "reckless_charge": {"Cost": 0, "Tags": ["attack"],
                             "Facts": [('damage', 7, 'event'), ('card', 'dazed', 1, 'DrawPile', 'source')]},
    "reckless_charge+": {"Cost": 0, "Tags": ["attack"],
                              "Facts": [('damage', 10, 'event'), ('card', 'dazed', 1, 'DrawPile', 'source')]},
    "seeing_red": {"Cost": 1, "Tags": ["skill"],
                        "Facts": [('gain', 'standard.energy', 2, 'source')]},
    "seeing_red+": {"Cost": 0, "Tags": ["skill"],
                         "Facts": [('gain', 'standard.energy', 2, 'source')]},
    "sever_soul": {"Cost": 2, "Tags": ["attack"],
                        "Facts": [('each', 'Hand', 'PileOrder', None, (('move', 'cardInstance.iterated', 'ExhaustPile'),))]},
    "sever_soul+": {"Cost": 2, "Tags": ["attack"],
                         "Facts": [('each', 'Hand', 'PileOrder', None, (('move', 'cardInstance.iterated', 'ExhaustPile'),))]},
    "shockwave": {"Cost": 2, "Tags": ["skill"],
                       "Facts": [('status', 'standard.weak', 3, 'allEnemies'), ('status', 'standard.vulnerable', 3, 'allEnemies')]},
    "shockwave+": {"Cost": 2, "Tags": ["skill"],
                        "Facts": [('status', 'standard.weak', 5, 'allEnemies'), ('status', 'standard.vulnerable', 5, 'allEnemies')]},
}

# inv:§4.1 -- the 10 zero-new-ability enemies: (hp_min, hp_max, action ids).
# §140: mirrors `rd_core::state::MAX_ENEMIES_IN_FIGHT`. The kernel enforces it on **summons**;
# this file enforces it on what the content **places**.
MAX_ENEMIES_IN_FIGHT = 4

INV_MONSTERS = [
    ("spike_slime_s", 10, 14, ["spike_slime_s.tackle"]),
    # §129: the wiki's act-3 boss, parked in the Boss pool (acts still share content).
    # §137: the act-3 normal pool gets thicker.
    ("darkling", 48, 48, ["darkling.nip", "darkling.chomp"]),
    # §212: wiki `The Maw` -- 300 HP (and "the only enemy whose Max HP does not change based on
    # Ascension level"), `Roar` / `Slam` / `Nom Nom` / `Drool`.
    ("maw", 300, 300, ["maw.roar", "maw.slam", "maw.nom_nom", "maw.drool"]),
    # §134: acts 2 and 3 have their own elites.
    ("gremlin_leader", 140, 140,
     ["gremlin_leader.slash", "gremlin_leader.rally", "gremlin_leader.summon"]),
    # §211: wiki `Giant Head` (Elite, Act 3) -- 500 HP (A8 520), `Slow`, `Count` 13,
    # `Glare` 1 Weak, `It Is Time` (30, +5 per use, cap 60; A3 40/70).
    ("giant_head", 500, 500,
     ["giant_head.count", "giant_head.glare", "giant_head.it_is_time"]),
    ("time_eater", 456, 456,
     ["time_eater.reverberate", "time_eater.ripple", "time_eater.head_slam"]),
    # §130: act 2 and act 3 have monsters of their own -- the point of the section.
    ("shelled_parasite", 68, 68, ["shelled_parasite.suck", "shelled_parasite.double_strike"]),
    # §213: wiki `Chosen` (Act 2 normal) -- HP 95-99 (A7 98-103), five moves:
    # Poke 5x2 (A2 6x2), Hex, Debilitate 10 + 2 Vulnerable (A2 12), Drain, Zap 18 (A2 21).
    ("chosen", 95, 99,
     ["chosen.poke", "chosen.hex", "chosen.debilitate", "chosen.drain", "chosen.zap"]),
    ("byrd", 25, 25, ["byrd.peck", "byrd.swoop"]),
    # §214: wiki `Shapes#Spiker` -- HP 42-56 (A7 44-60). The two moves are the wiki's `Attack` and
    # `Buff Thorns` (the ids are historical: `cut` = Attack, `spike` = Buff Thorns).
    ("spiker", 42, 56, ["spiker.cut", "spiker.spike"]),
    ("orb_walker", 90, 90, ["orb_walker.laser", "orb_walker.claw"]),
    # §152: the rest of act 1's roster, wiki numbers.
    # §258: the two louses had each other's move -- wiki says Red = Bite + Grow,
    # Green = Bite + Spit Web.
    ("louse_red", 10, 15, ["louse_red.bite", "louse_red.grow"]),
    ("louse_green", 11, 16, ["louse_green.bite", "louse_green.spit_web"]),
    ("fungi_beast", 22, 28, ["fungi_beast.bite", "fungi_beast.grow"]),
    ("slaver_red", 46, 50, ["slaver_red.stab", "slaver_red.scrape", "slaver_red.entangle"]),
    ("gremlin_nob", 82, 86,
     ["gremlin_nob.bellow", "gremlin_nob.rush", "gremlin_nob.skull_bash"]),
    # §173: the wiki's act-1 elite #2 and act-2 elites #2/#3.
    # Lagavulin: HP 109-111, Metallicize 8, Sleep for rounds 1-3 (`intent.round` rule), then
    # `siphon_soul`/`attack` alternating -- the order is chosen so round 4 is the Attack.
    ("lagavulin", 109, 111, ["lagavulin.siphon_soul", "lagavulin.attack",
                            "lagavulin.sleep", "lagavulin.stunned"]),
    ("book_of_stabbing", 160, 164,
     ["book_of_stabbing.multi_stab", "book_of_stabbing.big_stab"]),
    ("taskmaster", 54, 60, ["taskmaster.scouring_whip"]),
    # §175: act 3's elites. Nemesis carries `standard.phantom_veil` (the alternating Intangible);
    # Reptomancer summons Daggers; the Dagger's `Explode` does **not** kill it (no `destroyCombatant`).
    ("nemesis", 185, 185, ["nemesis.tri_attack", "nemesis.tri_burn", "nemesis.scythe"]),
    ("reptomancer", 180, 190,
     ["reptomancer.spawn_dagger", "reptomancer.big_bite", "reptomancer.snake_strike"]),
    ("dagger", 20, 25, ["dagger.wound", "dagger.explode"]),
    # §201: wiki `Thieves`. A7 raises HP to 46-50 and Thievery to 20; `EACT` has no ascension
    # column, so the content pins the base numbers (a known, documented gap).
    ("looter", 44, 48, ["looter.mug", "looter.lunge", "looter.smoke_bomb", "looter.escape"]),
    # §201: wiki `Thieves` -- HP 44-48 (A7 46-50); Mug 10 (+ steal 15), Lunge 12, Smoke Bomb 6
    # Block, Escape (leaves with the gold).
    # §147: the `Constricted` carrier (wiki HP 170; Strategic / Aggressive 16 / 22).
    # §148: the **cycle** is the two Aggressive moves; `Strategic` is a round-1 **rule**, not a
    # cycle slot (StS opens with it once). That is why it is absent from this list --
    # §214: wiki `Spire Growth` -- three moves: Constrict (strategic), Quick Tackle (aggressive),
    # Smash (aggressive_heavy). `strategic` is now **listed** by the record, not just an EACT row.
    ("spire_growth", 170, 170,
     ["spire_growth.strategic", "spire_growth.aggressive", "spire_growth.aggressive_heavy"]),
    ("fat_gremlin", 13, 17, ["fat_gremlin.smash"]),
    ("sneaky_gremlin", 10, 14, ["sneaky_gremlin.puncture"]),
    ("blue_slaver", 46, 50, ["blue_slaver.stab", "blue_slaver.rake"]),
    ("acid_slime_s", 8, 12, ["acid_slime_s.tackle", "acid_slime_s.lick"]),
    ("acid_slime_m", 28, 32, ["acid_slime_m.corrosive_spit",
                              "acid_slime_m.tackle", "acid_slime_m.lick"]),
    ("spike_slime_m", 28, 32, ["spike_slime_m.flame_tackle", "spike_slime_m.lick"]),
    ("jaw_worm", 40, 44, ["jaw_worm.chomp", "jaw_worm.thrash", "jaw_worm.bellow"]),
    ("cultist", 48, 54, ["cultist.incantation", "cultist.dark_strike"]),
    # inv:§0 flaw 4 -- the game files say 21-25, the wiki infobox says 23-25 and
    # its own Ascension value (22-26) is lower than the base one.  We take 21-25.
    ("gremlin_wizard", 21, 25, ["gremlin_wizard.charging"]),
    # inv:§4.2 -- the first elite, one row per instance. **Downgraded on purpose and in writing**:
    # no `Dazed` card (so Beam is 9 damage and nothing else) and no `Artifact 1` (the kernel has no
    # such status).
    ("sentry_1", 38, 42, ["sentry.bolt", "sentry.beam"]),
    ("sentry_2", 38, 42, ["sentry.bolt", "sentry.beam"]),
    ("sentry_3", 38, 42, ["sentry.bolt", "sentry.beam"]),
    # inv:§4.3 -- the act-1 boss. **Downgraded in writing**: no Split (the kernel cannot add
    # combatants mid-fight), which is the fight's identity; the three-move cycle is faithful.
    ("slime_boss", 140, 140, ["slime_boss.goop_spray", "slime_boss.preparing", "slime_boss.slam"]),

    # ================= §194: the wiki's boss pools, three per act =================
    # Act 1 (wiki: HP 240 / AscHP 250). The wiki's pattern is Charging Up, Fierce Bash, Vent Steam,
    # Whirlwind; Mode Shift / Defensive Mode / Roll Attack / Twin Slam are the mode sequence.
    ("the_guardian", 240, 240, ["the_guardian.charging_up", "the_guardian.fierce_bash",
                                "the_guardian.vent_steam", "the_guardian.whirlwind"]),
    # Act 1 (HP 250 / 264): the cycle is **rotated** so `(round-1) % 7` matches the wiki from turn 3
    # on; turns 1-2 are the two opening rules (Activate, Divider).
    ("hexaghost", 250, 250, ["hexaghost.sear", "hexaghost.inferno", "hexaghost.sear",
                             "hexaghost.tackle", "hexaghost.sear", "hexaghost.inflame",
                             "hexaghost.tackle"]),
    # Act 2 (HP 420 / 440 -- this replaced an invented 330).
    ("the_champ", 420, 420, ["the_champ.heavy_slash", "the_champ.face_slap",
                             "the_champ.defensive_stance", "the_champ.gloat"]),
    # Act 2 (HP 300 / 320). The cycle starts at Flail because the two Orbs are already deployed.
    ("bronze_automaton", 300, 300, ["bronze_automaton.flail", "bronze_automaton.boost",
                                    "bronze_automaton.flail", "bronze_automaton.boost",
                                    "bronze_automaton.hyper_beam", "bronze_automaton.stunned"]),
    ("bronze_orb", 52, 52, ["bronze_orb.stasis", "bronze_orb.beam", "bronze_orb.support_beam"]),
    # Act 2 (HP 282 / 300).
    ("the_collector", 282, 282, ["the_collector.fireball", "the_collector.buff"]),
    ("torch_head", 38, 38, ["torch_head.tackle"]),
    # Act 3 (HP 300 / 320): Slash, Slash, Soul Strike, Slash -- 75/25 and never three Slashes.
    ("awakened_one", 300, 300, ["awakened_one.slash", "awakened_one.slash",
                                "awakened_one.soul_strike", "awakened_one.slash"]),
    # Act 3 (HP 250 / 265 each). The first **pair** of bosses.
    ("donu", 250, 250, ["donu.circle_of_power", "donu.beam"]),
    ("deca", 250, 250, ["deca.beam", "deca.square_of_protection"]),
]

# inv:§4.1 -- every enemy action, as mechanically derived facts.
INV_ACTIONS = {
    # §193: `N = Number between (7-11;{{Asc|2|9-13}}), chosen at the start of combat` -- the amount
    # is a counter the fight rolls at spawn, not a constant (the range lives in `INV_ROLLS`).
    "darkling.nip": ("Attack", [("damage", ("counter", "roll.nip", "source"), "event")]),
    "darkling.chomp": ("Attack", [("damage", 8, "event"), ("damage", 8, "event")]),
    # §212: wiki `The Maw` -- Roar 3 Weak + 3 Frail (A17 5/5), Slam 25 (A2 30),
    # Nom Nom 5 x ceil(turn/2) (a multi-hit, hence `repeat`), Drool 3 Strength (A17 5).
    "maw.roar": ("Debuff", [("status", "standard.weak", 3, "event"),
                            ("status", "standard.frail", 3, "event")]),
    "maw.slam": ("Attack", [("damage", 25, "event")]),
    "maw.nom_nom": ("Attack", [("repeat", ("expr", "divide"), "damage", 5, "event")]),
    "maw.drool": ("Buff", [("status", "standard.strength", 3, "source")]),
    "gremlin_leader.slash": ("Attack", [("damage", 6, "event"), ("damage", 6, "event"),
                                ("damage", 6, "event")]),
    "gremlin_leader.rally": ("Defend", [("block", 12, "source"),
                                        ("status", "standard.strength", 5, "source")]),
    # §211: wiki `Giant Head`: Glare applies **1 Weak** and nothing else (the 12 damage that used
    # to sit here was the §130 simplification).
    "giant_head.glare": ("Debuff", [("status", "standard.weak", 1, "event")]),
    # §211: flat 13 (the wiki's Count has no A-row; 26 + A3 36 was the §130 simplification).
    "giant_head.count": ("Attack", [("damage", 13, "event")]),
    # `It Is Time`: the number lives in a **counter** (30 / A3 40, written by `Counters`); the
    # program clamps it to the cap, deals it, then raises it by 5 -- so the escalation needs no
    # repeated arithmetic in the content.
    "giant_head.it_is_time": ("Attack",
                              [("damage", ("counter", "it_is_time_damage", "source"), "event"),
                               ("when", None, "counter", "it_is_time_damage", 60, False, "source"),
                               ("when", None, "counter", "it_is_time_damage", 5, True, "source")]),
    # \u00a7138: summoning -- two minions the encounter never lists.
    "gremlin_leader.summon": ("Buff", [("spawn", "sneaky_gremlin", 10),
                                              ("spawn", "gremlin_wizard", 20)]),
    "shelled_parasite.suck": ("Attack", [("damage", 10, "event"), ("block", 2, "source")]),
    "shelled_parasite.double_strike": ("Attack", [("damage", 6, "event"), ("damage", 6, "event")]),
    # §213: wiki `Chosen`. Four of the five moves carry an A2 damage row; `Hex` / `Drain` are
    # status-only (no A-row on the page).
    "chosen.poke": ("Attack", [("damage", 5, "event"), ("damage", 5, "event")]),
    "chosen.hex": ("Debuff", [("status", "standard.hex", 1, "event")]),
    "chosen.drain": ("Debuff", [("status", "standard.weak", 3, "event"),
                                ("status", "standard.strength", 3, "source")]),
    "chosen.zap": ("Attack", [("damage", 18, "event")]),
    "chosen.debilitate": ("Attack", [("damage", 10, "event"),
                                     ("status", "standard.vulnerable", 2, "event")]),
    "byrd.peck": ("Attack", [("damage", 1, "event")] * 5),
    "byrd.swoop": ("Attack", [("damage", 12, "event")]),
    "spiker.cut": ("Attack", [("damage", 7, "event")]),
    # §214: `spike` is the wiki's `Buff Thorns` (+2 Thorns) -- the id is historical. The counter is
    # how "at most 6 times" is expressed (the AI rule reads it).
    "spiker.spike": ("Buff", [("status", "standard.thorns", 2, "source"),
                              ("counter", "thorns_buffs", 1, True, "source")]),
    "orb_walker.laser": ("Attack", [("damage", 10, "event"),
                                    ("status", "standard.weak", 2, "event")]),
    "orb_walker.claw": ("Attack", [("damage", 15, "event")]),
    "the_champ.heavy_slash": ("Attack", [("damage", 16, "event")]),
    # §194: Metallicize is 5 (wiki); A9 -> 18 Block / 6, A19 -> 20 / 7.
    "the_champ.defensive_stance": ("Defend", [("block", 15, "source"),
                                              ("status", "standard.metallicize", 5, "source")]),
    "the_champ.execute": ("Attack", [("damage", 10, "event"), ("damage", 10, "event")]),
    # §194: Haste -- "when reduced to below half HP, heals to 50% (A19: also 32 Block), once".
    "time_eater.haste": ("Buff", [("heal", ("expr", "max"), "source"),
                                  ("counter", "te_haste", 1, False, "source")]),
    "time_eater.reverberate": ("Attack", [("damage", 7, "event"), ("damage", 7, "event"),
                                          ("damage", 7, "event")]),
    # §195.7: "Applies 1 Draw Reduction" -- the status is a `TurnStartDraw` passive + a TurnEnded
    # decay, i.e. "next turn draw 1 less".
    "time_eater.head_slam": ("Attack", [("damage", 26, "event"),
                                        ("status", "standard.draw_reduction", 1, "event")]),
    "time_eater.ripple": ("Defend", [("block", 20, "source"),
                                     ("status", "standard.weak", 1, "event"),
                                     ("status", "standard.vulnerable", 1, "event")]),
    # §152: act 1's new enemies (wiki numbers).
    # §193: `N = Number between (5-7;{{Asc|2|6-8}}), chosen at the start of combat`.
    "louse_red.bite": ("Attack", [("damage", ("counter", "roll.bite", "source"), "event")]),
    "louse_red.grow": ("Buff", [("status", "standard.strength", 3, "source")]),
    # §258: Spit Web is the **Green** Louse's move (the id used to say `louse_red`), and the
    # green Bite is the same spawn-time roll as the red one -- not a hard-coded 6.
    "louse_green.spit_web": ("Debuff", [("status", "standard.weak", 2, "event")]),
    "louse_green.bite": ("Attack", [("damage", ("counter", "roll.bite", "source"), "event")]),
    "fungi_beast.bite": ("Attack", [("damage", 6, "event")]),
    "fungi_beast.grow": ("Buff", [("status", "standard.strength", 3, "source")]),
    # §196: Red Slaver's third move -- wiki: "Applies 1 Entangled" (+ the once-per-combat flag).
    "slaver_red.entangle": ("Debuff", [("status", "standard.entangled", 1, "event"),
                                       ("modify", "standard.entangle_ready", -99, "source")]),
    "slaver_red.stab": ("Attack", [("damage", 13, "event")]),
    # §187 回 wiki 重核：Red Slaver 的 Scrape 是 **8 伤害 + 1 Vulnerable**
    # (`wiki_slavers.txt`：`Deals (8;{{Asc|2|9}}) damage. Applies (1;{{Asc|17|2}}) Vulnerable.`)。
    # 内容与这张清单**当初一起写错**（写成了蓝色 Slaver 的 Rake），
    # 所以 20 道闸门全绿 —— 与 §186 的 `blind` 是同一个形状。
    "slaver_red.scrape": ("Attack", [("damage", 8, "event"),
                                     ("status", "standard.vulnerable", 1, "event")]),
    "gremlin_nob.bellow": ("Buff", [("status", "standard.strength", 2, "source")]),
    "gremlin_nob.rush": ("Attack", [("damage", 14, "event")]),
    "gremlin_nob.skull_bash": ("Attack", [("damage", 6, "event"),
                                          ("status", "standard.vulnerable", 2, "event")]),
    # §147: Constricted itself is a content trigger (see `standard.constricted`), so the action
    # only has to apply it.
    "spire_growth.strategic": ("Debuff", [("status", "standard.constricted", 10, "event")]),
    "spire_growth.aggressive": ("Attack", [("damage", 16, "event")]),
    "spire_growth.aggressive_heavy": ("Attack", [("damage", 22, "event")]),
    "spike_slime_s.tackle": ("Attack", [("damage", 5, "event")]),
    "fat_gremlin.smash": ("Attack", [("damage", 4, "event"),
                                     ("status", "standard.weak", 1, "event")]),
    "sneaky_gremlin.puncture": ("Attack", [("damage", 9, "event")]),
    "blue_slaver.stab": ("Attack", [("damage", 12, "event")]),
    "blue_slaver.rake": ("Attack", [("damage", 7, "event"),
                                    ("status", "standard.weak", 1, "event")]),
    "acid_slime_s.tackle": ("Attack", [("damage", 3, "event")]),
    "acid_slime_s.lick": ("Debuff", [("status", "standard.weak", 1, "event")]),
    "acid_slime_m.corrosive_spit": ("Attack", [("damage", 7, "event"),
                                               ("card", "slimed", 1, "DiscardPile", "event")]),
    "acid_slime_m.tackle": ("Attack", [("damage", 10, "event")]),
    "acid_slime_m.lick": ("Debuff", [("status", "standard.weak", 1, "event")]),
    "spike_slime_m.flame_tackle": ("Attack", [("damage", 8, "event"),
                                              ("card", "slimed", 1, "DiscardPile", "event")]),
    "spike_slime_m.lick": ("Debuff", [("status", "standard.frail", 1, "event")]),
    "jaw_worm.chomp": ("Attack", [("damage", 11, "event")]),
    "jaw_worm.thrash": ("Attack", [("damage", 7, "event"), ("block", 5, "source")]),
    "jaw_worm.bellow": ("Buff", [("status", "standard.strength", 3, "source"),
                                 ("block", 6, "source")]),
    "cultist.incantation": ("Buff", [("status", "ritual", 3, "source")]),
    "cultist.dark_strike": ("Attack", [("damage", 6, "event")]),
    "gremlin_wizard.charging": ("Special", []),
    "slime_boss.goop_spray": ("Special", [("card", "slimed", 3, "DiscardPile", "event")]),
    "slime_boss.preparing": ("Special", []),
    "slime_boss.slam": ("Attack", [("damage", 35, "event")]),
    "sentry.bolt": ("Attack", [("card", "dazed", 2, "DiscardPile", "event")]),
    "sentry.beam": ("Attack", [("damage", 9, "event")]),
    "gremlin_wizard.ultimate_blast": ("Attack", [
        ("damage", 25, "event"),
        # the AI turn counter is reset by the blast itself; it is the content-side
        # substitute for `intent.round` (there is none, see Notes.Deviations).
        ("counter", "gremlin_wizard_charges", 0, False, "source")]),
    # §173: the three elites that bring the act-1 and act-2 pools up to the wiki's three each.
    # `Sleep` is an **empty** program on purpose: the turn is taken and nothing happens.
    "lagavulin.sleep": ("Unknown", []),
    # §257: waking up by damage costs it a turn; the move itself only clears the "just woke" flag.
    "lagavulin.stunned": ("Unknown",
                          [("counter", "lagavulin_woken", 0, False, "source")]),
    "lagavulin.attack": ("Attack",
                         [("damage", 18, "event"),
                          # §257：三阶出招循环（Attack / Attack / Siphon Soul）的计数器。
                          ("counter", "lagavulin_step", ("expr", "remainder"), False, "source")]),
    # The wiki's Siphon Soul is "-1 Strength, -1 Dexterity" -- and it must be **`modifyStatusStacks`**,
    # not `applyStatus` with negative stacks: the latter throws `Exec` (§174), which the driver records
    # as `StepThrew` and then the fight is stuck with that enemy as the active combatant.
    "lagavulin.siphon_soul": ("Debuff", [("modify", "standard.strength", -1, "event"),
                                        ("modify", "standard.dexterity", -1, "event"),
                                        ("counter", "lagavulin_step", ("expr", "remainder"),
                                         False, "source")]),
    # "6×N damage, N = times Multi Stab was used this combat + 2". The order is damage-then-bump
    # because `setCombatantCounter` is a **queued effect**: a program cannot read a counter it just
    # wrote (measured: bump-then-repeat still counted the old value). "completed uses + 3" is
    # identically the wiki's "uses + 2". `repeat` **flattens** its body facts behind the count.
    "book_of_stabbing.multi_stab": ("Attack",
                                    [("repeat", ("expr", "add"), "damage", 6, "event"),
                                     ("counter", "book_stab_uses", 1, True, "source")]),
    "book_of_stabbing.big_stab": ("Attack",
                                  [("damage", 21, "event"),
                                   # §257：A18 起 Single Stab 也推进 N（wiki 的第二颗星号）。
                                   ("counter", "book_stab_uses",
                                    ("counter", "book_stab_single_bump", "source"), True, "source")]),
    # §175: act 3's two elites and the Dagger they summon.
    "nemesis.tri_attack": ("Attack", [("damage", 6, "event"), ("damage", 6, "event"),
                                      ("damage", 6, "event")]),
    "nemesis.tri_burn": ("Debuff", [("card", "burn", 3, "DiscardPile", "event")]),
    "nemesis.scythe": ("Attack", [("damage", 45, "event")]),
    "reptomancer.spawn_dagger": ("Buff", [("spawn", "dagger", 22)]),
    "reptomancer.big_bite": ("Attack", [("damage", 30, "event")]),
    "reptomancer.snake_strike": ("Attack", [("damage", 13, "event"), ("damage", 13, "event"),
                                            ("status", "standard.weak", 1, "event")]),
    "dagger.wound": ("Attack", [("damage", 9, "event"),
                                ("card", "wound", 1, "DiscardPile", "event")]),
    # §200: Explode = 25 damage **and the dagger dies** (wiki: Explode 25, then it leaves the
    # fight). Before §200 the kernel refused to remove the acting combatant, so it only dealt damage.
    "dagger.explode": ("Attack", [("damage", 25, "event"), ("destroy", "source")]),
    # §201: wiki `Thieves` -- every attack steals 15 (`Thievery`), Escape carries it away and the
    # Looter leaves the fight (`destroy` after `carry` -- order matters, the counter must be read
    # before the combatant is removed).
    "looter.mug": ("Attack", [("damage", 10, "event"), ("counter", "stolen_gold", 15, True, "source")]),
    "looter.lunge": ("Attack", [("damage", 12, "event"), ("counter", "stolen_gold", 15, True, "source")]),
    "looter.smoke_bomb": ("Defend", [("block", 6, "source")]),
    "looter.escape": ("Special", [("carry", "stolen_gold", "source"), ("destroy", "source")]),
    "taskmaster.scouring_whip": ("Attack", [("damage", 7, "event"),
                                            ("card", "wound", 1, "DiscardPile", "event")]),

    # ================= §194: the six new bosses + two minions =================
    # --- The Guardian (wiki: 32/36, 5x4, 9 Block, 9/10, 8x2, 3 Sharp Hide at A19 4, 20 Block) ----
    "the_guardian.charging_up": ("Defend", [("block", 9, "source")]),
    "the_guardian.fierce_bash": ("Attack", [("damage", 32, "event")]),
    "the_guardian.vent_steam": ("Debuff", [("status", "standard.weak", 2, "event"),
                                           ("status", "standard.vulnerable", 2, "event")]),
    "the_guardian.whirlwind": ("Attack", [("damage", 5, "event"), ("damage", 5, "event"),
                                          ("damage", 5, "event"), ("damage", 5, "event"),
                                          ("counter", "guard_mode", 0, False, "source"),
                                          ("counter", "guard_step", 0, False, "source")]),
    # §195.1: Mode Shift is a **budget** now (seeded at spawn from the record's `Counters`, drained
    # by the HP actually lost), so Defensive Mode *refills* it by the wiki's +10 per trigger.
    "the_guardian.defensive_mode": ("Buff", [("block", 20, "source"),
                                             ("status", "standard.sharp_hide", 3, "source"),
                                             ("counter", "mode_shift_budget", 10, True, "source"),
                                             ("counter", "guard_mode", 1, False, "source"),
                                             ("counter", "guard_step", 0, False, "source")]),
    "the_guardian.roll_attack": ("Attack", [("damage", 9, "event"),
                                            ("counter", "guard_step", 1, False, "source")]),
    "the_guardian.twin_slam": ("Attack", [("damage", 8, "event"), ("damage", 8, "event"),
                                          ("modify", "standard.sharp_hide", -99, "source"),
                                          ("counter", "guard_step", 2, False, "source")]),
    # --- Hexaghost (wiki: (HP/12+1)x6, 6 + 1 Burn, 5x2, 12 Block + 2 Str, 2x6 + 3 Burn+) ---------
    "hexaghost.activate": ("Special", []),
    "hexaghost.divider": ("Attack", [("repeat", ("expr", "add"), "damage", 6, "event")]),
    "hexaghost.sear": ("Attack", [("damage", 6, "event"),
                                  ("card", "burn", 1, "DiscardPile", "event")]),
    "hexaghost.tackle": ("Attack", [("damage", 5, "event"), ("damage", 5, "event")]),
    "hexaghost.inflame": ("Defend", [("block", 12, "source"),
                                     ("status", "standard.strength", 2, "source")]),
    # §195.7: Inferno also upgrades every Burn that already exists (wiki: "Upgrades all Burns").
    "hexaghost.inferno": ("Attack", [("damage", 2, "event"), ("damage", 2, "event"),
                                     ("damage", 2, "event"), ("damage", 2, "event"),
                                     ("damage", 2, "event"), ("damage", 2, "event"),
                                     ("card", "burn+", 3, "DiscardPile", "event"),
                                     ("upgrade", "event", "burn", None, None)]),
    # --- The Champ's four new moves (wiki: Face Slap 12 + 2 Frail + 2 Vuln, Gloat 2 Str,
    #     Taunt 2 Weak + 2 Vuln, Anger clears debuffs + 6 Str) -----------------------------------
    "the_champ.face_slap": ("Attack", [("damage", 12, "event"),
                                       ("status", "standard.frail", 2, "event"),
                                       ("status", "standard.vulnerable", 2, "event")]),
    "the_champ.gloat": ("Buff", [("status", "standard.strength", 2, "source")]),
    "the_champ.taunt": ("Debuff", [("status", "standard.weak", 2, "event"),
                                   ("status", "standard.vulnerable", 2, "event")]),
    "the_champ.anger": ("Buff", [("modify", "standard.weak", -99, "source"),
                                 ("modify", "standard.vulnerable", -99, "source"),
                                 ("modify", "standard.frail", -99, "source"),
                                 ("status", "standard.strength", 6, "source"),
                                 ("counter", "champ_phase", 1, False, "source"),
                                 ("counter", "champ_exec", 0, False, "source")]),
    # --- Bronze Automaton (wiki: Flail 7x2, Boost 3 Str + 9 Block, HYPER BEAM 45, Stunned) --------
    # §195.6: "Spawn Orbs" is two summons (two nodes, because each minted combatant needs its own id).
    "bronze_automaton.spawn_orbs": ("Special", [("spawn", "bronze_orb", 52),
                                                ("spawn", "bronze_orb", 52)]),
    "bronze_automaton.flail": ("Attack", [("damage", 7, "event"), ("damage", 7, "event")]),
    "bronze_automaton.boost": ("Defend", [("status", "standard.strength", 3, "source"),
                                          ("block", 9, "source")]),
    "bronze_automaton.hyper_beam": ("Attack", [("damage", 45, "event")]),
    "bronze_automaton.stunned": ("Special", []),
    # --- Bronze Orb (wiki: Beam 8, Support Beam +12 Block to allies) ------------------------------
    # §195.4: Stasis -- steal the highest-rarity card from the draw pile (discard if empty) into
    # `SetAsidePile`, then spend its own status ("once per combat").
    "bronze_orb.stasis": ("Debuff", [("select", "allEnemies", "DrawPile", "DiscardPile",
                                      "HighestRarity", 1, "SetAsidePile"),
                                     ("modify", "standard.stasis_ready", -99, "source")]),
    "bronze_orb.beam": ("Attack", [("damage", 8, "event")]),
    "bronze_orb.support_beam": ("Defend", [("block", 12, "allAllies")]),
    # --- The Collector (wiki: Fireball 18, Buff +3 Str + 15 Block, Mega Debuff 3/3/3) -------------
    # §195.3: the two moves the weighted rule draws from, each recording itself in `last_move`
    # (that counter is how "cannot Buff twice in a row" is expressed without kernel state).
    "the_collector.spawn": ("Special", [("spawn", "torch_head", 38),
                                        ("spawn", "torch_head", 38)]),
    "the_collector.fireball": ("Attack", [("damage", 18, "event")]),
    "the_collector.buff": ("Defend", [("status", "standard.strength", 3, "allAllies"),
                                      ("block", 15, "source")]),
    "the_collector.mega_debuff": ("Debuff", [("status", "standard.weak", 3, "event"),
                                             ("status", "standard.vulnerable", 3, "event"),
                                             ("status", "standard.frail", 3, "event")]),
    "torch_head.tackle": ("Attack", [("damage", 7, "event")]),
    # --- Awakened One (wiki: Slash 20, Soul Strike 6x4, Dark Echo 40, Tackle 10x3, Sludge 18+Void) -
    "awakened_one.slash": ("Attack", [("damage", 20, "event")]),
    "awakened_one.soul_strike": ("Attack", [("damage", 6, "event"), ("damage", 6, "event"),
                                            ("damage", 6, "event"), ("damage", 6, "event")]),
    "awakened_one.rebirth": ("Special", [("heal", ("expr", "max"), "source"),
                                         ("modify", "standard.curiosity", -99, "source"),
                                         ("counter", "ao_phase", 1, False, "source"),
                                         ("counter", "ao_started", 0, False, "source")]),
    "awakened_one.dark_echo": ("Attack", [("damage", 40, "event"),
                                          ("counter", "ao_started", 1, False, "source")]),
    "awakened_one.tackle": ("Attack", [("damage", 10, "event"), ("damage", 10, "event"),
                                       ("damage", 10, "event")]),
    "awakened_one.sludge": ("Attack", [("damage", 18, "event"),
                                       ("card", "void", 1, "DiscardPile", "event")]),
    # --- Donu / Deca (wiki: Beam 10x2 both, Circle of Power +3 Str, Square 16 Block) --------------
    "donu.circle_of_power": ("Buff", [("status", "standard.strength", 3, "allAllies")]),
    "donu.beam": ("Attack", [("damage", 10, "event"), ("damage", 10, "event")]),
    "deca.beam": ("Debuff", [("damage", 10, "event"), ("damage", 10, "event"),
                             ("card", "dazed", 2, "DiscardPile", "event")]),
    "deca.square_of_protection": ("Defend", [("block", 16, "allAllies")]),
}

# inv:§5.2 -- the weak pool.  The 4th entry (`enc_two_louses`) needs
# louse_red/louse_green, which are tier C (Curl Up needs a DamageTaken trigger).
INV_WEAK_POOL = {
    "enc_cultist": ["cultist"],
    "enc_jaw_worm": ["jaw_worm"],
    # The source rolls 50/50 acid|spike for the M and for the S independently;
    # a static enemy list pins one of the four combinations.
    "enc_small_slimes": ["acid_slime_m", "spike_slime_s"],
    # §130: act 2 and act 3 have encounters -- and therefore monsters -- of their own.
    "enc_shelled_parasite": ["shelled_parasite"],
    "enc_chosen": ["chosen"],
    # §138: the gang exists so that a **summoned** gremlin has a record to point at.
    "enc_gremlin_gang": ["fat_gremlin", "sneaky_gremlin", "gremlin_wizard"],
    "enc_byrds": ["byrd"],
    "enc_spiker": ["spiker"],
    "enc_orb_walker": ["orb_walker"],
    "enc_darklings": ["darkling", "darkling"],
    # §152: the rest of act 1's weak pool, wiki numbers (see patch_152_enemies.py).
    "enc_louse": ["louse_red"],
    # §258: wiki act-1 easy pool has both "1 Louse" and "2 Louses"; the 2-louse row is also the
    # only place the **green** louse appears (it used to have a roster row and no encounter).
    "enc_two_louses": ["louse_red", "louse_green"],
    "enc_fungi_beast": ["fungi_beast"],
    "enc_slaver_red": ["slaver_red"],
    # §147: the carrier for `Constricted` (act 3, wiki HP 170).
    "enc_spire_growth": ["spire_growth"],
    "enc_maw": ["maw"],
}
INV_WEAK_WEIGHT = 100  # inv:§5.2 权重之和 100（6 个遭遇按 20/16/16/16/16/16 分）

# inv:§5.3 -- the elite pool. One entry, so there is no weight question yet; `EncounterTables.Elite`
# in the document carries it, and this is what the check compares that against.
INV_ELITE_POOL = {
    # §134: one elite per later act.
    "enc_gremlin_leader": ["gremlin_leader"],
    "enc_giant_head": ["giant_head"],
    "enc_three_sentries": ["sentry_1", "sentry_2", "sentry_3"],
    # §152: a second act-1 elite, so the elite node is not always the same fight.
    "enc_gremlin_nob": ["gremlin_nob"],
    # §173: the wiki's three-per-act elite pools. Act 1 gains Lagavulin, act 2 gains Book of
    # Stabbing and the Slavers trio (Taskmaster + Red Slaver + Blue Slaver, in that order -- the
    # order is the turn order).
    "enc_lagavulin": ["lagavulin"],
    "enc_book_of_stabbing": ["book_of_stabbing"],
    "enc_slavers": ["taskmaster", "slaver_red", "blue_slaver"],
    # §175: act 3's two, so every act's elite pool has the wiki's three.
    "enc_nemesis": ["nemesis"],
    "enc_reptomancer": ["reptomancer", "dagger", "dagger"],
    # §201: the solo Looter (wiki: an act-1 normal encounter).
    "enc_looter": ["looter"],
}

# inv:§4.3 -- the boss pool. `inv:§4.3` says the three act-1 bosses are picked equiprobably; this
# content authors one of them (Slime Boss) and says why in the document.
# §130: the pool dicts above are the **union** (every encounter must be declared somewhere). These
# say which act each pool member belongs to, so the table checks can compare per act.
INV_ACT_TABLES = {
    "Weak": ["enc_cultist", "enc_jaw_worm", "enc_small_slimes",
             "enc_louse", "enc_fungi_beast", "enc_slaver_red",
             # §153: the Gremlin Gang is an **act-1** encounter (wiki); it sat in act 2.
             "enc_gremlin_gang",
             # §201: the Looter is an act-1 normal encounter.
             "enc_looter",
             # §258: "2 Red or Green Louses" -- the only place the green louse is reachable.
             "enc_two_louses"],
    "Weak2": ["enc_chosen", "enc_shelled_parasite"],
    "Weak3": ["enc_byrds", "enc_darklings", "enc_maw", "enc_orb_walker", "enc_spiker",
              "enc_spire_growth"],
    "Elite": ["enc_gremlin_nob", "enc_lagavulin", "enc_three_sentries"],
    "Elite2": ["enc_book_of_stabbing", "enc_gremlin_leader", "enc_slavers"],
    "Elite3": ["enc_giant_head", "enc_nemesis", "enc_reptomancer"],
    # §194: the wiki's "one of three, at random" per act. Act 1 lost the act-3 boss it never should
    # have had (Time Eater sat in `Boss`), and acts 2/3 stop replaying one invented boss.
    "Boss": ["enc_slime_boss", "enc_the_guardian", "enc_hexaghost"],
    "Boss2": ["enc_the_champ", "enc_bronze_automaton", "enc_the_collector"],
    "Boss3": ["enc_time_eater", "enc_awakened_one", "enc_donu_and_deca"],
}

INV_BOSS_POOL = {
    # Act 1.
    "enc_slime_boss": ["slime_boss"],
    "enc_the_guardian": ["the_guardian"],
    "enc_hexaghost": ["hexaghost"],
    # Act 2. The Champ is the same id but a **different fight** since §194 (HP 420, four more
    # moves): it used to be an invented 330-HP three-move boss.
    "enc_the_champ": ["the_champ"],
    # The orbs are deployed with the boss (the encounter roster is what lets a minion act, §138).
    "enc_bronze_automaton": ["bronze_automaton", "bronze_orb", "bronze_orb"],
    "enc_the_collector": ["the_collector", "torch_head", "torch_head"],
    # Act 3.
    "enc_time_eater": ["time_eater"],
    # §195.8: wiki -- the Awakened One comes with two Cultists, and they **flee** when it finally dies
    # (the kernel already does that for minions whose `owner` falls; the records declare `Owner`).
    "enc_awakened_one": ["awakened_one", "cultist", "cultist"],
    # The first **pair**: two bosses in one fight, which is what the wiki's Donu and Deca are.
    "enc_donu_and_deca": ["donu", "deca"],
}

# inv:§10 -- the 5 statuses, with the modifier the damage/block pipeline needs.
# `None` = the content cannot express it today (see Notes.KernelGapsFound).
# The magnitudes are copied from kernel/rd-core/src/status_catalog.rs:135-215,
# because a content image **disables** that catalog (exec.rs:2421-2426): with
# content present the candidate rows come only from STAT.PassiveModifiers.
INV_STATUSES = {
    # §227: Nightmare 的"下一回合把留存的副本拿进手牌" —— 一条 TurnStarted 触发器，
    # 没有任何修饰器（和 `standard.thorns` 一样属于"行为全在触发器里"）。
    "standard.nightmare_pending": [],
    # §231: Battle Trance 的"本回合不能再抽" —— 规则在内核的抽牌节点里，状态本身没有修饰器。
    "standard.no_draw": [],
    # §238: Double Tap's "next Attack is played twice" -- consumed by `play.rs`'s scope table.
    "standard.double_tap": [],
    # §242: Corruption -- `UsesStacks: false`; both rules are kernel-side, keyed on this id.
    "standard.corruption": [],
    # §244: Mayhem / Magnetism -- both are a single `TurnStarted` trigger.
    "standard.mayhem": [],
    "standard.magnetism": [],
    # §245: Panic Button -- the rule lives in `exec::gain_block_for` (keyed on this id).
    "standard.no_block_from_cards": [],
    # §248: Enlightenment's "cost at most N" -- the rule is `CostStage::CapCostAt`.
    "standard.cap_cost_at": [],
    # §256：Book of Stabbing 的 "受伤就塞 Wound"（规则全在触发器里）。
    "standard.painful_stabs": [],
    # §257：Lagavulin 的 Asleep —— 两条触发器（挨打醒 / 睡满三回合醒），无被动修饰器。
    "standard.lagavulin_asleep": [],
    # §260：八件遗物的载体状态 —— 全是"一条触发器 + 无被动修饰器"。
    "standard.orichalcum": [],
    "standard.mercury_hourglass": [],
    "standard.horn_cleat": [],
    "standard.captains_wheel": [],
    "standard.stone_calendar": [],
    "standard.cloak_clasp": [],
    "standard.incense_burner": [],
    "standard.pocketwatch": [],
    # §261：前两条有触发器（第 1 回合 +1 能量 / 多抽 2 张）；后两条**没有触发器**，
    # 它们的作用是给内核回合机看的两条标签。
    "standard.lantern": [],
    "standard.bag_of_preparation": [],
    "standard.ice_cream": [],
    "standard.calipers": [],
    # §262：六条纯触发器 + Pen Nib 的载体 + 翻倍载体（后者带 1 条 `PassiveModifiers`，
    # 由下面的修饰器表单独核对）。
    "standard.kunai": [],
    "standard.shuriken": [],
    "standard.ornamental_fan": [],
    "standard.letter_opener": [],
    "standard.nunchaku": [],
    "standard.ink_bottle": [],
    "standard.pen_nib": [],
    # §262: Pen Nib 的翻倍载体 —— 唯一一条"自己带的修饰器"就在它身上（×200 直接伤害）。
    # §264：`RestrictSourceCardTag: attack` 把 §262 那条"翻倍挡不住非攻击伤害"的偏差消掉了。
    "standard.double_damage": [("DamageDealt", "ScalePercent", 200, 250, "Direct")],
    # §263：`gremlin_horn` 有一条触发器；其余四条**没有触发器也没有修饰器** ——
    # 规则在内核（`exec.rs::S6a` 与倒下点的毒转移），状态只是载体。
    "standard.gremlin_horn": [],
    "standard.the_specimen": [],
    "standard.the_boot": [],
    "standard.torii": [],
    "standard.tungsten_rod": [],
    # §263：毒 —— **内核按 tag 读**（`damage_over_time`），自减 1 层由内容触发器做。
    "standard.poison": [],
    # §264：两条 `AppliesToStatusId` 改写 + 一条 `event.statusIs` 监听。
    # §264：两条**改写**。幅值与 `standard.vulnerable` / `standard.weak` 自己的那条对齐在
    # 同一个 `Priority`（300 / 200）—— 改写只换数字，不换排序。
    "standard.paper_phrog": [("DamageReceived", "ScalePercent", 175, 300, "Direct")],
    "standard.paper_krane": [("DamageDealt", "ScalePercent", 60, 200, "Direct")],
    "standard.champion_belt": [],
    # §265：`StatusStacks` / `StatusImmunity` 的载体（spec 的 `AppliesToStatusId` 是**过滤器**）。
    # 免疫那条的 `Operation`/`Magnitude` 不参与计算（判定只问"有没有这条 spec"），所以写 0。
    "standard.snecko_skull": [("StatusStacks", "AddFlat", 1, 100, None)],
    "standard.ginger": [("StatusImmunity", "AddFlat", 0, 100, None)],
    # §266：`red_skull` 带 `Condition`（HP ≤ 50%），`odd_mushroom` 带 `OverrideScope: Self`。
    "standard.red_skull": [("DamageDealt", "AddFlat", 3, 100, "Direct")],
    "standard.odd_mushroom": [("DamageReceived", "ScalePercent", 125, 300, "Direct")],
    # §268：五条载体。`runic_pyramid` 的全部行为是 `retain_hand` **标签**，`lizard_tail` 的是
    # `DeathPrevention` **行** —— 两者在内核侧都已接好，这批是第一次有内容去用。
    "standard.self_forming_clay": [],
    "standard.bird_faced_urn": [],
    "standard.runic_pyramid": [],
    "standard.lizard_tail": [],
    "standard.unceasing_top": [],
    # §269：两条 `TurnStartEnergy` 载体（挂不挂由运行层的 `KindMask` 决定）。
    "standard.slavers_collar": [("TurnStartEnergy", "AddPerStack", 1, 100, None)],
    "standard.busted_crown": [("TurnStartEnergy", "AddPerStack", 1, 100, None)],
    # §270：`ectoplasm` 的能量那一半（"不能再得金币"在运行层）。
    "standard.ectoplasm": [("TurnStartEnergy", "AddPerStack", 1, 100, None)],
    # §267：零基建批次。
    "standard.ring_of_the_serpent": [('TurnStartDraw', 'AddFlat', 1, 100, None)],
    "standard.philosophers_stone": [('TurnStartEnergy', 'AddPerStack', 1, 100, None)],
    "standard.akabeko": [('DamageDealt', 'AddFlat', 8, 100, 'Direct')],
    "standard.ring_of_the_snake": [],
    "standard.happy_flower": [],
    # §267：`art_of_war` 的能量走 `TurnStartEnergy` + `Condition`（回合末立的待决标记）。
    "standard.art_of_war": [("TurnStartEnergy", "AddFlat", 1, 100, None)],
    "standard.brimstone": [],
    "standard.mark_of_pain": [("TurnStartEnergy", "AddPerStack", 1, 100, None)],
    "standard.mutagenic_strength": [],
    "standard.centennial_puzzle": [],
    "standard.runic_cube": [],
    "standard.charons_ashes": [],
    "standard.duality": [],
    "standard.turnip": [("StatusImmunity", "AddFlat", 0, 100, None)],
    "standard.the_bomb_damage": [],
    "standard.the_bomb": [],
    "standard.sadistic_nature": [],
    "standard.panache": [],
    "standard.omega": [],
    # §237: the five trigger-hook powers. None has a passive modifier -- they are pure triggers
    # (`BlockGained` / `CardsDrawn` / `CardExhausted`).
    "standard.juggernaut": [],
    "standard.evolve": [],
    "standard.fire_breathing": [],
    "standard.dark_embrace": [],
    "standard.feel_no_pain": [],
    # §235: Demon Form 的"每回合开始加力量" —— 规则在内容触发器里（`ritual` 的 TurnStarted 兄弟）。
    "standard.demon_form": [],
    # §236: Brutality（每回合掉 1 血抽 1 张）与 Rupture（因牌失去生命时加力量）。
    "standard.brutality": [],
    "standard.rupture": [],
    # Declared inert by the kernel (`is_declared_inert`): it wants a TurnEnded content trigger,
    # not a modifier. `port-plan.md` §107.
    "standard.metallicize": [],
    # Thorns: a DamageTaken trigger (port-plan.md §116).
    "standard.thorns": [],
    # Downed / artifact / CardPlayed hooks (port-plan.md §117).
    "standard.spore_cloud": [],
    "standard.artifact": [],
    "standard.enrage": [],
    # The four built on existing hooks (port-plan.md §119).
    "standard.regen": [],
    "standard.rage": [],
    "standard.flame_barrier": [],
    "standard.combust": [],
    # Boss split: a Downed trigger that spawns two (port-plan.md §121).
    "standard.split": [],
    # Boss phase: at <=10 HP it splits once (port-plan.md §122).
    "standard.phase_split": [],
    # Time Eater's mechanic, prepared on an unused monster (port-plan.md §125).
    "standard.time_warp": [],
    # §149: the three damage-pipeline statuses -- no triggers at all, the kernel owns the rule.
    "standard.intangible": [],
    "standard.buffer": [],
    # §180: no triggers and no modifiers: its whole behaviour is `DeathPrevention`, which the
    # damage pipeline reads at the death point (`exec::resolve_damage_of_kind`). Listed with `[]`
    # because an empty expectation is the **assertion** ("this row must not grow modifiers"), not
    # an omission.
    "standard.fairy_in_a_bottle": [],
    # §181: no triggers, no modifiers -- `play.rs` reads its charges when a card program starts.
    "standard.duplication": [],
    "standard.plated_armor": [],
    # §175: Nemesis's carrier -- the first content row using a `TurnStarted` trigger.
    "standard.phantom_veil": [],
    # §147: `TurnEnded` trigger, damage = stacks, **ignores Block** ("lose HP" is not damage).
    "standard.constricted": [],
    "standard.strength": [("DamageDealt", "AddPerStack", 1, 100, "Direct")],
    "standard.vulnerable": [("DamageReceived", "ScalePercent", 150, 300, "Direct")],
    "standard.weak": [("DamageDealt", "ScalePercent", 75, 200, "Direct")],
    # `frail` is the only status on the *block* pipeline.  The wire string is
    # "BlockGain" -- the reference enum member name (`PassiveModifiers.cs:20`),
    # **not** "Block" (that is the kernel's *variant* name, not a wire string).  The numbers
    # come from the reference declaration (`StandardCombatPackage.cs:318-321`:
    # BlockGain / ScalePercent / 75 / Priority 200) and are folded by
    # `DeclarativePassiveBlockModifier` (`PassiveModifiers.cs:257-269`), which
    # reads the *gaining* combatant and passes `damageKind: null` -- hence the
    # None in the last slot.  Single stage, no priority-per-stage axis.
    "standard.frail": [("BlockGain", "ScalePercent", 75, 200, None)],
    "ritual": [],
    # §158: Dexterity. Same pipeline as `frail` and the same wire-string trap, but `AddPerStack`
    # (the reference declaration is `StandardCombatPackage.cs:360-363`:
    # BlockGain / AddPerStack / 1 / Priority 100). The kernel's own `BLOCK_MODIFIERS` table says the
    # same thing, but a content image **disables** that table (`exec.rs` §A), so this row is the only
    # thing that makes a Dexterity Potion move the number -- and
    # `dexterity_from_the_content_scales_a_real_defend` is what proves it does.
    "standard.dexterity": [("BlockGain", "AddPerStack", 1, 100, None)],
    # §158: the "give it back at the end of the turn" half of Flex / Speed Potion. No modifier: the
    # behaviour is a TurnEnded trigger that subtracts its own stacks from Strength / Dexterity and
    # then removes itself.
    "standard.lose_strength": [],
    "standard.lose_dexterity": [],
    # §219：`lose_strength` 的镜像 —— 回合末把"本回合被夺走的力量"还回去（`dark_shackles`）。
    # 没有修饰器：整条规则就是那个 `TurnEnded` 触发器（与 `lose_strength` 同形、符号相反）。
    "standard.regain_strength": [],
    # ================= §194 =================
    # Sharp Hide / Curiosity are the two the new bosses need, and both are `CardPlayed` triggers
    # filtered by a card tag -- the same shape as `standard.enrage`, which is why they are inert
    # here (no passive modifier; the whole effect is a trigger).
    "standard.sharp_hide": [],
    "standard.curiosity": [],
    # §195.1: the Guardian's Mode Shift -- a `DamageTaken` trigger that adds `eventAmount` (the HP
    # actually lost) to a counter. The threshold is an intent rule, so there is no passive modifier.
    "standard.mode_shift": [],
    # §195.2: Awakened One's phase-one guard. No trigger at all: the whole effect is the
    # `DeathPrevention` row, which `resolve_damage` already reads for any combatant (§180).
    "standard.unawakened": [],
    # §195.4: Bronze Orb's Stasis, split in two on purpose -- `standard.stasis` carries the `Downed`
    # hook (returns the stolen card) and `standard.stasis_ready` is the once-per-combat flag that the
    # move spends. One status cannot be both: consuming it would delete the hook.
    "standard.stasis": [],
    "standard.stasis_ready": [],
    # §195.7: Draw Reduction -- the `TurnStartDraw` pipeline, minus one per stack.
    "standard.draw_reduction": [("TurnStartDraw", "AddPerStack", -1, 100, None)],
    # §208: Byrd's Flying -- half damage from **attacks** (`ScalePercent`, which ignores stacks:
    # `ScalePercentPerStack` would halve once per stack) and one stack lost per attack taken.
    "standard.flying": [("DamageReceived", "ScalePercent", 50, 160, "Direct")],
    # §209: Curl Up -- no modifier at all; its whole rule is the `DamageTaken` trigger below.
    "standard.curl_up": [],
    # §213: Hex -- no modifier either; the whole rule is a `CardPlayed` trigger that shuffles a
    # Dazed into the draw pile when the played card is **not** an Attack.
    "standard.hex": [],
    # §210: Intangible -- "all damage becomes 1" is `ClampMax 1` (`min(current, max(0, 1))`), which is
    # the same `amount.min(1)` the kernel used to hardcode before block absorption.
    "standard.intangible": [("DamageReceived", "ClampMax", 1, 200, None)],
    # §199: Berserk -- the first `TurnStartEnergy` row (our own pipeline; +1 energy per stack).
    "standard.berserk": [("TurnStartEnergy", "AddPerStack", 1, 100, None)],
    # §198: Slow -- a `DamageReceived` row with the stack-linear scale (our own operation), plus a
    # `CardPlayed` trigger that grows it. No separate "clear" status: the wiki's "this turn" needs a
    # TurnEnded reset, which the trigger below does.
    # §216: the factor reads `state.cards_played_this_turn`, **not** the stacks. `Slow` resets at
    # end of turn (wiki), and stacks cannot express "present with count 0" here: `modifyStatusStacks`
    # to 0 deletes the instance (reference `StatusEffects.cs:830-838`) and then the `CardPlayed`
    # trigger never fires again.
    "standard.slow": [("DamageReceived", "ScalePercentPerCardPlayedThisTurn", 10, 150, "Direct")],
    # §197: Barricade (permanent) / Blur (one turn) -- both are "block is not cleared", which the
    # host already asks via the `retain_block` **tag**; no kernel rule, just a tag.
    "standard.barricade": [],
    "standard.blur": [],
    # §196: Entangled -- no modifiers at all; the whole rule is the kernel's play validator
    # (`Validator::Entangled`), and the status decays through its own TurnEnded trigger.
    "standard.entangled": [],
    "standard.entangle_ready": [],
}
# Statuses whose stacks decay at the owner's turn end (inv:§10).
INV_DECAYING = {
    # §195.7: one turn -- applied during the enemy's turn, gone by the end of the player's next.
    "standard.draw_reduction",
    # §263: 毒也是"层数就是时钟"（`TurnEnded` 减 1）。
    "standard.poison",
    # §196: "this turn" -- same decay idiom as Weak.
    "standard.entangled","standard.vulnerable", "standard.weak", "standard.frail"}

# =============================================================================
# 2.  helpers
# =============================================================================

PROBLEMS = []

# The five entity tables.  `reader.document()` always emits all five (as lists,
# possibly empty) while the source document may simply not have the key at all;
# so they are compared row by row, never as root keys.
# The document keys the compiler turns into **entity rows** (not root keys). UnknownRooms is the
# ?-room table (EV); the key is named that way because the reference document uses Events for a
# dict of its own shape and ENTITY_SECTIONS is a global mapping.
ROW_TABLES = ("Cards", "Statuses", "EnemyActions", "Encounters", "Relics")


def fail(where, message):
    PROBLEMS.append("%s: %s" % (where, message))


def ok(label, detail=""):
    print("  ok   %-34s %s" % (label, detail))


def die(code, message):
    sys.stderr.write("STS_CONTENT ENV_MISSING\n%s\n" % message)
    raise SystemExit(code)


def rel(path):
    try:
        return os.path.relpath(path, ROOT).replace("\\", "/")
    except ValueError:
        # A path on another drive (e.g. a scratch build passed via --src/--full).
        return path


def show(value, limit=120):
    text = json.dumps(value, ensure_ascii=False, sort_keys=True)
    return text if len(text) <= limit else text[:limit] + "..."


def diff(expected, actual, path="", out=None):
    """Structural diff that is **presence sensitive**.

    A key that exists on only one side is a difference even when the other side
    would read back as "absent" -- that is the whole point of the two sentinels
    in rdcfmt, and it is what makes "the image grew a fact" observable.
    """
    if out is None:
        out = []
    if len(out) >= 25:
        return out
    if type(expected) is not type(actual) and not (
            isinstance(expected, (int, float)) and isinstance(actual, (int, float))):
        out.append("%s: type %s vs %s (%s vs %s)"
                   % (path or "<root>", type(expected).__name__,
                      type(actual).__name__, show(expected), show(actual)))
        return out
    if isinstance(expected, dict):
        for key in sorted(set(expected) | set(actual)):
            sub = "%s.%s" % (path, key) if path else key
            if key not in expected:
                out.append("%s: unexpected key in image (%s)" % (sub, show(actual[key])))
            elif key not in actual:
                out.append("%s: key missing from image (%s)" % (sub, show(expected[key])))
            else:
                diff(expected[key], actual[key], sub, out)
    elif isinstance(expected, list):
        if len(expected) != len(actual):
            out.append("%s: list length %d vs %d"
                       % (path or "<root>", len(expected), len(actual)))
        for index in range(min(len(expected), len(actual))):
            diff(expected[index], actual[index], "%s[%d]" % (path, index), out)
    elif expected != actual:
        out.append("%s: %s vs %s" % (path or "<root>", show(expected), show(actual)))
    return out


def tgt(selector):
    """`TargetSelector` -> a short label.  Unknown selectors raise (never guess)."""
    kind = selector.get("kind")
    mapping = {
        "sel.eventTarget": "event",
        "sel.source": "source",
        # §178: distinct from `source` on purpose -- `sel.source` resolves to the EMPTY set for a
        # downed combatant, so a split on `Downed` must use this one. Two different facts, two
        # different labels; folding them would hide exactly the bug this section fixed.
        "sel.sourceIncludingDowned": "sourceDowned",
        "sel.allEnemies": "allEnemies",
        # §194: the source's **own** team. Every boss buff ("all enemies gain 3 Strength" in the
        # wiki's words) means this one; `allEnemies` is the opposing team and would buff the player.
        "sel.allAllies": "allAllies",
    }
    if kind not in mapping:
        raise AssertionError("unexpected selector kind %r" % kind)
    return mapping[kind]


def _has_dynamic_size(expr):
    """Does this expression tree mention a size the kernel has to read from state?

    Two kinds so far: `card.counter` (§229) and `combatantDefensivePool` (§233). Both make an
    `add`/`multiply` worth unwrapping; anything else stays opaque on purpose.
    """
    if not isinstance(expr, dict):
        return False
    if expr.get("kind") in ("card.counter", "combatantDefensivePool"):
        return True
    value = expr.get("value")
    if isinstance(value, dict):
        return any(_has_dynamic_size(item) for item in value.values())
    if isinstance(value, list):
        return any(_has_dynamic_size(item) for item in value)
    return False


def amount(expr):
    if expr.get("kind") == "const":
        return expr["value"]["Value"]
    if expr.get("kind") == "multiply" and _has_dynamic_size(expr):
        # §233: an `add`/`multiply` that mentions a **dynamic** size (this copy's counter, or a
        # defensive pool) is unwrapped; every other one keeps the old opaque shape (`('expr', ...)`),
        # because rewriting those would churn facts §193/§216 already froze.
        return ("multiply", amount(expr["value"]["Left"]), amount(expr["value"]["Right"]))
    if expr.get("kind") == "card.counter":
        # §229: a size that is **this copy's** counter ("increase this card's damage by 5").
        return ("cardCounter", expr["value"]["CounterId"]["value"])
    if expr.get("kind") == "add" and _has_dynamic_size(expr):
        # §229: an `add` that mentions **this copy's counter** is unwrapped, because "8 + what this
        # card already gained" is a different rule from a generic `add`. Every other `add` keeps the
        # old opaque shape (`('expr', 'add')`) -- unwrapping them all would rewrite facts that §193/
        # §216 already froze, and a check that churns is a check nobody reads.
        return ("add", amount(expr["value"]["Left"]), amount(expr["value"]["Right"]))
    if expr.get("kind") == "combatantDefensivePool":
        # §228: a size that is a **defensive pool** ("equal to your Block"). Spelled with the pool key
        # *and* the selector, so "your Block" and "their Block" cannot compare equal.
        return ("pool", expr["value"]["PoolId"]["value"], tgt(expr["value"]["Selector"]))
    if expr.get("kind") == "combatantCounter":
        # §193: a damage/gain whose size is a **counter**. Spelled with its key *and* the selector,
        # so "the wrong unit's counter" is a visible fact and not an interchangeable number.
        return ("counter", expr["value"]["CounterId"], tgt(expr["value"]["Selector"]))
    return ("expr", expr.get("kind"))


def program_facts(root):
    """Reduce an effect program to the facts it states -- mechanically.

    Any node kind this function does not know raises, so a node type that the
    inventory never mentions cannot sneak into the content unnoticed.  The
    result is compared for **equality** with the expected list: an extra fact is
    a failure ("多余也算失败"), not a pass.
    """
    facts = []

    def walk_into(node, out):
        """收集子树的事实到 `out`（`walk` 的另一种落点，供 forEach 用）。"""
        if not node:
            return
        walk(node, out)

    def walk_into_keep(node):
        """把子树的事实收进**当前**那一层（续延 `walk` 自己的 `out`）。"""
        if node:
            walk(node, current_out[0])

    current_out = [None]

    def walk(node, out=None):
        if out is None:
            out = facts
        current_out[0] = out
        kind = node.get("kind")
        body = node.get("value") or {}
        if kind == "node.sequence":
            for child in body.get("Children") or []:
                walk_into_keep(child)
        elif kind == "node.dealDamage":
            out.append(("damage", amount(body["Amount"]), tgt(body["TargetSelector"])))
        elif kind == "node.heal":
            out.append(("heal", amount(body["Amount"]), tgt(body["TargetSelector"])))
        elif kind == "node.loseHp":
            # §236: "Lose N HP" as a fact. It is **not** damage -- that difference is the whole
            # point (no Block, no modifiers, no "when attacked" hooks), so the fact says so.
            out.append(("loseHp", amount(body["Amount"]), tgt(body["TargetSelector"])))
        elif kind == "node.shuffleDiscardIntoDraw":
            # §243: Deep Breath -- "shuffle your discard pile into your draw pile".
            out.append(("shuffleDiscard", tgt(body["OwnerSelector"])))
        elif kind == "node.playTopCardOfDrawPile":
            # §241: Havoc -- the card is the **top of the draw pile**, so no definition to name;
            # it always ends in the Exhaust pile ("and Exhaust it").
            out.append(("playTopOfDrawPile", "ExhaustPile"))
        elif kind == "node.createRandomCardInstance":
            # §240: "add a random <tag> card" (Infernal Blade). The definition is NOT in the
            # content -- the kernel draws it from the card table at resolve time.
            out.append(("createRandom", body.get("Tag"), body.get("ToZone"),
                        amount(body["Count"]) if "Count" in body else 1,
                        bool(body.get("CostZero"))))
        elif kind == "node.dealDamageAndGainMaxHealthIfFatal":
            # §238: Feed -- damage and, **if that damage killed**, raise the source's Max HP.
            out.append(("damage", amount(body["Amount"]), tgt(body["TargetSelector"])))
            out.append(("ifFatalGainMaxHealth", body["MaxHealthGain"]))
        elif kind == "node.gainMaxHealth":
            # §238: "raise your Max HP by N" (Feed's "If Fatal"). Not a heal: it moves the ceiling.
            out.append(("gainMaxHealth", amount(body["Amount"]), tgt(body["TargetSelector"])))
        elif kind == "node.setDefensivePool":
            # §233: "set the pool to this" as a fact -- **gain** and **set** are different rules, so
            # they are different facts (a `GainBlock`-based Entrench would double *after* modifiers).
            out.append(("setPool", body["PoolId"]["value"], amount(body["Amount"]),
                        tgt(body["TargetSelector"])))
        elif kind == "node.dealDamageAndHealByLoss":
            # §231: "heal what you actually dealt" -- the `HealByLoss` half is part of the fact, or
            # "4 damage to all" and "4 damage to all, healing what it dealt" would compare equal.
            out.append(("damageHealLoss", amount(body["Amount"]), tgt(body["TargetSelector"])))
        elif kind == "node.dealDamageWithTagBonus":
            # §230: "6 damage, +2 per card with this tag" as one fact. The tag and the per-card bonus
            # are both part of it -- that is the whole identity of Perfected Strike.
            out.append(("damagePerTag", amount(body["Amount"]), amount(body["Bonus"]),
                        body["Tag"], tgt(body["TargetSelector"])))
        elif kind == "node.addCardCounter":
            # §229: "this card remembers something about itself" as a fact. The counter's **name** and
            # the delta are both part of it -- two cards that raise different counters must not compare
            # equal, or "Rampage got stronger" and "some other bookkeeping moved" would look the same.
            # §247：`Mode`（`Add` 缺席 / `Set` 覆盖）也是事实的一部分 —— "把价格设成 1" 与
            # "把价格加 1" 在同一个计数器上是两件事。
            # §248：`Mode`（`Add` 缺席 / `Set` / `SetMin`）是事实的一部分 ——
            # "把价格设成 1" 和 "把价格降到至多 1" 在最关键的 0 费牌上结果不同。
            out.append(("cardCounter", body["CardExpression"]["kind"],
                        body["CounterId"]["value"], amount(body["Delta"]),
                        body.get("Mode", "Add")))
        elif kind == "node.dealDamageToRandomTarget":
            # §228: "each hit re-rolls a target" as a fact -- the **count** and the pool are part of
            # it, because "3 hits to random enemies" and "3 hits to all enemies" differ only here.
            out.append(("damageRandom", amount(body["Amount"]), tgt(body["TargetSelector"]),
                        body["Times"]))
        elif kind == "node.gainBlock":
            out.append(("block", amount(body["Amount"]), tgt(body["TargetSelector"])))
        elif kind == "node.applyStatus":
            out.append(("status", body["StatusDefinitionId"]["value"],
                          amount(body["Stacks"]), tgt(body["TargetSelector"])))
        elif kind == "node.createCardInstance":
            out.append(("card", body["CardDefinitionId"]["value"],
                          amount(body["Count"]), body["ToZone"],
                          tgt(body["TargetSelector"])))
        elif kind == "node.setCombatantCounter":
            out.append(("counter", body["CounterId"]["value"], amount(body["Amount"]),
                          body["Relative"], tgt(body["TargetSelector"])))
        elif kind == "node.modifyStatusStacks":
            out.append(("modify", body["StatusDefinitionId"]["value"],
                          amount(body["Delta"]), tgt(body["TargetSelector"])))
        elif kind == "node.forEachCardInZone":
            # §225：Second Wind / Fiend Fire 的"整手牌逐张处理"。事实记成
            # `("each", zone, (循环体的事实...))` —— 递归进一次体，把那些事实收进元组。
            sub = []
            walk_into(body.get("Body"), sub)
            # §248：`Order` / `TakeFirst` 也是事实 —— "手里**每一张**"与"手里**随机一张**"
            # 的差别只在这两个字段上（`Enlightenment` vs `Madness`）。
            out.append(("each", body.get("Zone"), body.get("Order", "PileOrder"),
                        body.get("TakeFirst"), tuple(sub)))
        elif kind == "node.moveCardToZone":
            # §225：把**当前迭代的那张牌**送进消耗堆（Second Wind / Fiend Fire）。
            target = body.get("CardExpression") or {}
            out.append(("move", target.get("kind"), body.get("ToZone")))
        elif kind == "node.drawCards":
            # §221：Pommel Strike / Shrug It Off / Battle Trance 的抽牌。
            out.append(("draw", amount(body["Count"]), tgt(body["TargetSelector"])))
        elif kind in ("node.gainResource", "node.loseResource"):
            # §220: the two halves of "whenever this card is drawn, lose 1 Energy" /
            # "if this card is Exhausted, gain 2 Energy". Recorded as facts so the gate can see them
            # -- this function is the only vocabulary the checker has, and an unknown kind raises.
            words = "gain" if kind == "node.gainResource" else "lose"
            out.append((words, body["ResourceId"], amount(body["Amount"]),
                          tgt(body["TargetSelector"])))
        elif kind == "node.extraTurn":
            out.append(("extraTurn", tgt(body["TargetSelector"])))
        elif kind == "node.endTurn":
            out.append(("endTurn",))
        elif kind == "node.destroyCombatant":
            # §178: the other half of a split. Recorded as a fact, not ignored -- "the boss is
            # replaced" is exactly the thing the old content got wrong.
            out.append(("destroy", tgt(body["TargetSelector"])))
        elif kind == "node.carryAwayStolenGold":
            # §201: "flees with your gold" -- which counter is carried away, and from whom.
            out.append(("carry", body["CounterId"]["value"], tgt(body["TargetSelector"])))
        elif kind == "node.createCombatant":
            out.append(("spawn", body["DefinitionId"], amount(body["Health"]) if body.get("Health") else 0))
        elif kind == "node.conditional":
            # A conditional states the facts of **both** branches, tagged with the condition, so the
            # inventory cannot hide a branch behind an `if` (port-plan.md §118).
            cond = body["Condition"]
            key = cond.get("value", {}).get("FieldKey")
            for branch in ("Then", "Else"):
                sub = body.get(branch)
                if sub:
                    before = len(facts)
                    walk_into_keep(sub)
                    facts[before:] = [("when", key) + f for f in facts[before:]]
        elif kind == "node.upgradeCards":
            # §195.7: "upgrade every <id>" -- which definition, and where.
            # §227: `CardDefinitionId` is optional now -- absent = "the whole zone" (Armaments+).
            # `None` in the fact is what keeps "upgrade one definition" and "upgrade everything in
            # hand" from ever comparing equal.
            definition = body.get("CardDefinitionId")
            out.append(("upgrade", tgt(body["OwnerSelector"]),
                          definition["value"] if definition else None,
                          body.get("FromZone"), body.get("Count")))
        elif kind == "node.selectCards":
            # §195.4: "pick which card" as a fact. Every field that decides *which* card is part of
            # the fact, because "steal the best card" and "steal the first card" differ only here.
            out.append(("select", tgt(body["OwnerSelector"]), body["FromZone"],
                          body.get("FallbackZone"), body["Order"],
                          # `Count` is a plain int field on this node (not an expression).
                          body["Count"], body["ToZone"]))
        elif kind == "node.chooseCards":
            # §226/§227: "ask the player which cards, then do X to them" as one fact. **Every** field
            # that decides the question is part of it -- "an Attack or Power" vs "any card" vs "only
            # cards with a `+` row" is exactly the difference between these cards.
            then = body["Then"]
            extra = ()
            if then == "Copy":
                extra = (body.get("ToZone", "Hand"), body["Copies"])
            # §246：`DrawFirst` 是节点内部的一次抽牌 —— 事实必须写出来，否则"抽 1 张"
            # 会从对账表里消失，而它正是 Warcry / Thinking Ahead 的第一句。
            if body.get("DrawFirst"):
                out.append(("draw", body["DrawFirst"], tgt(body["OwnerSelector"])))
            out.append(("choose", tgt(body["OwnerSelector"]), body["FromZone"],
                          tuple(body.get("RequireAnyTag") or ()),
                          body["Min"], body["Max"], then) + extra)
        elif kind == "node.dealDamageAndIfFatal":
            # §250: "deal N damage, and if that killed, do X". The fatal branch is a **sub-program**,
            # so its facts are tagged `fatal` -- "deal 15 and grow" vs "deal 15" must never compare
            # equal (that is exactly the Ritual Dagger / Hand of Greed shape).
            before = len(facts)
            walk(body["Program"])
            fatal_facts = facts[before:]
            del facts[before:]
            if body.get("IgnoresBlock"):
                out.append(("damageIgnoresBlock", tgt(body["TargetSelector"]),
                            amount(body["Amount"])))
            else:
                out.append(("damage", amount(body["Amount"]), tgt(body["TargetSelector"])))
            facts.extend(("fatal",) + f for f in fatal_facts)
        elif kind == "node.playCard":
            # §253: "play that card **through the full pipeline**" (`Wish`). `IgnoreUnplayable` is
            # part of the fact: "play it even though it is unplayable" and "play it only if it is
            # playable" are two different content promises.
            out.append(("playCard", tgt(body["PlayerSelector"]),
                        body.get("IgnoreUnplayable", False)))
        elif kind == "node.offerCards":
            # §254: "offer these exact cards, and the pick is played at once" (`Wish`). The
            # **list** is the fact: which three cards, in which order, is the whole card.
            out.append(("offerList", tuple(body.get("Definitions") or ()),
                        body.get("Min", 1), body.get("Max", 1),
                        body.get("Then", "ToHandFree")))
        elif kind == "node.gainGold":
            # §250: gold **inside** a fight (`Hand of Greed`). A fact of its own: the run's gold is
            # not a combat resource, so it must not be folded into `gain`.
            out.append(("gold", amount(body["Amount"])))
        elif kind == "node.createCardCopy":
            # §250: "a copy of **this** card" (Pride / Necronomicurse). `CardDefinitionId` is part of
            # the fact because it is the **only** thing that decides *which* card is copied --
            # leaving it out lets two different cards read as the same content (§250's first gate).
            out.append(("copySelf", body.get("CardDefinitionId"), body["ToZone"],
                        body.get("Placement", "Bottom"), body.get("Count", 1)))
        elif kind == "node.offerRandomCards":
            # §250: "offer N of the class pool, pick one, it arrives free" (`Discovery`). The `then`
            # is fixed by the node (`ToHandFree`), so it is spelled out in the fact -- a second
            # consumer with a different `then` would have to change this line too.
            out.append(("offer", body.get("Count", 3), body.get("Min", 1),
                        body.get("Max", 1), "ToHandFree"))
        elif kind == "node.repeat":
            # §146: the body runs an unknown-at-authoring number of times, so its facts are tagged
            # by **the count expression** rather than unrolled. That keeps the inventory honest
            # ("this card deals 5 damage to all enemies *per X*") and keeps the walker total: a
            # repeat that hid its body would be the same failure as an unknown node kind.
            before = len(facts)
            walk(body["Body"])
            facts[before:] = [("repeat", amount(body["Count"])) + f for f in facts[before:]]
        else:
            raise AssertionError("unexpected node kind %r" % kind)

    walk(root)
    return facts


def split_history(facts):
    """Peel the `prev_move = last_move; last_move = k` pair off a fact list.

    §195.5: "which move did I just use" is **content state** (a counter pair at the end of every
    action program), and every boss that draws by weight needs it. Keeping those two facts out of
    `INV_ACTIONS` is deliberate: that table is the independent copy of the **wiki's numbers**, and a
    bookkeeping counter is not a wiki number. The bookkeeping is checked structurally instead, by
    `check_intent_history`, which can say things a per-action table cannot ("the code a rule asks
    about must be written by some action").
    """
    if len(facts) >= 2:
        prev, last = facts[-2], facts[-1]
        is_prev = (prev[0] == "counter" and prev[1] == "prev_move"
                   and isinstance(prev[2], tuple) and prev[2] == ("counter", "last_move", "source"))
        is_last = (last[0] == "counter" and last[1] == "last_move"
                   and isinstance(last[2], int) and last[3] is False)
        if is_prev and is_last:
            return facts[:-2], last[2]
    return facts, None


def load_programs(doc):
    """id -> the program root, for cards and enemy actions."""
    out = {}
    for rec in doc.get("Cards") or []:
        out["card:" + rec["Id"]] = rec["Program"]["Root"]
    for rec in doc.get("EnemyActions") or []:
        out["action:" + rec["Id"]] = rec["Program"]["Root"]
    return out


# =============================================================================
# 3.  the checks
# =============================================================================

def check_preconditions():
    print("[0] preconditions")
    for path in (SRC_PATH, FULL_PATH, CORE_PATH):
        if not os.path.exists(path):
            die(2, "missing %s -- run: python tools/contentc/build.py --package sts"
                % rel(path))
    src_mtime = os.path.getmtime(SRC_PATH)
    for path in (FULL_PATH, CORE_PATH):
        if os.path.getmtime(path) + 1e-6 < src_mtime:
            die(2, "%s is OLDER than %s -- the image is stale; run: "
                   "python tools/contentc/build.py --package sts"
                % (rel(path), rel(SRC_PATH)))
    for path in (SRC_PATH, FULL_PATH, CORE_PATH):
        ok("present + fresh", "%s (%d B)" % (rel(path), os.path.getsize(path)))


def check_quantities(doc):
    print("[1] quantities (from inv:§1 / §2 / §3.3 / §5.2 / §10)")
    got = {
        "monsters": len(doc.get("Monsters") or []),
        "encounters": len(doc.get("Encounters") or []),
        "deck": len((doc.get("Start") or {}).get("Deck") or []),
        "statuses": len(doc.get("Statuses") or []),
    }
    for name, want in sorted(INV_COUNTS.items()):
        if got[name] != want:
            fail("quantity." + name, "content has %d, inv says %d" % (got[name], want))
    # inv:§1 "25 个敌人实体" is the whole act; this milestone authors the
    # zero-new-ability tier only (plan §3.3: 10/25).
    ok("counts", "monsters=%d encounters=%d deck=%d statuses=%d cards=%d actions=%d"
       % (got["monsters"], got["encounters"], got["deck"], got["statuses"],
          len(doc.get("Cards") or []), len(doc.get("EnemyActions") or [])))

    # The roster must be exactly the inventory's tier-A list.
    roster_ids = sorted(m["Id"] for m in doc.get("Monsters") or [])
    inv_ids = sorted(m[0] for m in INV_MONSTERS)
    if roster_ids != inv_ids:
        fail("roster.ids", "roster %s != inv %s" % (roster_ids, inv_ids))
    # Both pools: the weak one (`inv:§5.2`) and the elite one (`inv:§5.3`).
    declared = sorted(set(INV_WEAK_POOL) | set(INV_ELITE_POOL) | set(INV_BOSS_POOL))
    if sorted(doc.get("Encounters") and [e["Id"]["Value"] for e in doc["Encounters"]]) \
            != declared:
        fail("encounters.ids", "encounter ids %s != inv %s"
             % (sorted(e["Id"]["Value"] for e in doc["Encounters"]),
                declared))
    if sorted(s["Id"] for s in doc.get("Statuses") or []) != sorted(INV_STATUSES):
        fail("statuses.ids", "%s != %s"
             % (sorted(s["Id"] for s in doc["Statuses"] or []), sorted(INV_STATUSES)))
    if sorted(c["Id"] for c in doc.get("Cards") or []) != sorted(INV_CARDS):
        fail("cards.ids", "%s != %s"
             % (sorted(c["Id"] for c in doc.get("Cards") or []), sorted(INV_CARDS)))
    if sorted(a["Id"] for a in doc.get("EnemyActions") or []) != sorted(INV_ACTIONS):
        fail("actions.ids", "%s != %s"
             % (sorted(a["Id"] for a in doc.get("EnemyActions") or []),
                sorted(INV_ACTIONS)))
    ok("id sets match inv", "roster/encounters/statuses/cards/actions")


def check_monsters(doc):
    print("[2] monster numbers (inv:§4.1)")
    by_id = {m["Id"]: m for m in doc.get("Monsters") or []}
    for mid, hp_min, hp_max, actions in INV_MONSTERS:
        entry = by_id.get(mid)
        if entry is None:
            fail("monster." + mid, "not in the roster")
            continue
        if (entry.get("HpMin"), entry.get("HpMax")) != (hp_min, hp_max):
            fail("monster." + mid, "HP range %s-%s, inv says %d-%d"
                 % (entry.get("HpMin"), entry.get("HpMax"), hp_min, hp_max))
        # The kernel's FightPlan has one integer (battle.rs:121-134), so the
        # content pins the range's lower bound; that choice is in Notes.Deviations.
        if entry.get("MaxHealth") != hp_min:
            fail("monster." + mid, "MaxHealth %r, expected the HpMin stand-in %d"
                 % (entry.get("MaxHealth"), hp_min))
        got_actions = [a["value"] for a in entry.get("Actions") or []]
        if got_actions != actions:
            fail("monster." + mid, "actions %s, inv says %s" % (got_actions, actions))
    # The roster is the authored source for every enemy, so the action count must
    # equal the number of distinct actions the inventory lists.
    total = sum(len(m[3]) for m in INV_MONSTERS)
    ok("roster numbers", "%d monsters, %d action references" % (len(INV_MONSTERS), total))
    check_intent_rules(doc)


# §148: the intent-rule vocabulary (`intent.rs::ConditionKind`) and its operators.
INTENT_CONDITIONS = ("intent.healthPercent", "intent.round", "intent.selfHasStatus",
                     "intent.opponentHasStatus", "intent.selfHasCounter", "intent.selfResource",
                     "intent.opponentCardsPlayed", "intent.allOf", "intent.anyOf", "intent.not",
                     # §187 / §257：本移植自己的两条。`ascensionAtLeast` 早就在用，清单里一直
                     # 漏着 —— 这条清单是"内核认识哪些条件"的副本，漏一条就等于给内容开了个
                     # 不受检的口子。
                     "intent.ascensionAtLeast", "intent.enemyAliveCount")
INTENT_OPS = ("Equal", "NotEqual", "Less", "LessOrEqual", "Greater", "GreaterOrEqual")


def check_intent_rules(doc):
    """§148: every `IntentRules` entry must be **executable**.

    The kernel reads a rule as `(Condition, Action, Priority)`; a condition kind it does not know is a
    loud error at intent time, and an `Action` that is not an `EACT` row is `UnknownAction` — both
    *after* the player is already in the fight. Worse: a rule that silently never matches falls back
    to the `Actions` **cycle**, which looks like a working enemy with a slightly different rhythm.
    So the shape is checked here, where the message can name the enemy.

    An action named by a rule need **not** be in the enemy's `Actions` list: that is exactly how a
    "turn 1 only" opener is expressed (Spire Growth's `Strategic`).
    """
    print("[2b] enemy intent rules (port-plan.md §148)")
    actions = {a["Id"] for a in doc.get("EnemyActions") or []}
    checked = 0

    def walk(where, rules):
        nonlocal checked
        for index, rule in enumerate(rules or []):
            label = "%s.IntentRules[%d]" % (where, index)
            condition = rule.get("Condition") or {}
            kind = condition.get("kind")
            if kind not in INTENT_CONDITIONS:
                fail(label, "condition kind %r is outside the kernel's 10" % (kind,))
            # Every operator-bearing condition must name a known `Op` — the kernel throws on an
            # unknown one, so a typo is a mid-fight error rather than a different rhythm.
            if kind not in ("intent.allOf", "intent.anyOf", "intent.not"):
                op = (condition.get("value") or {}).get("Op")
                if op is not None and op not in INTENT_OPS:
                    fail(label, "Op %r is outside the kernel's 6" % (op,))
            # §195.3: a rule names either one `Action` or a weighted `Choice` list. Both halves are
            # checked, and "both at once" is an error -- the kernel refuses that combination rather
            # than picking one (two answers for one condition has no correct reading).
            single = (rule.get("Action") or {}).get("value")
            choice = rule.get("Choice")
            if single is not None and choice is not None:
                fail(label, "has both `Action` and `Choice`")
            elif single is not None:
                if single not in actions:
                    fail(label, "Action %r is not an EACT row" % (single,))
            elif choice is not None:
                if not isinstance(choice, list) or not (1 <= len(choice) <= 8):
                    fail(label, "Choice must be a list of 1..=8 options (%r)" % (choice,))
                else:
                    total = 0
                    for option in choice:
                        if set(option) != {"Action", "Weight"}:
                            fail(label, "Choice option keys %r" % (sorted(option),))
                            continue
                        weight = option["Weight"]
                        if not isinstance(weight, int) or weight <= 0:
                            fail(label, "Choice weight %r is not a positive int" % (weight,))
                        else:
                            total += weight
                        target = (option.get("Action") or {}).get("value")
                        if target not in actions:
                            fail(label, "Choice option %r is not an EACT row" % (target,))
                    if total > 255:
                        fail(label, "Choice weights total %d > 255 (the pick index is a u8)" % total)
            else:
                fail(label, "names neither `Action` nor `Choice`")
            if not isinstance(rule.get("Priority"), int):
                fail(label, "Priority must be an integer, got %r" % (rule.get("Priority"),))
            checked += 1

    for monster in doc.get("Monsters") or []:
        walk("Monster." + monster.get("Id", "?"), monster.get("IntentRules"))
    for encounter in doc.get("Encounters") or []:
        for enemy in encounter.get("Enemies") or []:
            # The encounter's inline record is what the kernel reads; the roster copy is
            # documentation. They must agree, and the gate compares them below.
            walk("Encounter.%s./%s" % (encounter.get("Id", {}).get("Value"), enemy.get("Id")),
                 enemy.get("IntentRules"))
            roster = next((m for m in doc.get("Monsters") or []
                           if m.get("Id") == enemy.get("Id")), None)
            if roster is not None and (roster.get("IntentRules") or []) != (enemy.get("IntentRules") or []):
                fail("Encounter.%s./%s" % (encounter.get("Id", {}).get("Value"), enemy.get("Id")),
                     "the inline IntentRules differ from the roster's copy")
    ok("intent rules", "%d rule(s), all conditions/actions/priorities resolvable" % checked)


def check_cards_and_actions(doc):
    print("[3] card / enemy-action numbers (inv:§2.1, §3.1, §4.1)")
    programs = load_programs(doc)
    cards = {c["Id"]: c for c in doc.get("Cards") or []}
    # ---- §249：**内容用到的每个表达式 kind，内核都求值得出来吗** --------------
    #
    # 这一条是 §249 的教训：`remainder` 在 `INT_KINDS` 表里有、能写进内容、能过其它
    # 所有检查，但内核**没实现**它 ⇒ 只有玩到那张牌时才炸（`UnsupportedKind`）。
    # 判据从 `expr.rs` 源码里抽（表 = 声明、match 分支 = 已实现），所以**新增一张牌就自动
    # 被覆盖**，不需要维护第二份清单。
    tables = audit.kind_tables()
    _, done = audit.implemented()
    unsupported = set()
    for names in tables.values():
        unsupported |= names - done
    used = audit.content_kinds()
    bad = {}
    for kind, owner in used:
        if kind.startswith("node.") or kind.startswith("sel."):
            continue
        if kind in unsupported:
            bad.setdefault(kind, set()).add(owner)
    for kind, owners in sorted(bad.items()):
        fail("program." + sorted(owners)[0],
             "uses kind %r which expr.rs does not evaluate (UnsupportedKind)" % kind)
    ok("programs", "%d kind(s) used, all implemented"
       % len({k for k, _ in used}))
    for cid, spec in INV_CARDS.items():
        card = cards.get(cid)
        if card is None:
            fail("card." + cid, "missing")
            continue
        costs = card.get("Costs") or []
        got_cost = costs[0]["Amount"] if costs else 0
        if got_cost != spec["Cost"]:
            fail("card." + cid, "cost %r, inv says %d" % (got_cost, spec["Cost"]))
        got_tags = [t["value"] for t in card.get("Tags") or []]
        if got_tags != spec["Tags"]:
            fail("card." + cid, "tags %s, inv says %s" % (got_tags, spec["Tags"]))
        if costs and costs[0]["ResourceId"]["value"] != "standard.energy":
            fail("card." + cid, "cost resource %r" % costs[0]["ResourceId"])
        got = program_facts(card["Program"]["Root"])
        if got != _tuples(spec["Facts"]):
            fail("card." + cid, "facts %s, inv says %s" % (got, spec["Facts"]))
    actions = {a["Id"]: a for a in doc.get("EnemyActions") or []}
    for aid, (intent, facts) in INV_ACTIONS.items():
        action = actions.get(aid)
        if action is None:
            fail("action." + aid, "missing")
            continue
        if (action.get("Intent") or {}).get("Kind") != intent:
            fail("action." + aid, "intent %r, inv says %r"
                 % ((action.get("Intent") or {}).get("Kind"), intent))
        got, _code = split_history(program_facts(action["Program"]["Root"]))
        if got != facts:
            fail("action." + aid, "facts %s, inv says %s" % (got, facts))
    ok("cards", "%d cards x (cost, tags, facts)" % len(INV_CARDS))
    ok("enemy actions", "%d actions x (intent, facts)" % len(INV_ACTIONS))
    check_intent_history(doc)
    check_time_variables(doc)
    # §219：落区是**枚举名**（`zone_from_wire_name`），写错一个词 = 这张牌一打就抛。
    ok("card zones", "%d zone cells x 7 known names" % check_card_zones(doc))
    # §220：`CARD.LifecyclePrograms` 的键与事实（`Drawn` / `Exhausted` 是这一节新加的）。
    ok("card lifecycle", "%d program(s) x (event key, facts)" % check_card_lifecycle(doc))
    ok("card wiki", "%d cards x (type, rarity, cost, keywords, facts)" % check_card_wiki(doc))
    check_ascension_variants(doc)
    check_ascension_health(doc)
    check_starting_status_ascension(doc)
    check_spawn_rolls(doc)


# §187：`EACT.ProgramAsc` 的**独立第二份**。每一行都是 wiki 的数字（出处列在
# `native/patch_187_content.py` 的表头），而不是从内容拄过来的 --
# "从内容生成期望值"等于没有期望值。
INV_ASC_VARIANTS = {
    # action id: [(AscensionMin, facts), ...] —— §192 起是**列表**：一个动作可以有两个档位
    # （`jaw_worm.bellow` 的 Strength 在 A2 升、Block 在 A17 升）。单档位的动作仍然只写一项。
    # 每一行都是 wiki 的数字；出处见 `native/wiki_asc/<monster>.txt`。
    'acid_slime_m.corrosive_spit': [(2, [('damage', 8, 'event'), ('card', 'slimed', 1, 'DiscardPile', 'event')])],
    'acid_slime_m.tackle': [(2, [('damage', 12, 'event')])],
    'acid_slime_s.tackle': [(2, [('damage', 4, 'event')])],
    'blue_slaver.rake': [(2, [('damage', 8, 'event'), ('status', 'standard.weak', 1, 'event')]),
                        (17, [('damage', 8, 'event'), ('status', 'standard.weak', 2, 'event')])],
    'blue_slaver.stab': [(2, [('damage', 13, 'event')])],
    'book_of_stabbing.big_stab': [(3, [('damage', 24, 'event'),
                                      ('counter', 'book_stab_uses',
                                       ('counter', 'book_stab_single_bump', 'source'), True, 'source')])],
    'book_of_stabbing.multi_stab': [(3, [('repeat', ('expr', 'add'), 'damage', 7, 'event'), ('counter', 'book_stab_uses', 1, True, 'source')])],
    'byrd.peck': [(2, [('damage', 1, 'event'), ('damage', 1, 'event'), ('damage', 1, 'event'), ('damage', 1, 'event'), ('damage', 1, 'event'), ('damage', 1, 'event')])],
    'byrd.swoop': [(2, [('damage', 14, 'event')])],
    # §204: wiki `Thieves` -- Looter's Mug 10 (A2: 11) and Lunge 12 (A2: 14). Thievery itself has an
    # A17 row (15 -> 20) but `EACT` still has no ascension column, so the **steal** stays 15 (the
    # note is in the monster's `AiNote`); only the damage moves here.
    # §205: Thievery 15 -> A17: 20. A variant is a **whole program**, so the A17 row has to carry the
    # A2 damage bump as well -- otherwise A17 would *lose* it (the picker takes the largest
    # threshold, not a stack of deltas).
    'looter.mug': [(2, [('damage', 11, 'event'),
                        ('counter', 'stolen_gold', 15, True, 'source')]),
                   (17, [('damage', 11, 'event'),
                         ('counter', 'stolen_gold', 20, True, 'source')])],
    'looter.lunge': [(2, [('damage', 14, 'event'),
                          ('counter', 'stolen_gold', 15, True, 'source')]),
                     (17, [('damage', 14, 'event'),
                           ('counter', 'stolen_gold', 20, True, 'source')])],
    # §211: `It Is Time` 的基数在计数器里（30 / A3 40），所以 A3 那一行只动**上限**：60 → 70。
    'giant_head.it_is_time': [(3, [('damage', ('counter', 'it_is_time_damage', 'source'), 'event'),
                                   ('when', None, 'counter', 'it_is_time_damage', 70, False, 'source'),
                                   ('when', None, 'counter', 'it_is_time_damage', 5, True, 'source')])],
    # §212: wiki `The Maw` -- Roar 3/3 -> A17 5/5, Slam 25 -> A2 30, Drool 3 -> A17 5.
    'maw.roar': [(17, [('status', 'standard.weak', 5, 'event'),
                       ('status', 'standard.frail', 5, 'event')])],
    'maw.slam': [(2, [('damage', 30, 'event')])],
    'maw.drool': [(17, [('status', 'standard.strength', 5, 'source')])],
    # §213: wiki `Chosen` -- Poke 5x2 -> A2 6x2, Debilitate 10 -> A2 12, Zap 18 -> A2 21.
    'chosen.poke': [(2, [('damage', 6, 'event'), ('damage', 6, 'event')])],
    'chosen.debilitate': [(2, [('damage', 12, 'event'),
                               ('status', 'standard.vulnerable', 2, 'event')])],
    'chosen.zap': [(2, [('damage', 21, 'event')])],
    # §214: wiki `Shapes#Spiker` -- Attack 7 -> A2 9.
    'spiker.cut': [(2, [('damage', 9, 'event')])],
    # §214: wiki `Spire Growth` -- Constrict 10 -> A2 12, Quick Tackle 16 -> A2 18, Smash 22 -> A2 25.
    'spire_growth.strategic': [(2, [('status', 'standard.constricted', 12, 'event')])],
    'spire_growth.aggressive': [(2, [('damage', 18, 'event')])],
    'spire_growth.aggressive_heavy': [(2, [('damage', 25, 'event')])],
    # §204: wiki `Lagavulin` -- Siphon Soul -1/-1 (A18: -2/-2).
    'lagavulin.siphon_soul': [(18, [('modify', 'standard.strength', -2, 'event'),
                                    ('modify', 'standard.dexterity', -2, 'event'),
                                    ('counter', 'lagavulin_step', ('expr', 'remainder'),
                                     False, 'source')])],
    'chosen.debilitate': [(2, [('damage', 12, 'event'), ('status', 'standard.vulnerable', 2, 'event')])],
    'chosen.poke': [(2, [('damage', 6, 'event'), ('damage', 6, 'event')])],
    'cultist.incantation': [(2, [('status', 'ritual', 4, 'source')])],
    'darkling.chomp': [(2, [('damage', 9, 'event'), ('damage', 9, 'event')])],
    'fat_gremlin.smash': [(2, [('damage', 5, 'event'), ('status', 'standard.weak', 1, 'event')])],
    'fungi_beast.grow': [(2, [('status', 'standard.strength', 4, 'source')])],
    'gremlin_nob.bellow': [(18, [('status', 'standard.strength', 3, 'source')])],
    'gremlin_nob.rush': [(3, [('damage', 16, 'event')])],
    'gremlin_nob.skull_bash': [(3, [('damage', 8, 'event'), ('status', 'standard.vulnerable', 2, 'event')])],
    'gremlin_wizard.ultimate_blast': [(2, [('damage', 30, 'event'), ('counter', 'gremlin_wizard_charges', 0, False, 'source')])],
    'jaw_worm.bellow': [
        (2, [('status', 'standard.strength', 4, 'source'), ('block', 6, 'source')]),
        (17, [('status', 'standard.strength', 5, 'source'), ('block', 9, 'source')]),
    ],
    'jaw_worm.chomp': [(2, [('damage', 12, 'event')])],
    'lagavulin.attack': [(3, [('damage', 20, 'event'),
                              ('counter', 'lagavulin_step', ('expr', 'remainder'), False,
                               'source')])],
    'louse_red.grow': [(17, [('status', 'standard.strength', 4, 'source')])],
    'nemesis.tri_attack': [(3, [('damage', 7, 'event'), ('damage', 7, 'event'), ('damage', 7, 'event')])],
    'nemesis.tri_burn': [(18, [('card', 'burn', 5, 'DiscardPile', 'event')])],
    'orb_walker.claw': [(2, [('damage', 16, 'event')])],
    'orb_walker.laser': [(2, [('damage', 11, 'event'), ('status', 'standard.weak', 2, 'event')])],
    'reptomancer.big_bite': [(3, [('damage', 34, 'event')])],
    'reptomancer.snake_strike': [(3, [('damage', 16, 'event'), ('damage', 16, 'event'), ('status', 'standard.weak', 1, 'event')])],
    'reptomancer.spawn_dagger': [(18, [('spawn', 'dagger', 22), ('spawn', 'dagger', 22)])],
    'sentry.beam': [(3, [('damage', 10, 'event')])],
    'sentry.bolt': [(18, [('card', 'dazed', 3, 'DiscardPile', 'event')])],
    'shelled_parasite.double_strike': [(2, [('damage', 7, 'event'), ('damage', 7, 'event')])],
    'shelled_parasite.suck': [(2, [('damage', 12, 'event'), ('block', 2, 'source')])],
    'slaver_red.scrape': [(2, [('damage', 9, 'event'), ('status', 'standard.vulnerable', 1, 'event')]),
                          (17, [('damage', 9, 'event'), ('status', 'standard.vulnerable', 2, 'event')])],
    'slaver_red.stab': [(2, [('damage', 14, 'event')])],
    'slime_boss.goop_spray': [(19, [('card', 'slimed', 5, 'DiscardPile', 'event')])],
    'slime_boss.slam': [(4, [('damage', 38, 'event')])],
    'sneaky_gremlin.puncture': [(2, [('damage', 10, 'event')])],
    'spike_slime_m.flame_tackle': [(2, [('damage', 10, 'event'), ('card', 'slimed', 1, 'DiscardPile', 'event')])],
    'spike_slime_s.tackle': [(2, [('damage', 6, 'event')])],
    'spiker.cut': [(2, [('damage', 9, 'event')])],
    'spire_growth.aggressive': [(2, [('damage', 18, 'event')])],
    'spire_growth.aggressive_heavy': [(2, [('damage', 25, 'event')])],
    'spire_growth.strategic': [(2, [('status', 'standard.constricted', 12, 'event')])],
    'taskmaster.scouring_whip': [(3, [('damage', 7, 'event'), ('card', 'wound', 2, 'DiscardPile', 'event')])],
    'the_champ.heavy_slash': [(4, [('damage', 18, 'event')])],
    # ================= §194 =================
    # The Guardian (wiki: Fierce Bash 32->A4 36, Roll Attack 9->A4 10, Sharp Hide 3->A19 4).
    'the_guardian.fierce_bash': [(4, [('damage', 36, 'event')])],
    'the_guardian.roll_attack': [(4, [('damage', 10, 'event'),
                                      ('counter', 'guard_step', 1, False, 'source')])],
    'the_guardian.defensive_mode': [(19, [('block', 20, 'source'),
                                          ('status', 'standard.sharp_hide', 4, 'source'),
                                          ('counter', 'mode_shift_budget', 10, True, 'source'),
                                          ('counter', 'guard_mode', 1, False, 'source'),
                                          ('counter', 'guard_step', 0, False, 'source')])],
    # Hexaghost (Sear 1 Burn->A19 2, Tackle 5x2->A4 6x2, Inflame 2 Str->A19 3, Inferno 2x6->A4 3x6).
    'hexaghost.sear': [(19, [('damage', 6, 'event'),
                             ('card', 'burn', 2, 'DiscardPile', 'event')])],
    'hexaghost.tackle': [(4, [('damage', 6, 'event'), ('damage', 6, 'event')])],
    'hexaghost.inflame': [(19, [('block', 12, 'source'),
                                ('status', 'standard.strength', 3, 'source')])],
    'hexaghost.inferno': [(4, [('damage', 3, 'event'), ('damage', 3, 'event'),
                               ('damage', 3, 'event'), ('damage', 3, 'event'),
                               ('damage', 3, 'event'), ('damage', 3, 'event'),
                               ('card', 'burn+', 3, 'DiscardPile', 'event'),
                               ('upgrade', 'event', 'burn', None, None)])],
    # The Champ (Face Slap 12->A4 14, Gloat 2->A4 3->A19 4, Anger 6->A4 9->A19 12,
    # Defensive Stance 15/5 ->A9 18/6 ->A19 20/7).
    'the_champ.face_slap': [(4, [('damage', 14, 'event'),
                                 ('status', 'standard.frail', 2, 'event'),
                                 ('status', 'standard.vulnerable', 2, 'event')])],
    'the_champ.gloat': [(4, [('status', 'standard.strength', 3, 'source')]),
                        (19, [('status', 'standard.strength', 4, 'source')])],
    'the_champ.anger': [(4, [('modify', 'standard.weak', -99, 'source'),
                             ('modify', 'standard.vulnerable', -99, 'source'),
                             ('modify', 'standard.frail', -99, 'source'),
                             ('status', 'standard.strength', 9, 'source'),
                             ('counter', 'champ_phase', 1, False, 'source'),
                             ('counter', 'champ_exec', 0, False, 'source')]),
                        (19, [('modify', 'standard.weak', -99, 'source'),
                              ('modify', 'standard.vulnerable', -99, 'source'),
                              ('modify', 'standard.frail', -99, 'source'),
                              ('status', 'standard.strength', 12, 'source'),
                              ('counter', 'champ_phase', 1, False, 'source'),
                              ('counter', 'champ_exec', 0, False, 'source')])],
    'the_champ.defensive_stance': [(9, [('block', 18, 'source'),
                                        ('status', 'standard.metallicize', 6, 'source')]),
                                   (19, [('block', 20, 'source'),
                                         ('status', 'standard.metallicize', 7, 'source')])],
    # Bronze Automaton (Flail 7x2->A4 8x2, Boost Str 3->A4 4 and Block 9->A9 12, HYPER BEAM 45->A4 50).
    'bronze_automaton.flail': [(4, [('damage', 8, 'event'), ('damage', 8, 'event')])],
    'bronze_automaton.boost': [(4, [('status', 'standard.strength', 4, 'source'),
                                    ('block', 9, 'source')]),
                               (9, [('status', 'standard.strength', 4, 'source'),
                                    ('block', 12, 'source')])],
    'bronze_automaton.hyper_beam': [(4, [('damage', 50, 'event')])],
    # The Collector (Fireball 18->A4 21, Buff Str 3->A4 4->A19 5 and Block 15->A9 18->A19 23,
    # Mega Debuff 3/3/3 ->A19 5/5/5).
    'the_collector.fireball': [(4, [('damage', 21, 'event')])],
    'the_collector.buff': [(4, [('status', 'standard.strength', 4, 'allAllies'),
                                ('block', 15, 'source')]),
                           (9, [('status', 'standard.strength', 4, 'allAllies'),
                                ('block', 18, 'source')]),
                           (19, [('status', 'standard.strength', 5, 'allAllies'),
                                 ('block', 23, 'source')])],
    'the_collector.mega_debuff': [(19, [('status', 'standard.weak', 5, 'event'),
                                        ('status', 'standard.vulnerable', 5, 'event'),
                                        ('status', 'standard.frail', 5, 'event')])],
    # Time Eater (Reverberate 7x3->A4 8x3, Head Slam +2 Slimed at A19, Ripple +Frail at A19).
    'time_eater.reverberate': [(4, [('damage', 8, 'event'), ('damage', 8, 'event'),
                                    ('damage', 8, 'event')])],
    'time_eater.head_slam': [(4, [('damage', 32, 'event'),
                                 ('status', 'standard.draw_reduction', 1, 'event')]),
                             (19, [('damage', 32, 'event'),
                                   ('card', 'slimed', 2, 'DiscardPile', 'event'),
                                   ('status', 'standard.draw_reduction', 1, 'event')])],
    'time_eater.ripple': [(19, [('block', 20, 'source'),
                                ('status', 'standard.weak', 1, 'event'),
                                ('status', 'standard.vulnerable', 1, 'event'),
                                ('status', 'standard.frail', 1, 'event')])],
    # Donu / Deca (Beam 10x2->A4 12x2 both; Square of Protection +3 Plated Armor at A19).
    'time_eater.haste': [(19, [('heal', ('expr', 'max'), 'source'),
                               ('block', 32, 'source'),
                               ('counter', 'te_haste', 1, False, 'source')])],
    'donu.beam': [(4, [('damage', 12, 'event'), ('damage', 12, 'event')])],
    'deca.beam': [(4, [('damage', 12, 'event'), ('damage', 12, 'event'),
                       ('card', 'dazed', 2, 'DiscardPile', 'event')])],
    'deca.square_of_protection': [(19, [('block', 16, 'allAllies'),
                                        ('status', 'standard.plated_armor', 3, 'allAllies')])],
}


# §193: the wiki's damage ranges, as an **independent second copy**.
#
#   native/wiki_asc/louse.txt:28      Deals N damage. N between (5-7;{{Asc|2|6-8}}), chosen at the
#                                     start of combat.
#   native/wiki_asc/darkling.txt:32   Deals N damage. N between (7-11;{{Asc|2|9-13}}), chosen at
#                                     the start of combat.
#
# enemy record id: [(Key, Min, Max, AscensionMin), ...]  -- `AscensionMin` absent = the base range.
INV_ROLLS = {
    # §209: Curl Up N (3-7, A7: 4-8, A17: 9-12) -- rolled at spawn, read by the trigger.
    "louse_red": [("roll.bite", 5, 7, 0), ("roll.bite", 6, 8, 2),
                  ("roll.curl_up", 3, 7, 0), ("roll.curl_up", 4, 8, 7),
                  ("roll.curl_up", 9, 12, 17)],
    # §258: the green louse is reachable now (`enc_two_louses`), and wiki gives it the same
    # spawn-time roll as the red one: Bite 5-7 (A2: 6-8), Curl Up 3-7 (A7: 4-8, A17: 9-12).
    "louse_green": [("roll.bite", 5, 7, 0), ("roll.bite", 6, 8, 2),
                    ("roll.curl_up", 3, 7, 0), ("roll.curl_up", 4, 8, 7),
                    ("roll.curl_up", 9, 12, 17)],
    "darkling": [("roll.nip", 7, 11, 0), ("roll.nip", 9, 13, 2)],
}

# §195.1: `ENCT.Enemies[].Counters` -- the **stated** numbers a status/rule needs to find already in
# place (a random roll cannot say "30", and no program can initialise a counter).
#
# The Guardian's Mode Shift budget: wiki `Powers = Mode Shift 30 (Asc|9|35 | Asc|19|40)`.
INV_SPAWN_COUNTERS = {
    "the_guardian": [("mode_shift_budget", 30, 0),
                     ("mode_shift_budget", 35, 9),
                     ("mode_shift_budget", 40, 19)],
    # §211: wiki `Giant Head` -- `It Is Time` deals (30; A3: 40), +5 per use, cap (60; A3: 70).
    # The **base** lives here (one place); the cap lives in the program's two variants.
    "giant_head": [("it_is_time_damage", 30, 0),
                   ("it_is_time_damage", 40, 3)],
    # §257: `Book of Stabbing` -- N = 2 + Multi-Stab uses (the base), and that A18 makes the
    # **Single Stab** push N too. Both are content state, not wiki numbers on their own; the wiki
    # numbers they produce are pinned by `INV_ACTIONS` / `INV_ASC_VARIANTS`.
    "book_of_stabbing": [("book_stab_hits_base", 2, 0),
                         ("book_stab_single_bump", 0, 0),
                         ("book_stab_single_bump", 1, 18)],
}

# §193: actions that exist in `EACT` but that **no enemy record lists**. They must not be converted
# to a counter read -- a counter nobody rolls reads 0, and 0 damage is a landmine that the
# ENEMY_DIFF harness cannot see (it runs every `EACT` row against a synthesised `<prefix>` enemy).
# The day one of these gets a record, this table goes red and forces the roll to be written too.
# §258: the green louse now has `enc_two_louses`, so nothing is unwired any more.
INV_UNWIRED = set()

# §218：每张卡的 wiki 页面。**字段**（type / rarity / cost / 关键字）在检查时从 dump 里读
# （`native/wiki_cards.py`），**数字**在 `native/card_wiki_inventory.py` 里人工冻结
# （wiki 的 Description 是散文，解析它等于在闸门里再实现一遍规则）。两边都指向同一份 dump，
# 所以任何一个数字都能离线复查。
CARD_WIKI = None            # 见 `load_card_wiki()`（延迟加载：导入 checker 的脚本不一定要它）
CARD_WIKI_DEVIATIONS = {}   # 基础 id -> 已知偏差的说明（矩阵的 Deviation 列会用它）

# 本内容有、wiki 没有的卡（样例包自带的）。**列出来**，不静默跳过。
NO_WIKI_PAGE = {
    'patient_guard': '本内容自有（样例包），wiki 没有这张牌',
    'swift_strike': '本内容自有（样例包），wiki 没有这张牌',
}

# ⚠️ §219：`Exhaust` **不在**这张表里 —— 它不是 tag，而是落区（见 `check_card_zones` 与
# `check_card_wiki` 的 ④）。留在表里会让它被当 tag 查两次，而内容里从来没有 `exhaust` tag。
KEYWORD_TAGS = {'Unplayable': 'unplayable', 'Ethereal': 'ethereal',
                'Innate': 'innate', 'Retain': 'retain'}


def load_card_wiki():
    """→ {基础 id: {'wiki': parse(...), 'base': [...], 'plus': [...] | None, 'deviation': {...}}}。"""
    global CARD_WIKI, CARD_WIKI_DEVIATIONS
    if CARD_WIKI is not None:
        return CARD_WIKI
    import card_wiki_inventory as W          # noqa: E402  (native/ 已在 sys.path 上)
    import wiki_cards
    out = {}
    for card_id in sorted(W.FACTS):
        deviation = W.DEVIATIONS.get(card_id, {})
        out[card_id] = {
            'wiki': wiki_cards.parse(card_id),
            'base': deviation.get('base_facts', W.FACTS[card_id][0]),
            'plus': deviation.get('plus_facts', W.FACTS[card_id][1]),
            'deviation': deviation,
        }
        if deviation.get('why'):
            CARD_WIKI_DEVIATIONS[card_id] = deviation['why']
    CARD_WIKI = out
    return out


CARD_ZONE_NAMES = {"DrawPile", "Hand", "DiscardPile", "ExhaustPile", "BanishedPile",
                   "QueuePile", "SetAsidePile"}


def check_card_zones(doc):
    """§219：两个卡牌落区字段的值必须是内核认识的**枚举名**。

    判据来自 `play.rs:1931` 的 `zone_from_wire_name`：它只认上表那七个串，别的一律
    `IrError::UnknownKind` —— 也就是说"写错一个词"= 这张牌一打就抛。`bandage_up` /
    `dark_shackles` 曾经写着 `"Exhaust"`（正确是 `"ExhaustPile"`），因为**没有任何测试打过它们**，
    这个错从 §157 一路活到 §218 的卡牌 wiki 对照。
    """
    seen = 0
    for card in doc["Cards"]:
        for key in ("PlayedCardDestinationZone", "TurnEndHandDestinationZone"):
            name = card.get(key)
            if name is None:
                continue
            seen += 1
            if name not in CARD_ZONE_NAMES:
                fail("card." + card["Id"], "%s = %r 不是区名（认识的是 %s）"
                     % (key, name, sorted(CARD_ZONE_NAMES)))
    return seen


CARD_LIFECYCLE_EVENTS = ("TurnEndInHand", "Drawn", "Exhausted",
                         # §250：`pain` —— "这张牌在手上、别人打出牌时"。
                         "CardPlayedInHand")


def _tuples(value):
    """把 `INV_CARDS` 的字面量转成 `program_facts` 的**形状**：`list[tuple]`。

    `program_facts` 返回 `[('damage', 2, 'source')]`（外层 list、内层 tuple），而字面量写成了
    `[['damage', 2, 'source']]`。两者打印出来几乎一样，但 `list != tuple` —— 不统一就会让每一条
    生命周期节目都报"事实不符"，而那看起来像内容错（§250 第一版就是这么红的）。
    """
    if not isinstance(value, list):
        return value
    out = []
    for item in value:
        if isinstance(item, list):
            out.append(tuple(_deep_tuple(sub) for sub in item))
        else:
            out.append(item)
    return out


def _deep_tuple(value):
    """嵌套的 list 一律变 tuple（`('loseHp', ['expr', ...], ...)` 那种内层）。"""
    if isinstance(value, list):
        return tuple(_deep_tuple(item) for item in value)
    return value


def check_card_lifecycle(doc):
    """§220：`CARD.LifecyclePrograms` 的**键集合**与**事实**，两个方向都查。

    这一层必须存在：这些节目不在卡的 `Program` 里，所以 `INV_CARDS` 的 `Facts` 一行**看不见**
    它们 —— 内容把一条节目删掉/写错时，只有这张表会红。`void`（`Drawn`）与 `sentinel`
    （`Exhausted`）是这一节新加的两条；`Drawn`/`Exhausted` 两个事件本身也是这一节新加的内核能力
    （参考的 `CardLifecycleTrigger` 只有 `TurnEndInHand`）。
    """
    cards = {card["Id"]: card for card in doc["Cards"]}
    seen = 0
    for card_id in sorted(cards):
        programs = cards[card_id].get("LifecyclePrograms") or {}
        expected = (INV_CARDS.get(card_id) or {}).get("Lifecycle") or {}
        for key in programs:
            if key not in CARD_LIFECYCLE_EVENTS:
                fail("card." + card_id, "生命周期事件 %r 内核不认识（认识的是 %s）"
                     % (key, list(CARD_LIFECYCLE_EVENTS)))
                continue
            if key not in expected:
                fail("card." + card_id, "有一条 `%s` 生命周期节目，`INV_CARDS` 没有记录" % key)
                continue
            seen += 1
            facts = program_facts(programs[key]["Root"])
            if facts != _tuples(expected[key]):
                fail("card." + card_id, "`%s` 节目事实 %s，inv says %s"
                     % (key, facts, expected[key]))
        for key in expected:
            if key not in programs:
                fail("card." + card_id, "`INV_CARDS` 记了 `%s` 节目，内容里没有" % key)
    return seen


def check_card_wiki(doc):
    """每张有 wiki 页面的卡：类型 / 稀有度 / 费用 / 关键字 / 数字，五项分开判。

    这一层补的是"内容门的清单也是人抄的"那个洞（§195.9：`blind` 的稀有度与 Exhaust 都写错过，
    而当时 20 道闸门全绿）。
    """
    inventory = load_card_wiki()
    cards = {card["Id"]: card for card in doc["Cards"]}
    checked = 0
    for card_id in sorted(inventory):
        entry = inventory[card_id]
        wiki = entry["wiki"]
        deviation = entry["deviation"]
        card = cards.get(card_id)
        if card is None:
            fail("card." + card_id, "wiki 页在、内容里没有这张卡")
            continue
        tags = {tag["value"] for tag in (card.get("Tags") or [])}

        # ① 类型：wiki 的 Attack/Skill/Power/Status/Curse 必须出现在内容的 tag 里
        #    （`buffer` 例外：wiki 页面已是 v2.3 的重做版（Power/Rare/2 费），本内容按旧版
        #     Skill/Uncommon/1 费 —— 那一条在偏差表里写明了）。
        if not deviation.get('content_type'):
            if wiki['type'] not in tags:
                fail("card." + card_id, "type %r 不在 tags %s 里（wiki `%s`）"
                     % (wiki['type'], sorted(tags), wiki['name']))

        # ② 稀有度：curse 的页面不写 Rarity，内容写 Curse
        expected_rarity = deviation.get('content_rarity')
        if expected_rarity is None:
            expected_rarity = wiki['rarity'] or ('Curse' if wiki['type'] == 'curse' else None)
        if expected_rarity is not None:
            actual = card.get('Rarity')
            if actual != expected_rarity:
                fail("card." + card_id, "rarity %r，wiki 说 %r" % (actual, expected_rarity))

        # ③ 费用：wiki 用 -1 表示 X 费、-2 表示不可出，内容用 tag 表达同一件事
        expected_cost = deviation.get('content_cost')
        if expected_cost is None:
            if wiki['cost'] == -1:
                expected_cost = 'x_cost'
            elif wiki['cost'] == -2:
                expected_cost = 'unplayable'
            else:
                expected_cost = wiki['cost']
        if expected_cost == 'x_cost':
            if 'x_cost' not in tags:
                fail("card." + card_id, "wiki 是 X 费，内容没有 `x_cost` tag")
        elif expected_cost == 'unplayable':
            if 'unplayable' not in tags:
                fail("card." + card_id, "wiki 是不可出，内容没有 `unplayable` tag")
        else:
            costs = [(cost["ResourceId"]["value"], cost["Amount"])
                     for cost in (card.get("Costs") or [])]
            if not any(resource.endswith("energy") and amount == expected_cost
                       for resource, amount in costs):
                fail("card." + card_id, "费用 %s，wiki 说 %d" % (costs, expected_cost))

        # ④ 关键字：`{{KW|X}}`（不带竖线的才算）↔ tag / 落区。
        #    ⚠️ §219：`Exhaust` 不是 tag，而是 **`PlayedCardDestinationZone = ExhaustPile`**
        #    （`play.rs:1931` 在那里把牌送进消耗堆）。§218 把它当 tag 比，于是 `bandage_up` /
        #    `dark_shackles` 被误判成"缺载体" —— 它们其实有，只是落区写错了一个词
        #    （那个拼写 bug 由 `check_card_zones` 与本节一起抓）。
        expected_keywords = deviation.get('content_keywords')
        if expected_keywords is None:
            expected_keywords = wiki['keywords']
        expected_tags = {KEYWORD_TAGS[name] for name in expected_keywords
                         if name in KEYWORD_TAGS}
        missing = expected_tags - tags
        if missing:
            fail("card." + card_id, "缺少关键字 tag %s（wiki %s）"
                 % (sorted(missing), wiki['keywords']))
        exhaust_expected = "Exhaust" in expected_keywords
        exhaust_actual = card.get("PlayedCardDestinationZone") == "ExhaustPile"
        if exhaust_expected != exhaust_actual:
            fail("card." + card_id, "wiki %s Exhaust，内容的落区是 %r"
                 % ("有" if exhaust_expected else "没有",
                    card.get("PlayedCardDestinationZone")))
        # 反向：内容有 ethereal/innate/retain 而 wiki 没有 —— 也要红（`sentinel` 就是这条）
        extra = (tags & {'ethereal', 'innate', 'retain'}) - expected_tags
        if extra and 'content_keywords' not in deviation:
            fail("card." + card_id, "多出关键字 tag %s（wiki 没有）" % sorted(extra))

        # ⑤ 数字：基础行与升级行分开比（`INV_CARDS` 的 Facts 就是从程序里抽出来的同一套词表）
        checked += 1
        # §250：字面量是 `list[list]`，wiki 那一侧来自 `program_facts` 的 `list[tuple]`；
        # 归一化之后 `repr` 才可比（否则每条新牌都报"facts 不符"，那看起来像内容错）。
        base_facts = _tuples(INV_CARDS[card_id]["Facts"])
        if sorted(map(repr, base_facts)) != sorted(map(repr, entry["base"])):
            fail("card." + card_id, "facts %s，wiki 说 %s" % (list(base_facts), entry["base"]))
        plus_id = card_id + "+"
        if entry["plus"] is None:
            if plus_id in INV_CARDS:
                fail("card." + plus_id, "内容有升级行，但 wiki 的升级只改关键字/目标（没有数字）")
        else:
            if plus_id not in INV_CARDS:
                fail("card." + plus_id, "wiki 有升级数字 %s，内容没有这一行" % (entry["plus"],))
            else:
                plus_facts = _tuples(INV_CARDS[plus_id]["Facts"])
                if sorted(map(repr, plus_facts)) != sorted(map(repr, entry["plus"])):
                    fail("card." + plus_id, "facts %s，wiki 说 %s"
                         % (list(plus_facts), entry["plus"]))

    # 没有 wiki 页的两张牌必须**还是**那两张（内容加了新牌就该有人去找页面）
    for card_id, reason in sorted(NO_WIKI_PAGE.items()):
        if card_id not in cards:
            fail("card." + card_id, "`NO_WIKI_PAGE` 声明的 %s 在内容里不存在（声明烂了）：%s"
                 % (card_id, reason))
        elif card_id in inventory:
            fail("card." + card_id, "已经有 wiki 页了，`NO_WIKI_PAGE` 里那一条该删掉")
        elif card_id + "+" in cards:
            pass      # 升级行沿用同一张页面，没有独立页面是正常的
    return checked

# §216: **每个程序读哪一个"时间变量"**，穷尽。这条表是被一次真 bug 逼出来的：
# `maw.nom_nom` 用的是 `turnNumber`，而那是**一轮内的行动者序号**（`turn.rs:970` 绕回时置 1）——
# 单怪场景里 Maw 出手时它恒为 2，于是 `ceil(turn/2)` **永远是 1 击**。wiki 说的是
# "Current turn, divided by two"，指**轮次**（`roundNumber`）。
#
# ⚠️ 为什么事实表挡不住它：`INV_ACTIONS` 把这条动作钉成
# `("repeat", ("expr", "divide"), "damage", 5, "event")` —— `turnNumber` 与 `roundNumber`
# 在事实层面**一模一样**。所以这里钉的是**变量名**，两个方向都查：
#   ① 表里声明的变量必须真的出现（改了内容就红）；
#   ② 程序里出现的变量必须在表里（新写一个读时间变量的动作也红）。
# 这条表的粒度是"哪个变量"，不是"哪个节点"：`turnNumber` 与 `roundNumber` 只差一个词，
# 而它们一个是轮内序号、一个是轮次。
TIME_VARIABLES = ("turnNumber", "roundNumber")
INV_TIME_VARIABLES = {
    "maw.nom_nom": ("roundNumber",),
}


# §206: the wiki's `AscHP` **lower bound** per monster, straight out of the `Enemy Infobox` dump in
# `native/wiki_asc/*.txt`. This is the **independent copy** of the numbers the ENCT rows pin: the
# content is what the kernel reads, this table is what the wiki said, and the check is that they
# match. `maw` is absent on purpose -- its wiki page 404s, so that record keeps the old `+10%` model.
INV_ASC_HP = {
    'spike_slime_s': 11, 'fat_gremlin': 14, 'sneaky_gremlin': 11, 'blue_slaver': 48,
    'acid_slime_s': 9, 'acid_slime_m': 29, 'spike_slime_m': 29, 'jaw_worm': 42,
    'cultist': 50, 'gremlin_wizard': 22, 'sentry_1': 39, 'sentry_2': 39, 'sentry_3': 39,
    'slime_boss': 150, 'time_eater': 480, 'shelled_parasite': 70, 'chosen': 98, 'byrd': 26,
    'spiker': 44, 'orb_walker': 92, 'the_champ': 440, 'gremlin_leader': 145, 'giant_head': 520,
    'darkling': 50, 'spire_growth': 190, 'louse_red': 11, 'louse_green': 12, 'fungi_beast': 24,
    'slaver_red': 48, 'gremlin_nob': 85, 'lagavulin': 112, 'book_of_stabbing': 168,
    'taskmaster': 57, 'nemesis': 200, 'reptomancer': 190, 'dagger': 20, 'the_guardian': 250,
    'hexaghost': 264, 'bronze_automaton': 320, 'bronze_orb': 54, 'the_collector': 300,
    'torch_head': 40, 'awakened_one': 320, 'donu': 265, 'deca': 265, 'looter': 46,
}
# Which ascension level owns "tougher enemies" (§187's three rules).
INV_ASC_HP_LEVEL = {'Elite': 8, 'Boss': 9}


# §207: the wiki's starting-power ascension rows (`Enemy Infobox` -> `Powers`), by monster id.
# `{status: [(level, stacks), …]}` -- the **independent copy** the content is checked against.
INV_STATUS_ASC = {
    # `Shapes` (Spiker): Thorns 3 (A2: 4 | A17: 7).
    'spiker': {'standard.thorns': [(2, 4), (17, 7)]},
    # `Byrd`: Flying 3 (A17: 4). §208 added `standard.flying` (half damage from attacks, one stack
    # per hit) **and** the `damage.isAttack` event fact, so the §207 "not expressible" note is gone.
    # `Jaw Worm`: Strength 3 (A2/A17) is a status; its Block 6 (A17: 9) is a **defensive pool** --
    # §208 gave the enemy record `StartingBlock` / `StartingBlockAsc` for exactly that case.
    'byrd': {'standard.flying': [(17, 4)]},
    # `Orb Walker`: Strength Up 3 (A17: 5).
    'orb_walker': {'standard.strength': [(17, 5)]},
    # `Awakened One`: Regenerate 10 (A19: 15), Curiosity 1 (A19: 2).
    'awakened_one': {'standard.regen': [(19, 15)], 'standard.curiosity': [(19, 2)]},
    # `Donu and Deca`: Artifact 2 (A19: 3).
    'donu': {'standard.artifact': [(19, 3)]},
    'deca': {'standard.artifact': [(19, 3)]},
}


def check_starting_status_ascension(doc):
    """§207: every `StartingStatuses[].Asc` row is the wiki's, at the wiki's level."""
    print("[7e] starting-status ascension (port-plan.md §207)")
    seen = set()
    for encounter in doc.get("Encounters") or []:
        eid = encounter["Id"]["Value"] if isinstance(encounter["Id"], dict) else encounter["Id"]
        for enemy in encounter.get("Enemies") or []:
            monster = enemy["Id"]
            want = INV_STATUS_ASC.get(monster)
            rows = enemy.get("StartingStatuses") or []
            for row in rows:
                status = (row.get("StatusDefinitionId") or {}).get("value")
                if want is None or status not in want:
                    if row.get("Asc"):
                        fail("asc.status.%s/%s" % (monster, status),
                             "an `Asc` row that no wiki page backs (%r)" % (row.get("Asc"),))
                    continue
                got = [(entry.get("AscensionMin"), entry.get("Stacks"))
                       for entry in row.get("Asc") or []]
                if got != want[status]:
                    fail("asc.status.%s/%s" % (monster, status),
                         "Asc %s, wiki says %s" % (got, want[status]))
                seen.add((monster, status))
    missing = [(monster, status) for monster, rows in INV_STATUS_ASC.items()
               for status in rows if (monster, status) not in seen]
    if missing:
        fail("asc.status.missing", "no record pins %s" % (missing,))
    ok("starting-status ascension", "%d rows pinned (A2/A17/A19)" % len(seen))


# §207: monsters whose ENCT record has **no** `MaxHealthAsc`, with the wiki reason.
INV_NO_ASC_HP = {
    # wiki `The Maw`: "The Maw is the only enemy whose Max HP does not change based on Ascension
    # level." (native/wiki_asc/the_maw.txt) -- pinning a number here would be inventing one.
    'maw': 'wiki The Maw: max HP does not change with ascension',
}


def check_ascension_health(doc):
    """§206: every pinned `MaxHealthAsc` matches the wiki's `AscHP` lower bound, at the right level."""
    print("[7d] ascension health (port-plan.md §206)")
    # ⚠️ `Monster.Tier` is **not** the fight tier (`gremlin_nob` says "Normal" and is an elite), so
    # the level comes from the **pools**: a boss pool pays A9, an elite pool A8, the rest A7.
    level_of = {}
    for key, entries in (doc.get("EncounterTables") or {}).items():
        if not isinstance(entries, list):
            continue
        level = 9 if key.startswith("Boss") else (8 if key.startswith("Elite") else 7)
        for entry in entries:
            level_of[entry["Id"]] = max(level_of.get(entry["Id"], 0), level)
    checked = 0
    unpinned = set()
    for encounter in doc.get("Encounters") or []:
        eid = encounter["Id"]["Value"] if isinstance(encounter["Id"], dict) else encounter["Id"]
        level = level_of.get(eid, 7)
        for enemy in encounter.get("Enemies") or []:
            monster = enemy["Id"]
            want = INV_ASC_HP.get(monster)
            if want is None:
                if monster not in INV_NO_ASC_HP:
                    fail("asc.hp." + monster, "no pinned row and no wiki reason")
                unpinned.add(monster)
                continue
            rows = enemy.get("MaxHealthAsc")
            if not rows:
                fail("asc.hp." + monster, "no MaxHealthAsc (the row still uses the +10% model)")
                continue
            if len(rows) != 1:
                fail("asc.hp." + monster, "expected exactly one A%d row, got %r" % (level, rows))
                continue
            row = rows[0]
            if row.get("AscensionMin") != level:
                fail("asc.hp." + monster,
                     "pinned at A%s, but this encounter pays A%d"
                     % (row.get("AscensionMin"), level))
            if row.get("MaxHealth") != want:
                fail("asc.hp." + monster,
                     "MaxHealthAsc %r, wiki says %d" % (row.get("MaxHealth"), want))
            checked += 1
    ok("ascension health", "%d ENCT enemy records pinned; unpinned monsters: %s"
       % (checked, sorted(unpinned) or "none"))


def check_ascension_variants(doc):
    """§187/§192：**每一条**升档节目都必须被上面那张表钉住，且与基础节目、别的变体**都不同**。"""
    print("[7] ascension variants (port-plan.md §187/§192)")
    actions = {a["Id"]: a for a in doc.get("EnemyActions") or []}
    total = 0
    for aid, entries in INV_ASC_VARIANTS.items():
        action = actions.get(aid)
        if action is None:
            fail("asc." + aid, "action missing")
            continue
        variants = action.get("ProgramAsc")
        if variants is None:
            fail("asc." + aid, "no ProgramAsc")
            continue
        if not isinstance(variants, list) or not variants:
            fail("asc." + aid, "ProgramAsc must be a non-empty **list** (%r)" % (variants,))
            continue
        # 阈值：内容写的这几个必须**正好**是表里那几个（多一个 = 没人钉过的档位）。
        thresholds = []
        for index, variant in enumerate(variants):
            keys = set(variant) if isinstance(variant, dict) else set()
            if keys != {"AscensionMin", "Program"}:
                fail("asc." + aid, "variant[%d] keys %r" % (index, sorted(keys)))
                break
            thresholds.append(variant["AscensionMin"])
        if len(thresholds) != len(variants):
            continue
        if sorted(thresholds) != [t for t, _ in entries]:
            fail("asc." + aid, "thresholds %r, inv says %r"
                 % (thresholds, [t for t, _ in entries]))
            continue
        if thresholds != sorted(set(thresholds)):
            fail("asc." + aid, "thresholds %r are not strictly ascending/unique -- the kernel "
                               "picks the largest eligible, so order must not be load-bearing"
                 % (thresholds,))
        # 事实：每个档位各自与表比；而且**没有两个档位讲同一个故事**。
        seen = [program_facts(action["Program"]["Root"])]
        for variant, (threshold, facts) in zip(variants, entries):
            got, _code = split_history(program_facts(variant["Program"]["Root"]))
            if got != facts:
                fail("asc." + aid + ".A%d" % threshold,
                     "facts %s, inv says %s" % (got, facts))
            if got in seen:
                fail("asc." + aid + ".A%d" % threshold,
                     "identical to the base or to an earlier variant -- this tier does nothing")
            seen.append(got)
            total += 1
    # 反向：内容里有而表里没有的变体也不行（"没人钉过的数字"）。
    unknown = sorted(aid for aid, action in actions.items()
                     if action.get("ProgramAsc") and aid not in INV_ASC_VARIANTS)
    if unknown:
        fail("asc.unknown", "variants not pinned by the inventory: %s" % unknown)
    ok("ascension variants", "%d variants over %d actions pinned (A2/A3/A4 + A17-A19)"
       % (total, len(INV_ASC_VARIANTS)))
    check_ascension_coverage(actions)


# §204: the moves whose wiki page shows **no** ascension row. Each entry says which page was read;
# "the wiki has no A-row here" is a decision, and a decision has to be written down or the next
# reader cannot tell it from "nobody looked".
INV_NO_ASC = {
    # `Thieves` (native/wiki_asc/thieves.txt): Smoke Bomb is "Gains 6 Block" with no A-row; Escape
    # is a rule, not a number.
    'looter.smoke_bomb': 'wiki Thieves: 6 Block, no A-row',
    'looter.escape': 'wiki Thieves: Escape has no numbers',
    # `Cultist`: Dark Strike "Deals 6 damage." -- the Ritual stack is what ascension moves (already
    # an `Incantation` variant).
    'cultist.dark_strike': 'wiki Cultist: 6 damage, no A-row',
    # `Jaw Worm`: Thrash "Deals 7 damage. Gains 5 Block." -- Chomp/Bellow carry the A-rows.
    'jaw_worm.thrash': 'wiki Jaw Worm: Thrash has no A-row',
    # `Fungi Beast`: Bite "Deals 6 damage." (Grow carries them).
    'fungi_beast.bite': 'wiki Fungi Beast: Bite has no A-row',
    # `Gremlin Leader`: Slash "Deals 6x3 damage." / Rally's numbers are pinned as A3/A18 variants
    # already -- the *attack* has no A-row.
    'gremlin_leader.summon': 'wiki Gremlin Leader: Summon has no numbers',
    # `The Guardian`: Twin Slam "Deals 8x2 damage." / Whirlwind "Deals 5x4 damage." -- Fierce Bash
    # and Vent Steam carry the A-rows (Vent Steam's Sharp Hide 3 -> A19: 4 is a counter, see below).
    'the_guardian.twin_slam': 'wiki The Guardian: no A-row',
    'the_guardian.whirlwind': 'wiki The Guardian: no A-row',
    'the_guardian.charging_up': 'wiki The Guardian: Mode Shift moves, no A-row on the move itself',
    # `Hexaghost`: Divider scales with HP ("(N+1)x6", no A-row); Activate/Inferno hold the A-rows.
    'hexaghost.divider': 'wiki Hexaghost: Divider has no A-row',
    'hexaghost.activate': 'wiki Hexaghost: Activate has no numbers',
    # `Nemesis`: Scythe "Deals 45 damage." (Tri Attack/Tri Burn carry the A-rows).
    'nemesis.scythe': 'wiki Nemesis: Scythe has no A-row',
    # `Awakened One`: none of the five moves has an A-row; the ascension rows are on its starting
    # powers (Regenerate / Curiosity / Strength), which are `StartingStatuses`.
    'awakened_one.slash': 'wiki Awakened One: no A-row on moves',
    'awakened_one.soul_strike': 'wiki Awakened One: no A-row on moves',
    'awakened_one.tackle': 'wiki Awakened One: no A-row on moves',
    'awakened_one.sludge': 'wiki Awakened One: no A-row on moves',
    'awakened_one.dark_echo': 'wiki Awakened One: no A-row on moves',
    'awakened_one.rebirth': 'wiki Awakened One: Rebirth is a rule, no numbers',
    # `Donu and Deca`: Circle of Power "All enemies gain 3 Strength" (the beams and Square of
    # Protection carry the A-rows).
    'donu.circle_of_power': 'wiki Donu and Deca: Circle of Power has no A-row',
    # Dagger: Wound 9 / Explode 25 -- neither has an A-row (the dagger's HP does).
    'dagger.wound': 'wiki Reptomancer: dagger moves have no A-row',
    'dagger.explode': 'wiki Reptomancer: Explode 25, no A-row',
    'slime_boss.preparing': 'wiki Slime Boss: Preparing has no numbers',
    'gremlin_wizard.charging': 'wiki Gremlin Wizard: Charging has no numbers',
    # ---- §206: the rest of the 26, each read off its own page today ---------------------------
    # `Acid Slime` / `Spike Slime`: only the **L** size has an A17 row (`Lick` 2 -> 3); this content
    # ships no L slime, and the S/M rows are flat (1 Weak / 1 Frail).
    'acid_slime_s.lick': 'wiki Acid Slime: S Lick is 1 Weak, no A-row',
    'acid_slime_m.lick': 'wiki Acid Slime: M Lick is 1 Weak, no A-row',
    'spike_slime_m.lick': 'wiki Spike Slime: M Lick is 1 Frail, no A-row (only L has A17)',
    # `Slavers`: Entangle is a rule ("Applies 1 Entangled"), not a number.
    'slaver_red.entangle': 'wiki Slavers: Entangle applies a status, no A-row',
    # `The Champ`: Taunt 2 Weak + 2 Vulnerable and Execute 10x2, both flat.
    'the_champ.taunt': 'wiki The Champ: Taunt has no A-row',
    'the_champ.execute': 'wiki The Champ: Execute is 10x2, no A-row',
    # `Gremlin Leader`: Slash is 6x3 flat. `Rally!` **does** have A3/A18 rows, but they are worded
    # "all enemies gain N Strength / other enemies gain M Block" -- this content's rally is the §130
    # simplification (self +5 Strength / +12 Block), so the wiki's rows describe a program we do not
    # implement. Named here instead of silently claimed.
    'gremlin_leader.slash': 'wiki Gremlin Leader: Slash is 6x3, no A-row',
    'gremlin_leader.rally': 'wiki rows describe "all enemies" wording; this content is the §130 simplification',
    # `Giant Head`: Glare applies 1 Weak, flat (Count carries the A3 row).
    'giant_head.glare': 'wiki Giant Head: Glare applies 1 Weak, no A-row',
    'giant_head.count': 'wiki Giant Head: Count is flat 13, no A-row',
    # `Darkling` / `Louses`: the damage is **rolled at combat start** (`N = 7-11`, A2 `9-13`), which
    # is the `Rolls` mechanism (§193), not `ProgramAsc`.
    'darkling.nip': 'wiki Darkling: Nip is rolled at spawn (A2 changes the roll, §193)',
    'louse_red.bite': 'wiki Louses: Bite is rolled at spawn (A2 changes the roll, §193)',
    'louse_green.bite': 'wiki Louses: Bite is rolled at spawn (A2 changes the roll, §193)',
    'louse_green.spit_web': 'wiki Green Louse: Spit Web is 2 Weak at every ascension',
    'louse_green.spit_web': 'wiki Green Louse: Spit Web is 2 Weak, no A-row',
    # `Lagavulin`: Sleep does nothing.
    'lagavulin.sleep': 'wiki Lagavulin: Sleep does nothing',
    'lagavulin.stunned': 'wiki Lagavulin: Stunned does nothing (a lost turn, no numbers)',
    # `The Guardian`: Vent Steam applies 2 Weak + 2 Vulnerable, flat (the Sharp Hide / Mode Shift
    # numbers live on `defensive_mode` / `twin_slam`, which have their own rows).
    'the_guardian.vent_steam': 'wiki The Guardian: Vent Steam has no A-row',
    # `Bronze Automaton` / `Bronze Orb` / `Torch Head`: Stunned and the summons have no numbers; Beam
    # is 8 and Support Beam 12 Block, both flat; Torch Head Tackle is 7, flat.
    'bronze_automaton.stunned': 'wiki Bronze Automaton: Stunned does nothing',
    'bronze_automaton.spawn_orbs': 'wiki Bronze Automaton: Spawn Orbs has no numbers',
    'bronze_orb.stasis': 'wiki Bronze Orb: Stasis is a rule, no numbers',
    'bronze_orb.beam': 'wiki Bronze Orb: Beam is 8, no A-row',
    'bronze_orb.support_beam': 'wiki Bronze Orb: Support Beam is 12 Block, no A-row',
    'torch_head.tackle': 'wiki Torch Head: Tackle is 7, no A-row',
    'the_collector.spawn': 'wiki The Collector: Spawn has no numbers',
    # ---- §207: `maw` -- the wiki page is **The Maw** (the search API found it; the plain `Maw`
    # title 404s). Its moves do have A-rows (Slam 25 -> A2: 30, Roar 3 Weak/3 Frail -> A17: 5,
    # Drool 3 Strength -> A17: 5), but this content's `maw` is the **§137 stub** (80 HP, `bite 14` /
    # `slam 20 + Block` / `roar +Strength`), i.e. a different monster. Copying the wiki numbers onto
    # it would be inventing a hybrid, so the deviation is recorded here instead.
    # §212: `Nom Nom` is the only one of the four without an A-row (its number is a formula).
    'maw.nom_nom': 'wiki The Maw: Nom Nom is 5 x ceil(turn/2), no A-row',
    # §213: `Hex` applies a status and `Drain` moves statuses; neither has an A-row on the page.
    'chosen.hex': 'wiki Chosen: Hex applies the Hex debuff, no A-row',
    'chosen.drain': 'wiki Chosen: Drain is 3 Weak + 3 Strength, no A-row',
    # wiki `Shapes` (Spiker): its two moves are `Attack` (7 -> A2: 9) and `Buff Thorns`. This
    # content's `spiker.spike` is 4 damage + 2 Block -- a simplification of neither, so the wiki's
    # A2 row cannot be copied onto it without inventing a number.
    'spiker.spike': 'wiki Shapes#Spiker: Buff Thorns is always +2 Thorns, no A-row',
}

# §204: how many actions still have **neither** a variant nor an exemption. This is a **ratchet**:
# the number may only go down, and it is printed (not implied) so "we reviewed everything" cannot be
# claimed without the count agreeing. 44 at §204, 26 at §205, 4 at §206, **0** after §207.
ASC_UNREVIEWED_CEILING = 0


def check_ascension_coverage(actions):
    """§204: every damage-dealing move carries a **decision**, and the undecided count shrinks."""
    print("[7c] ascension coverage (port-plan.md §204)")
    for aid, reason in INV_NO_ASC.items():
        action = actions.get(aid)
        if action is None:
            fail("asc.exempt." + aid, "action missing")
            continue
        if action.get("ProgramAsc"):
            fail("asc.exempt." + aid,
                 "listed as 'no ascension row' (%s) but it **has** ProgramAsc" % reason)
    pinned = set(INV_ASC_VARIANTS) | set(INV_NO_ASC)
    unreviewed = sorted(a["Id"] for a in actions.values() if a["Id"] not in pinned)
    ok("ascension coverage", "%d with variants + %d exempt = %d reviewed, %d undecided"
       % (len(INV_ASC_VARIANTS), len(INV_NO_ASC), len(pinned), len(unreviewed)))
    if len(unreviewed) > ASC_UNREVIEWED_CEILING:
        fail("asc.unreviewed", "%d actions have no ascension decision (ceiling %d): %s"
             % (len(unreviewed), ASC_UNREVIEWED_CEILING, ", ".join(unreviewed[:12])))


def check_spawn_rolls(doc):
    """§193: 每条计数器读取都必须被**列出这条动作的那个敌人的**掷骰覆盖。"""
    print("[7b] spawn rolls (port-stage/§193)")
    records = {}
    for encounter in doc.get("Encounters") or []:
        for record in encounter["Enemies"]:
            records.setdefault(record["Id"], []).append(record)

    # ① 记录侧的形态：只有表里的敌人掷骰，而且范围/档位逐个对得上。
    for record_id, group in records.items():
        for record in group:
            rolls = record.get("Rolls")
            if rolls is None:
                fail("roll." + record_id, "the record has no `Rolls` key (shape drift)")
                continue
            got = [(r["Key"], r["Min"], r["Max"], r.get("AscensionMin", 0)) for r in rolls]
            want = INV_ROLLS.get(record_id, [])
            if got != want:
                fail("roll." + record_id, "%r, inv says %r" % (got, want))
            # 值域必须能被一次 `shuffled_pick_index` 覆盖（下标是 u8），而且 Min 不许比 Max 大。
            for key, low, high, threshold in got:
                if high < low:
                    fail("roll." + record_id, "`%s`: Max %d < Min %d" % (key, high, low))
                if high - low + 1 > 255:
                    fail("roll." + record_id,
                         "`%s`: %d values do not fit the u8 pick index" % (key, high - low + 1))
                if threshold < 0:
                    fail("roll." + record_id, "`%s`: negative AscensionMin" % key)
            # 同一个 Key 的阈值必须严格升序（与 `ProgramAsc` 同一条规矩：顺序不参与判定，
            # 但"两行同阈值"选谁都是猜）。
            by_key = {}
            for key, _, _, threshold in got:
                by_key.setdefault(key, []).append(threshold)
            for key, thresholds in by_key.items():
                if thresholds != sorted(set(thresholds)):
                    fail("roll." + record_id,
                         "`%s`: thresholds %r are not strictly ascending/unique" % (key, thresholds))
    unknown = sorted(record_id for record_id in INV_ROLLS if record_id not in records)
    if unknown:
        fail("roll.unknown", "inventory names enemies that are not in the content: %s" % unknown)

    # ①b §195.1：固定计数器的形态 + 数字（`Counters: [{Key, Value, AscensionMin?}]`）。
    for record_id, group in records.items():
        for record in group:
            entries = record.get("Counters")
            if entries is None:
                fail("counters." + record_id, "the record has no `Counters` key (shape drift)")
                continue
            got = [(e["Key"], e["Value"], e.get("AscensionMin", 0)) for e in entries]
            want = INV_SPAWN_COUNTERS.get(record_id, [])
            if got != want:
                fail("counters." + record_id, "%r, inv says %r" % (got, want))
            by_key = {}
            for key, _value, threshold in got:
                by_key.setdefault(key, []).append(threshold)
            for key, thresholds in by_key.items():
                if thresholds != sorted(set(thresholds)):
                    fail("counters." + record_id,
                         "`%s`: thresholds %r are not strictly ascending/unique" % (key, thresholds))
    missing = sorted(record_id for record_id in INV_SPAWN_COUNTERS if record_id not in records)
    if missing:
        fail("counters.unknown", "inventory names enemies that are not in the content: %s" % missing)

    # ② 程序侧：每个计数器读取都必须是**列这条动作的记录**掷过的键。
    actions = {a["Id"]: a for a in doc.get("EnemyActions") or []}
    readers = 0
    for record_id, group in records.items():
        for record in group:
            # §211: `Counters` (fixed spawn counters, §195.1) initialise values exactly like `Rolls`
            # do, so reading either is legitimate. The check only knew the random half -- which is why
            # `it_is_time_damage` (written by `Counters`) looked like "a counter nobody rolls".
            rolled = {r["Key"] for r in record.get("Rolls") or []}
            rolled |= {c["Key"] for c in record.get("Counters") or []}
            for action_id in record["Actions"]:
                action_id = action_id["value"] if isinstance(action_id, dict) else action_id
                program = actions.get(action_id)
                if program is None:
                    fail("roll." + action_id, "record lists an action that is not in EACT")
                    continue
                for fact in program_facts(program["Program"]["Root"]):
                    # 事实的形状是 ("damage", amount, target)；amount 是 3 元组才是计数器读取。
                    if fact[0] not in ("damage", "block", "heal"):
                        continue
                    size = fact[1]
                    if not isinstance(size, tuple) or size[0] != "counter":
                        continue
                    readers += 1
                    if size[2] != "source":
                        fail("roll." + action_id,
                             "reads a counter from `%s`, not from itself" % size[2])
                    if size[1] not in rolled:
                        fail("roll." + action_id,
                             "reads `%s` but `%s` never rolls it (damage would be 0)" % (size[1], record_id))

    # ③ 反向：没有敌人记录的动作**不许**读计数器（见 `INV_UNWIRED` 的理由）。
    listed = set()
    for record in records.values():
        for action_ids in record:
            for action_id in action_ids["Actions"]:
                listed.add(action_id["value"] if isinstance(action_id, dict) else action_id)
    for action_id, action in actions.items():
        if action_id in listed:
            continue
        for fact in program_facts(action["Program"]["Root"]):
            if fact[0] in ("damage", "block", "heal") and isinstance(fact[1], tuple) \
                    and fact[1][0] == "counter":
                fail("roll.unwired." + action_id,
                     "unreachable action reads a counter nobody rolls")
    for action_id in INV_UNWIRED:
        if action_id in listed:
            fail("roll.wired." + action_id,
                 "this action now has an enemy record -- give it a roll and drop it from INV_UNWIRED")
    ok("spawn rolls", "%d ranges over %d enemies, %d counter reads wired, %d fixed counters"
       % (sum(len(v) for v in INV_ROLLS.values()), len(INV_ROLLS), readers,
          sum(len(v) for v in INV_SPAWN_COUNTERS.values())))


def check_time_variables(doc):
    """§216：每个敌人动作读哪一个时间变量 —— 穷尽两个方向。

    `turnNumber` = 一轮内的行动者序号（绕回置 1）；`roundNumber` = 第几轮。两者在**事实**层面
    长得一样（都是"一个整数字段"），所以只有钉变量名才能抓住"用对了形状、用错了含义"。
    """
    seen = {}
    for action in doc["EnemyActions"]:
        names = set()
        programs = [action.get("Program")]
        programs += [entry.get("Program") for entry in (action.get("ProgramAsc") or [])]
        for program in programs:
            if program:
                collect_time_variables(program["Root"], names)
        if names:
            seen[action["Id"]] = tuple(sorted(names))
    for action_id in sorted(set(seen) | set(INV_TIME_VARIABLES)):
        expected = tuple(sorted(INV_TIME_VARIABLES.get(action_id, ())))
        actual = seen.get(action_id, ())
        if expected != actual:
            fail("action." + action_id,
                 "time variables %s, inventory says %s" % (list(actual), list(expected)))
    return len(INV_TIME_VARIABLES)


def collect_time_variables(node, out):
    if isinstance(node, dict):
        kind = node.get("kind")
        if kind in TIME_VARIABLES:
            out.add(kind)
        for value in node.values():
            collect_time_variables(value, out)
    elif isinstance(node, list):
        for value in node:
            collect_time_variables(value, out)


def check_intent_history(doc):
    """§195.5：`last_move` / `prev_move` 这套历史是**内容状态**，所以它有自己的检查。

    带权抽签本身不需要历史；需要它的是"不能连续用同一招"那类规则，而那些规则的条件是
    `intent.selfHasCounter{last_move == k}`。于是有三件事必须同时成立，否则 Boss 会静默出招错乱：

    1. **每个能被选中的动作都要写自己的 code**（否则 `last_move` 停在上一只怪的旧值上，排除规则
       会一直命中或永远不命中）；
    2. **同一个敌人的 code 两两不同**（两招写同一个数 ⇒ "不能连续用 A" 会连带禁掉 B）；
    3. **规则里问到的每个 code 都真有动作写它**（这是一个 4 字节的错字就能造成的死规则：
       规则永远不命中、Boss 永远按默认权重出招，而所有数字看起来都对）。
    """
    print("[2c] intent history (port-stage/§195.5)")
    actions = {a["Id"]: a for a in doc.get("EnemyActions") or []}
    watched = 0
    for monster in doc.get("Monsters") or []:
        rules = monster.get("IntentRules") or []
        blob = json.dumps(rules)
        if "last_move" not in blob:
            continue
        watched += 1
        mid = monster["Id"]
        # every action this enemy can pick (cycle + every Choice/Action a rule names)
        reachable = [entry["value"] for entry in monster.get("Actions") or []]
        asked = set()
        for rule in rules:
            if rule.get("Action"):
                reachable.append(rule["Action"]["value"])
            for option in rule.get("Choice") or []:
                reachable.append(option["Action"]["value"])
            for condition in _walk_conditions(rule.get("Condition")):
                if condition.get("kind") == "intent.selfHasCounter":
                    value = condition["value"]
                    if value["Counter"]["value"] == "last_move":
                        asked.add(value["Value"])
        # 1 + 2: each reachable action writes a distinct code
        codes = {}
        for action_id in sorted(set(reachable)):
            action = actions.get(action_id)
            if action is None:
                continue
            for program in [action["Program"]] + [v["Program"] for v in action.get("ProgramAsc") or []]:
                _facts, code = split_history(program_facts(program["Root"]))
                if code is None:
                    fail("history." + mid, "`%s` does not record `last_move`" % action_id)
                else:
                    codes.setdefault(code, set()).add(action_id)
        for code, owners in sorted(codes.items()):
            if len(owners) > 1:
                fail("history." + mid,
                     "code %d is written by %s -- codes must be distinct per enemy"
                     % (code, sorted(owners)))
        # 3: every asked code exists
        for code in sorted(asked):
            if code not in codes:
                fail("history." + mid,
                     "a rule asks for `last_move == %d`, but no action writes it" % code)
    ok("intent history", "%d enemies use last_move; codes distinct and all referenced codes written"
       % watched)


def _walk_conditions(condition):
    """Yield every condition node in a (possibly nested) condition tree."""
    if not isinstance(condition, dict):
        return
    yield condition
    value = condition.get("value") or {}
    for inner in value.get("Conditions") or []:
        yield from _walk_conditions(inner)
    if value.get("Condition") is not None:
        yield from _walk_conditions(value["Condition"])


# §264：`PassiveModifiers` 的两个**参数**键。只登记真的用了它们的行；
# 其余行的这两个键必须是 null（下面的循环逐条断言）—— "内容悄悄用了一个参数而这里没写"
# 会红，这正是我们要的。
SPEC_PARAMS = {
    # 遗物改写别的状态的幅值：`(AppliesToStatusId, RestrictSourceCardTag)`
    "standard.paper_phrog": ("standard.vulnerable", None),
    "standard.paper_krane": ("standard.weak", None),
    # §265：新管线的 spec 天生绑在某条状态上。
    "standard.snecko_skull": ("standard.poison", None),
    "standard.ginger": ("standard.weak", None),
    "standard.turnip": ("standard.frail", None),
    # §266
    "standard.odd_mushroom": ("standard.vulnerable", None),
    # §267：`akabeko` 的 +8 只对攻击牌（`RestrictSourceCardTag`）。
    "standard.akabeko": (None, "attack"),
    # §262 的翻倍现在只对攻击牌生效（§264 解开了那个参数）。
    "standard.double_damage": (None, "attack"),
}


def check_statuses(doc):
    print("[4] status rows (inv:§10)")
    statuses = {s["Id"]: s for s in doc.get("Statuses") or []}
    for sid, mods in INV_STATUSES.items():
        row = statuses.get(sid)
        if row is None:
            fail("status." + sid, "missing")
            continue
        # §264：spec 现在最多有 7 个键，后两个（`AppliesToStatusId` / `RestrictSourceCardTag`）
        # 是**参数**。比对分两半：
        #   * 前 5 个字段进主元组（和以前一样，所有行都写着）；
        #   * 后两个参数只在**声明了**的条目上比对 —— 见下面的 `PARAMS` 表。
        # 为什么不让每一行都写成 7 元组：那会把 20 多条无关的行一起改，而"改得越多越容易手滑"
        # 是这个仓库反复吃亏的形状。
        got = [(m["Pipeline"], m["Operation"], m["Magnitude"], m["Priority"],
                m["RestrictDamageKind"])
               for m in row.get("PassiveModifiers") or []]
        if got != mods:
            fail("status." + sid, "passive modifiers %s, expected %s" % (got, mods))
        # §264：两个参数键。声明过的行逐条比对；没声明的行必须是 null。
        want = SPEC_PARAMS.get(sid, (None, None))
        filled = ((row.get("PassiveModifiers") or [{}])[0].get("AppliesToStatusId"),
                  (row.get("PassiveModifiers") or [{}])[0].get("RestrictSourceCardTag"))
        filled_ids = tuple((v or {}).get("value") for v in filled)
        if filled_ids != want:
            fail("status." + sid,
                 "modifier params (AppliesToStatusId, RestrictSourceCardTag) = %r, expected %r"
                 % (filled_ids, want))
        triggers = [t["Event"] for t in row.get("Triggers") or []]
        if sid in INV_DECAYING:
            # plan §G10 -- stacks are the clock, and it is a TurnEnded trigger
            # that ticks them down (DurationTurns merges with `max`, so two
            # applications of "2" would give 2 turns instead of 4).
            if triggers != ["TurnEnded"]:
                fail("status." + sid, "expected exactly one TurnEnded trigger, got %s"
                     % triggers)
            elif program_facts(row["Triggers"][0]["Program"]["Root"]) != \
                    [("modify", sid, -1, "source")]:
                fail("status." + sid, "decay trigger is not modifyStatusStacks(-1) on self: %s"
                     % program_facts(row["Triggers"][0]["Program"]["Root"]))
            if row.get("UsesDuration") is not False:
                fail("status." + sid, "UsesDuration must be false (plan §G10), got %r"
                     % row.get("UsesDuration"))
            if row.get("UsesStacks") is not True:
                fail("status." + sid, "UsesStacks must be true (plan §G10), got %r"
                     % row.get("UsesStacks"))
        elif sid in ("standard.lose_strength", "standard.lose_dexterity",
                     "standard.regain_strength"):
            # §158: the "give back what Flex / Speed Potion lent" half. Two modifications, both by
            # an **expression** (`subtract(0, stacks)` -- the kernel has no `negate`, expr.rs:50),
            # and the order is part of the fact: the matched status first, then itself. Removing
            # the instance first would make its own stacks read 0 and the debt would be free.
            lends = {"standard.lose_strength": "standard.strength",
                     "standard.lose_dexterity": "standard.dexterity",
                     # §219：镜像 —— 回合末**加回**力量
                     "standard.regain_strength": "standard.strength"}[sid]
            if triggers != ["TurnEnded"]:
                fail("status." + sid, "expected exactly one TurnEnded trigger, got %s" % triggers)
            else:
                facts = program_facts(row["Triggers"][0]["Program"]["Root"])
                # §219：`regain_strength` 是 `lose_strength` 的镜像 —— 回合末**加回**力量。
                sign = "add" if sid == "standard.regain_strength" else "subtract"
                expected = [("modify", lends, ("expr", sign), "source"),
                            ("modify", sid, ("expr", "subtract"), "source")]
                if facts != expected:
                    fail("status." + sid, "the give-back program is %s, expected %s"
                         % (facts, expected))
        elif sid in ("standard.thorns", "standard.spore_cloud", "standard.enrage",
                     "standard.regen", "standard.rage", "standard.flame_barrier",
                     "standard.combust", "standard.split", "standard.phase_split",
                     "standard.time_warp", "standard.constricted",
                     "standard.phantom_veil",
                     "standard.sharp_hide", "standard.curiosity", "standard.mode_shift",
                     "standard.stasis", "standard.flying",
                     "standard.curl_up", "standard.plated_armor", "standard.hex",
                     # §227: Nightmare 的"下一回合"载体 —— `TurnStarted` 触发器。
                     "standard.nightmare_pending",
                     # §231: Battle Trance 的"本回合不能再抽" —— `TurnEnded` 自摘。
                     "standard.no_draw",
                     # §235: Demon Form —— 每回合开始加力量（`TurnStarted`）。
                     "standard.demon_form",
                     # §236: Brutality（TurnStarted）与 Rupture（HpLost）。
                     "standard.brutality", "standard.rupture",
                     # §256
                     "standard.painful_stabs",
                     "standard.lagavulin_asleep",
                     # §260
                     "standard.orichalcum", "standard.mercury_hourglass", "standard.horn_cleat",
                     "standard.captains_wheel", "standard.stone_calendar", "standard.cloak_clasp",
                     "standard.incense_burner", "standard.pocketwatch",
                     # §261
                     "standard.lantern", "standard.bag_of_preparation", "standard.ice_cream",
                     "standard.calipers",
                     # §262
                     "standard.kunai", "standard.shuriken", "standard.ornamental_fan",
                     "standard.letter_opener", "standard.nunchaku", "standard.ink_bottle",
                     "standard.pen_nib", "standard.double_damage",
                     # §263
                     "standard.gremlin_horn", "standard.the_specimen", "standard.the_boot",
                     "standard.torii", "standard.tungsten_rod", "standard.poison",
                     # §264：**只有 champion_belt 有触发器**；paper_phrog / paper_krane 是
                     # 纯修饰器载体（改写别的状态），所以它们在 `INV_STATUSES` 那张表里。
                     "standard.champion_belt",
                     # §267
                     "standard.ring_of_the_snake",
                     "standard.ring_of_the_serpent",
                     "standard.philosophers_stone",
                     "standard.happy_flower",
                     "standard.art_of_war",
                     "standard.brimstone",
                     "standard.mark_of_pain",
                     "standard.mutagenic_strength",
                     "standard.centennial_puzzle",
                     "standard.runic_cube",
                     "standard.charons_ashes",
                     "standard.duality",
                     "standard.akabeko",
                     # §268（`black_blood` 没有状态）
                     "standard.self_forming_clay", "standard.bird_faced_urn",
                     "standard.runic_pyramid", "standard.lizard_tail", "standard.unceasing_top",
                     # §269
                     "standard.slavers_collar", "standard.busted_crown", "standard.ectoplasm",
                     # §237: the five trigger-hook powers.
                     "standard.juggernaut", "standard.evolve", "standard.fire_breathing",
                     "standard.dark_embrace", "standard.feel_no_pain",
                     # §244
                     "standard.mayhem", "standard.magnetism",
                     # §249：四个触发器 power（The Bomb 的记账搭档没有触发器）。
                     "standard.omega", "standard.panache", "standard.sadistic_nature",
                     "standard.the_bomb"):
            expected = {"standard.thorns": ["DamageTaken"],
                        "standard.spore_cloud": ["Downed"],
                        "standard.enrage": ["CardPlayed"],
                        "standard.regen": ["TurnEnded"],
                        "standard.rage": ["CardPlayed"],
                        "standard.flame_barrier": ["DamageTaken"],
                        "standard.combust": ["TurnEnded"],
                        "standard.split": ["Downed"],
                        "standard.phase_split": ["DamageTaken"],
                        "standard.time_warp": ["CardPlayed"],
                        # §147: "lose HP at the end of your turn" is a TurnEnded trigger.
                        "standard.constricted": ["TurnEnded"],
                        # §175: the first `TurnStarted` trigger in this package.
                        "standard.phantom_veil": ["TurnStarted"],
                        # §235: Demon Form —— 每回合开始加力量。
                        "standard.demon_form": ["TurnStarted"],
                        # §236
                        "standard.brutality": ["TurnStarted"],
                        "standard.rupture": ["HpLost"],
                        # §256：Book of Stabbing 的 Painful Stabs（`DamageDealt` 的 bearer 是**出手方**）。
                        "standard.painful_stabs": ["DamageDealt"],
                        # §257：Lagavulin 的 Asleep。`DamageTaken`（bearer = **挨打的那个**）负责
                        # "被打掉血就醒"，`TurnStarted` 负责"睡满三回合自己醒"。
                        "standard.lagavulin_asleep": ["DamageTaken", "TurnStarted"],
                        # §260：八件遗物的载体状态。
                        "standard.orichalcum": ["TurnEnded"],
                        "standard.mercury_hourglass": ["TurnStarted"],
                        "standard.horn_cleat": ["TurnStarted"],
                        "standard.captains_wheel": ["TurnStarted"],
                        "standard.stone_calendar": ["TurnEnded"],
                        "standard.cloak_clasp": ["TurnEnded"],
                        "standard.incense_burner": ["TurnStarted"],
                        "standard.pocketwatch": ["TurnStarted"],
                        # §261
                        "standard.lantern": ["TurnStarted"],
                        "standard.bag_of_preparation": ["TurnStarted"],
                        # 这两条**故意**没有触发器：规则由内核读标签实现。
                        "standard.ice_cream": [],
                        "standard.calipers": [],
                        # §262：七条都是 `CardPlayed`；翻倍载体自己也带一条（下一张攻击打完摘掉自己）。
                        "standard.kunai": ["CardPlayed"],
                        "standard.shuriken": ["CardPlayed"],
                        "standard.ornamental_fan": ["CardPlayed"],
                        "standard.letter_opener": ["CardPlayed"],
                        "standard.nunchaku": ["CardPlayed"],
                        "standard.ink_bottle": ["CardPlayed"],
                        "standard.pen_nib": ["CardPlayed"],
                        "standard.double_damage": ["CardPlayed"],
                        # §263
                        "standard.gremlin_horn": ["FoeDowned"],
                        "standard.the_specimen": [],
                        "standard.the_boot": [],
                        "standard.torii": [],
                        "standard.tungsten_rod": [],
                        # §263：毒的自减是 `TurnEnded`（"层数就是时钟"，与 vulnerable/weak 同一写法）。
                        "standard.poison": ["TurnEnded"],
                        # §237
                        "standard.juggernaut": ["BlockGained"],
                        "standard.evolve": ["CardsDrawn"],
                        "standard.fire_breathing": ["CardsDrawn"],
                        "standard.dark_embrace": ["CardExhausted"],
                        "standard.feel_no_pain": ["CardExhausted"],
                        # §244
                        "standard.mayhem": ["TurnStarted"],
                        "standard.magnetism": ["TurnStarted"],
                        # §249
                        "standard.omega": ["TurnEnded"],
                        "standard.panache": ["CardPlayed"],
                        "standard.sadistic_nature": ["StatusApplied"],
                        "standard.the_bomb": ["TurnEnded"],
                        # §231: Battle Trance 的"本回合不能再抽" —— 一条 TurnEnded 自摘触发器
                        # （规则本身在内核的抽牌节点里）。
                        "standard.no_draw": ["TurnEnded"],
                        # §194: the Guardian's Sharp Hide and the Awakened One's Curiosity -- both
                        # `CardPlayed` filtered by the played card's tag, the Enrage shape.
                        "standard.sharp_hide": ["CardPlayed"],
                        "standard.curiosity": ["CardPlayed"],
                        # §195.1: "after losing X HP" is a `DamageTaken` trigger (the event now carries
                        # the amount).
                        "standard.mode_shift": ["DamageTaken"],
                        # §195.4: "on death, the stolen card is returned" -- a Downed trigger.
                        "standard.stasis": ["Downed"],
                        # §216: Slow has **no** trigger any more -- the count lives in the kernel's
                        # `cards_played_this_turn`, so it is checked by `INV_TIME_VARIABLES` and by
                        # the modifier row (`INV_STATUSES`), not by a content trigger.
                        # §208: Byrd's Flying -- loses a stack when hit by an **attack**.
                        "standard.flying": ["DamageTaken"],
                        # §209: "the first time this enemy takes damage" -- a DamageTaken trigger.
                        "standard.curl_up": ["DamageTaken"],
                        # §210: "lose a stack on unblocked **attack** damage" -- the decrement moved
                        # out of `exec.rs` S6c, which could not tell poison from an attack.
                        "standard.plated_armor": ["DamageTaken"],
                        # §213: "whenever you play a non-Attack card" -- a CardPlayed trigger.
                        "standard.hex": ["CardPlayed"],
                        # §227: "next turn, add the copies to your hand" -- a `TurnStarted` trigger
                        # (the second one in this package, after Phantom Veil).
                        "standard.nightmare_pending": ["TurnStarted"],
                        # §264: "whenever you apply Vulnerable" -- a StatusApplied trigger whose
                        # condition is `event.statusIs(vulnerable)`.
                        # §267
                        "standard.ring_of_the_snake": ['TurnStarted'],
                        "standard.ring_of_the_serpent": [],
                        "standard.philosophers_stone": [],
                        "standard.happy_flower": ['TurnStarted'],
                        "standard.art_of_war": ['CardPlayed', 'TurnEnded', 'TurnStarted'],
                        "standard.brimstone": ['TurnStarted'],
                        "standard.mark_of_pain": ['TurnStarted'],
                        "standard.mutagenic_strength": ['TurnEnded'],
                        # §267：伤害与"失去生命"是**两条路**，掉血类遗物两条都要听。
                        "standard.centennial_puzzle": ['DamageTaken', 'HpLost'],
                        "standard.runic_cube": ['DamageTaken', 'HpLost'],
                        "standard.charons_ashes": ['CardExhausted'],
                        "standard.duality": ['CardPlayed'],
                        "standard.akabeko": ['CardPlayed'],
                        # §268
                        "standard.self_forming_clay": ['DamageTaken', 'HpLost', 'TurnStarted'],
                        "standard.bird_faced_urn": ['CardPlayed'],
                        "standard.runic_pyramid": [],
                        "standard.lizard_tail": [],
                        "standard.unceasing_top": ['CardPlayed'],
                        # §269（两条能量载体都没有触发器）
                        "standard.slavers_collar": [],
                        "standard.busted_crown": [],
                        # §270
                        "standard.ectoplasm": [],
                        "standard.champion_belt": ["StatusApplied"]}[sid]
            if triggers != expected:
                fail("status." + sid, "expected exactly %s, got %s" % (expected, triggers))
        elif sid != "ritual" and triggers:
            # `ritual` is checked separately below (it *needs* a TurnEnded
            # trigger); every other status in this subset must be trigger-free.
            fail("status." + sid, "unexpected trigger(s) %s" % triggers)
    # `ritual` is the only status that *changes* another status on a tick.
    ritual = statuses.get("ritual") or {}
    facts = program_facts(ritual["Triggers"][0]["Program"]["Root"]) \
        if ritual.get("Triggers") else []
    if not facts or facts[0][0] != "status" or facts[0][1] != "standard.strength":
        fail("status.ritual", "first tick fact must be applyStatus(standard.strength), got %s"
             % facts)
    ok("statuses", "%d rows x (modifiers, turn clock)" % len(INV_STATUSES))


def check_conditional_else(doc):
    """§262 的地雷：`conditional.Else` 里放**请求节点**会 `Exec(Modifier)` 炸掉。

    复现（§262，二分记录）：`conditional(gate, seq(cond, bump))` 失败；
    `Else = seq()`（空）正常；同一个 `bump` 放在 `Then` 里也正常。
    症状是 `Exec(Modifier)` —— 现场看起来像"层数写负了"，实际是续延在嵌套 conditional 的
    假分支上把帧提前退掉了。内核那笔债还没还（`exec.rs` 的 `resume_later` 路径），
    所以这里**先挡住内容**：本内容一律不用 `Else`。

    内容需要"否则"时，写成平铺的两条 `conditional`（`and(...)` 之类组合条件），或者
    把不需要的分支留空。要真正解锁 `Else`，先修内核并加一条"嵌套 conditional 返回后兄弟节点
    仍能派发"的判据 —— 那时删掉这条检查。
    """
    print("[9] conditional.Else (kernel debt, §262)")

    def walk(where, node, path):
        if not isinstance(node, dict):
            return
        kind = node.get("kind")
        value = node.get("value") or {}
        if kind == "node.conditional":
            otherwise = value.get("Else")
            if otherwise not in (None, {}):
                if not (isinstance(otherwise, dict) and otherwise.get("kind") == "node.sequence"
                        and not ((otherwise.get("value") or {}).get("Children"))):
                    fail(where, "conditional.Else is used at %s -- see check_conditional_else "
                                "(it faults with Exec(Modifier) today)" % path)
        for key, child in value.items():
            walk(where, child, path + "/" + key)
        if isinstance(node, list):
            pass

    for section, rows in (("Statuses", doc.get("Statuses") or []),
                          ("Cards", doc.get("Cards") or []),
                          ("EnemyActions", doc.get("EnemyActions") or []),
                          ("Events", doc.get("Events") or []),
                          ("Relics", doc.get("Relics") or [])):
        for row in rows:
            walk("%s.%s" % (section, row.get("Id")), row, "")
    ok("conditional.Else", "unused everywhere (flatten instead)")

def check_relations(doc):
    print("[5] cross references (deck/encounters/actions/statuses)")
    cards = {c["Id"] for c in doc.get("Cards") or []}
    actions = {a["Id"] for a in doc.get("EnemyActions") or []}
    statuses = {s["Id"] for s in doc.get("Statuses") or []}
    roster = {m["Id"]: m for m in doc.get("Monsters") or []}

    hands = {
        "Start.Deck": (doc.get("Start") or {}).get("Deck") or [],
        "root Deck": doc.get("Deck") or [],
        "Characters[0].Start.Deck":
            ((doc.get("Characters") or [{}])[0].get("Start") or {}).get("Deck") or [],
    }
    want = []
    for cid, count in sorted(INV_DECK.items()):
        want.extend([cid] * count)
    for where, deck in hands.items():
        got = [c["value"] for c in deck]
        if sorted(got) != sorted(want):
            fail("deck." + where, "%s, inv (inv:§2.1) says %s" % (got, want))
        for cid in got:
            if cid not in cards:
                fail("deck." + where, "references card %r with no CARD row" % cid)
    # Start == Characters[0].Start (the reference duplicates it; a drift between
    # the two would be invisible to any single read).
    start = doc.get("Start") or {}
    char_start = ((doc.get("Characters") or [{}])[0].get("Start") or {})
    if start != char_start:
        fail("Start", "Start and Characters[0].Start disagree: %s"
             % diff(start, char_start, "Start"))

    # every action a monster lists must exist
    for mid, entry in sorted(roster.items()):
        for ref in entry.get("Actions") or []:
            if ref["value"] not in actions:
                fail("monster." + mid, "action %r has no EACT row" % ref["value"])

    # every encounter's inline enemy record must equal the roster's, field by field
    for enc in doc.get("Encounters") or []:
        eid = enc["Id"]["Value"]
        if eid in INV_WEAK_POOL:
            pool = INV_WEAK_POOL
        elif eid in INV_ELITE_POOL:
            pool = INV_ELITE_POOL
        else:
            pool = INV_BOSS_POOL
        if eid not in pool:
            fail("encounter." + eid,
                 "not in the inventory's weak (inv:§5.2), elite (inv:§5.3) or boss (inv:§4.3) pool")
        listed = [e["Id"] for e in enc.get("Enemies") or []]
        if listed != pool.get(eid):
            fail("encounter." + eid, "enemies %s, the inventory says %s"
                 % (listed, pool.get(eid)))
        # `CardsDrawnPerTurn` null = the per-turn draw default, which inv:§2 says
        # is 5.  Writing a number here would be a second place the draw count lives.
        if enc.get("CardsDrawnPerTurn") is not None:
            fail("encounter." + eid,
                 "CardsDrawnPerTurn must stay null (= inv:§2's %d-card default), got %r"
                 % (INV_HERO["CardsDrawnPerTurn"], enc.get("CardsDrawnPerTurn")))
        # §140: the **same** cap the kernel enforces for summons applies to what the content may
        # place directly. A five-enemy encounter would build fine at runtime and then be unable to
        # show or target the fifth -- better to refuse it here.
        if len(enc.get("Enemies") or []) > MAX_ENEMIES_IN_FIGHT:
            fail("encounter." + eid, "%d enemies, the cap is %d"
                 % (len(enc.get("Enemies") or []), MAX_ENEMIES_IN_FIGHT))
        for inline in enc.get("Enemies") or []:
            mid = inline["Id"]
            entry = roster.get(mid)
            if entry is None:
                fail("encounter." + eid, "enemy %r is not in the roster" % mid)
                continue
            for key in ("Actions", "IntentRules", "StartingStatuses"):
                if inline.get(key) != entry.get(key):
                    fail("encounter.%s/%s" % (eid, mid),
                         "%s differs from the roster: %s"
                         % (key, diff(entry.get(key), inline.get(key), key)))
            if inline.get("MaxHealth") != entry.get("MaxHealth"):
                fail("encounter.%s/%s" % (eid, mid),
                     "MaxHealth %r != roster %r"
                     % (inline.get("MaxHealth"), entry.get("MaxHealth")))
        energy = {(r["Resource"]["value"], r["Current"], r["Max"])
                  for r in enc.get("HeroResources") or []}
        if ("standard.energy", INV_HERO["EnergyCurrent"], INV_HERO["EnergyMax"]) not in energy:
            fail("encounter." + eid, "hero energy %s, inv:§2 says 3/3" % sorted(energy))

    # every status a program names must have a STAT row
    def named_statuses(facts):
        for fact in facts:
            if fact[0] == "status" or fact[0] == "modify":
                yield fact[1]

    for rec in (doc.get("Cards") or []) + (doc.get("EnemyActions") or []):
        for sid in named_statuses(program_facts(rec["Program"]["Root"])):
            if sid not in statuses:
                fail("program." + rec["Id"], "names status %r with no STAT row" % sid)
    for rec in doc.get("Statuses") or []:
        for trig in rec.get("Triggers") or []:
            for sid in named_statuses(program_facts(trig["Program"]["Root"])):
                if sid not in statuses:
                    fail("trigger." + rec["Id"], "names status %r with no STAT row" % sid)

    ok("deck", "3 spellings, %d cards each" % len(want))
    ok("encounter <-> roster", "%d encounters, inline records equal the roster"
       % len(doc.get("Encounters") or []))


def check_weak_pool_table(doc):
    print("[6] encounter weights (inv:§5.2)")
    table = (doc.get("EncounterTables") or {}).get("Weak") or []
    got = {row["Id"]: row["Weight"] for row in table}
    if sorted(got) != sorted(INV_ACT_TABLES["Weak"]):
        fail("EncounterTables.Weak", "%s != act 1 %s (inv:§5.2)"
             % (sorted(got), sorted(INV_ACT_TABLES["Weak"])))
    ok("weak pool", "%d entries x %d%%" % (len(table), INV_WEAK_WEIGHT))
    elite = (doc.get("EncounterTables") or {}).get("Elite")
    if elite is None:
        fail("encounter-tables", "EncounterTables.Elite is missing (inv:§5.3)")
    if sorted(e["Id"] for e in elite) != sorted(INV_ACT_TABLES["Elite"]):
        fail("encounter-tables", "Elite %s != inv %s"
             % (sorted(e["Id"] for e in elite), sorted(INV_ELITE_POOL)))
    ok("elite pool", "%d entry" % len(elite))
    boss = (doc.get("EncounterTables") or {}).get("Boss")
    if boss is None:
        fail("encounter-tables", "EncounterTables.Boss is missing (inv:§4.3)")
    # §130: acts 2 and 3 have their own Weak/Elite/Boss pools. Each is checked against the same
    # inventory: a pool that names an encounter the kernel cannot build is the same bug regardless
    # of which act it belongs to.
    for act in (2, 3):
        for kind in ("Weak", "Elite", "Boss"):
            name = "%s%d" % (kind, act)
            rows = (doc.get("EncounterTables") or {}).get(name)
            if rows is None:
                fail("encounter-tables", "EncounterTables.%s is missing" % name)
                continue
            ids = sorted(row["Id"] for row in rows)
            if ids != sorted(INV_ACT_TABLES[name]):
                fail("encounter-tables", "%s %s != act %d %s"
                     % (name, ids, act, sorted(INV_ACT_TABLES[name])))
    if sorted(e["Id"] for e in boss) != sorted(INV_ACT_TABLES["Boss"]):
        fail("encounter-tables", "Boss %s != act 1 %s"
             % (sorted(e["Id"] for e in boss), sorted(INV_ACT_TABLES["Boss"])))


# §143: the event choices' closed vocabulary, checked **here** rather than only when a player
# clicks the button. `EventEffect::parse` in `rd-run` is the authority on the shape; this gate is
# the authority on the **payloads**, which the run layer cannot check on its own (it does not know
# the content): a `curse:` id must be a Curse card in the pool, and a `relic:` id must be a relic
# whose effect the kernel implements.
EVENT_BARE_EFFECTS = ("heal", "gold", "damage", "max_hp", "nothing",
                      "remove_card", "upgrade_card", "transform_card")
# Mirrors `rd_run::state::RunState::relic_effect`. Kept as a literal list on purpose: this file is
# the **second opinion** -- if the two disagree, one of them is wrong and the gate says so.
IMPLEMENTED_RELICS = ("burning_blood", "anchor", "vajra", "pear", "blood_vial", "thread_and_needle",
                      # §156: wiki numbers (Strawberry +7 max HP, Bronze Scales 3 Thorns, Regal Pillow
                      # +15 on rest, Meat on the Bone 12 HP at or below 50%).
                      "strawberry", "bronze_scales", "regal_pillow", "meat_on_the_bone",
                      # §157: two more Rare (Eternal Feather, Golden Idol) + Potion Belt.
                      "eternal_feather", "golden_idol", "potion_belt",
                      # §221/§224: `oddly_smooth_stone` = 1 Dexterity **on the hero** at combat
                      # start; `bag_of_marbles` = 1 Vulnerable **on every enemy** -- the latter needs
                      # `RelicEffect::StartCombatStatusOnEnemies` (the hero-shaped variant made the
                      # *hero* Vulnerable, which `ACT1_SLICE` caught as an unwinnable boss).
                      "bag_of_marbles", "oddly_smooth_stone",
                      # §259: the seven campfire relics. Three **open** an option (`girya` Lift,
                      # `peace_pipe` Toke, `shovel` Dig), two **close** Rest (`coffee_dripper`,
                      # `mark_of_the_bloom`), one closes Smith (`fusion_hammer`), one adds a card
                      # reward to Rest (`dream_catcher`).
                      "girya", "peace_pipe", "shovel", "coffee_dripper", "mark_of_the_bloom",
                      "fusion_hammer", "dream_catcher",
                      # §260: 战斗开始类 / 回合末类八件 —— 全部是 `StartCombatStatus`，
                      # 规则在内容状态里（`TurnStarted` / `TurnEnded` 触发器）。
                      "orichalcum", "mercury_hourglass", "horn_cleat", "captains_wheel",
                      "stone_calendar", "cloak_clasp", "incense_burner", "pocketwatch",
                      # §261: 战斗开始类五件 —— 两条走 `TurnStarted`（第 1 回合），
                      # 两条走**标签**（内核回合机读），一条走 `per_curse`（数牌组）。
                      "lantern", "bag_of_preparation", "ice_cream", "calipers", "du_vu_doll",
                      # §262: "每第 N 张某类型牌"七件 —— 全部 `CardPlayed` 触发器 + 自己的计数器。
                      "kunai", "shuriken", "ornamental_fan", "letter_opener", "nunchaku",
                      "ink_bottle", "pen_nib",
                      # §263: 敌人死亡类两件 + 伤害管线数值改写三件。
                      "gremlin_horn", "the_specimen", "the_boot", "torii", "tungsten_rod",
                      # §264: 改写别的状态幅值两件 + 施加易伤时附带虚弱一件。
                      "paper_phrog", "paper_krane", "champion_belt",
                      # §265: 改状态施加三件 + 开战给敌人上毒一件。
                      "snecko_skull", "ginger", "turnip", "twisted_funnel",
                      # §266: 条件修饰器 + 同侧改写。
                      "red_skull", "odd_mushroom",
                      # §267: 零基建批次。
                      "ring_of_the_snake", "ring_of_the_serpent", "philosophers_stone", "happy_flower", "art_of_war", "brimstone", "mark_of_pain", "mutagenic_strength", "centennial_puzzle", "runic_cube", "charons_ashes", "duality", "akabeko", "clockwork_souvenir", "red_mask", "gremlin_visage", "fossilized_helix", "mango",
                      # §268: 零基建档收尾。
                      "self_forming_clay", "bird_faced_urn", "runic_pyramid", "lizard_tail",
                      "unceasing_top", "black_blood",
                      # §269: 战斗类型层 + 奖励层。
                      "preserved_insect", "pantograph", "slavers_collar", "sling_of_courage",
                      "question_card", "busted_crown", "prayer_wheel", "white_beast_statue",
                      "black_star",
                      # §270: 加牌类 + 金币/商店类。
                      "omamori", "ceramic_fish", "darkstone_periapt", "molten_egg", "toxic_egg",
                      "frozen_egg", "bloody_idol", "ectoplasm", "maw_bank", "membership_card",
                      "smiling_mask")


def check_relics(doc):
    """§145：遗物池里的**每一件**都必须被内核实现。

    这不是洁癖：宝箱和商店都是从这张表里随机挑一件，所以一件内核跑不了的遗物不是"躺在那里
    没人用"，而是**随机地把玩家的宝箱变成一次拒绝**（`push_relic` 在授予那一刻就报错）。
    `RunState::relic_effect` 是内核那边的表；这里是它的第二张嘴。
    """
    print("[6e] relic pool (port-plan.md §145)")
    relics = doc.get("Relics") or []
    if len(relics) < 2:
        fail("Relics", "只有 %d 件遗物 —— 池子至少要能让一次掉落有得选" % len(relics))
    for relic in relics:
        relic_id = relic.get("Id")
        if relic_id not in IMPLEMENTED_RELICS:
            fail("Relics.%s" % relic_id,
                 "内核没实现这件遗物的效果（%s）⇒ 宝箱抽到它会当场拒绝"
                 % " / ".join(IMPLEMENTED_RELICS))
        if not relic.get("DisplayName"):
            fail("Relics.%s" % relic_id, "没有 DisplayName（页面上会是一串 id）")
    # A relic that exists in the kernel's table but not in the content can never be handed out
    # either -- say so once, in the other direction.
    declared = {relic.get("Id") for relic in relics}
    for relic_id in IMPLEMENTED_RELICS:
        if relic_id not in declared:
            fail("Relics", "内核实现了 `%s`，但内容里没有它 ⇒ 永远发不出来" % relic_id)
    ok("relic pool", "%d relics, all implemented" % len(relics))


# §152: the potion vocabulary, as the ABI's `rd_env_use_potion` reads it. `kind:payload` carries a
# status id; the payload form is the same convention the event vocabulary uses (§143).
# §161.3: the two atoms whose effect is a **question** (`PendingChoice`). They read no amount and
# they do not resolve inside `rd_env_use_potion` -- the ABI returns "pending" and the answer arrives
# through `rd_env_choice_confirm`.
POTION_CHOICE_KINDS = ("choice_hand_exhaust", "choice_hand_discard_draw",
                       "choice_discard_to_hand", "choice_offered")
POTION_KINDS = ("combat_block", "combat_energy", "combat_heal_percent", "combat_draw",
                "combat_damage", "combat_damage_all",
                # §179: the three potions that needed a new verb (Blessing of the Forge, Snecko
                # Oil, Smoke Bomb). Listed here as the **second opinion** -- §161.3 taught that a
                # vocabulary known in two places drifts unless both are checked.
                "combat_upgrade_hand", "combat_randomize_costs", "combat_flee",
                # §182: auto-play reads the count, so it is **not** in `NO_AMOUNT`.
                "combat_autoplay_top",
                # §157/§158: the effects that are about the **run**, not the fight (Fruit Juice,
                # Entropic Brew). §158 made them usable **outside** a fight, which is what the wiki
                # says; before that the "no fight" check came first and refused them.
                "max_hp", "potion_fill") + POTION_CHOICE_KINDS
# Which effects need the player to pick an enemy (the ABI's code `1`). Kept here as the **second
# opinion**: if the page's rule and this list disagree, one of them is wrong.
POTION_NEEDS_TARGET = ("combat_damage", "combat_status_target")


# The tags a card can carry and still be upgraded at a campfire. Curses and statuses cannot.
# §183: `colorless` joins the list, and the reason is **not** "they cannot be upgraded" (in StS they
# can) -- it is that **no deck can ever hold them**: the only way a colorless card enters play is a
# potion's offer, inside one fight. A `+` row would be content nothing can reach, and inventing three
# upgrades whose wiki numbers nobody read is worse than saying so.
NOT_UPGRADABLE_TAGS = ("curse", "status", "colorless")


def check_upgrades(doc):
    """§154: **every upgradable card must have a `+` row.**

    The run's upgrade path is "append `+` to the id" (`RunState::upgrade_at`), so a card without an
    upgraded row becomes an id the image does not contain: the run looks fine until the next fight,
    which then refuses to build (`UnknownCard(CardDefinitionId("iron_wave+"))`). §147 fixed exactly
    one card and wrote the lesson down; nine others still had no row.
    """
    print("[3c] card upgrades (port-plan.md §154)")
    cards = {card["Id"]: card for card in doc.get("Cards") or []}
    missing = []
    for card_id, card in cards.items():
        if card_id.endswith("+"):
            continue
        tags = [tag["value"] for tag in card.get("Tags") or []]
        if any(tag in NOT_UPGRADABLE_TAGS for tag in tags):
            continue
        if card_id + "+" not in cards:
            missing.append(card_id)
    if missing:
        fail("cards.upgrades", "no `+` row for %s" % (missing,))
    # An upgraded row may be **cheaper** but never more expensive, and must keep the same tags.
    #
    # ⚠️ §197 修正了一条**假不变量**：这里原来要求"`+` 行的费必须和基础行一样"。那不是 StS ——
    # 降费升级是**最常见**的一类升级（Barricade 3→2、Blur 1→0、Body Slam 1→0 …），而内核每次出牌
    # 读的就是那一行的 `Costs`，所以内容本来就表达得了。原来那条规则会让"想写对的人"被迫写错，
    # 于是内容与检查器**一起**错还全绿 —— 正是审阅 §4.2 说的那种绿。
    for card_id, card in cards.items():
        if not card_id.endswith("+"):
            continue
        base = cards.get(card_id[:-1])
        if base is None:
            fail("cards.upgrades", "%s has no base row" % (card_id,))
            continue
        base_cost = [cost.get("Amount") for cost in base.get("Costs") or []]
        up_cost = [cost.get("Amount") for cost in card.get("Costs") or []]
        if any(up > base for up, base in zip(up_cost, base_cost)) or len(up_cost) != len(base_cost):
            fail("cards.upgrades", "%s costs MORE than %s (%r > %r)"
                 % (card_id, card_id[:-1], up_cost, base_cost))
        # §223：升级行**可以少一个 `ethereal`** —— wiki 的 Apparition 就是"升级去掉 Ethereal"，
        # 一刀切会让正确内容被判错。其它差别仍然红（"升级顺手换了类型/关键字"是抄写错误）。
        base_tags = [tag["value"] for tag in base.get("Tags") or []]
        up_tags = [tag["value"] for tag in card.get("Tags") or []]
        # §236：升级行**可以多一个 `innate`** —— wiki 把 Brutality 的升级写成
        # `(;{{KW|Innate}}. / )At the start of your turn…`，那个括号就是"基础;升级"。
        # 与 §223 的"升级可以少一个 ethereal"对称：两处都是**升级改变关键字**的真实写法，
        # 一刀切会把正确内容判错。
        if (
            up_tags != base_tags
            and up_tags != [tag for tag in base_tags if tag != "ethereal"]
            and up_tags != base_tags + ["innate"]
        ):
            fail("cards.upgrades", "%s has different tags from %s" % (card_id, card_id[:-1]))
    upgraded = sum(1 for card_id in cards if card_id.endswith("+"))
    ok("card upgrades", "%d upgraded rows, every upgradable card has one" % upgraded)


def check_potions(doc):
    """§152: every potion must be **drinkable**.

    Before this section the content had five potions built from three effects and two of them were
    broken: `swift_potion` was a second Block Potion under a different name, and `blood_potion` used
    an effect the ABI did not handle at all (refused with "未知的药水效果"). A potion that cannot be
    drunk is a dead button in the belt -- the §150 shape, one layer down.
    """
    print("[3b] potions (port-plan.md §152, §158)")
    potions = doc.get("Potions") or []
    statuses = {status["Id"] for status in doc.get("Statuses") or []}
    # §161.5: every tag any card carries -- `choice_offered:<tag>` payloads must be one of these.
    tags = {tag.get("value") for card in doc.get("Cards") or []
            for tag in card.get("Tags") or []}
    seen_effects = set()
    for potion in potions:
        potion_id = potion.get("Id")
        effect = potion.get("Effect") or ""
        label = "Potions.%s" % potion_id
        amount = potion.get("Amount")
        if not potion.get("NameKey") or not potion.get("DescriptionKey"):
            fail(label, "needs NameKey and DescriptionKey (the belt shows the id otherwise)")
        # §158: an effect is a **comma-separated list of atoms**. Every atom is checked on its own,
        # for the same reason the run layer executes them one at a time: `combat_status:a` and
        # `combat_status:zzz` in the same cell must not pass because the first one was fine.
        atoms = [atom for atom in effect.split(",") if atom]
        if not atoms:
            fail(label, "no Effect at all")
        for atom in atoms:
            kind, _, payload = atom.partition(":")
            if kind in POTION_KINDS:
                if payload and kind != "choice_offered":
                    fail(label, "`%s` takes no payload" % kind)
                if kind == "choice_offered":
                    # §161.5: the payload is a **tag**, and the promise is "three of them exist".
                    # 少于三张时这瓶药给不出它写的东西 —— 那正是一个安静的死按钮。
                    if payload not in tags:
                        fail(label, "`choice_offered` names tag %r, which no card carries"
                             % (payload,))
                    else:
                        carriers = sum(1 for card in doc.get("Cards") or []
                                       if any(t.get("value") == payload
                                              for t in card.get("Tags") or []))
                        if carriers < 3:
                            fail(label, "`choice_offered:%s` needs 3 cards carrying it, %d exist"
                                 % (payload, carriers))
            elif kind in ("combat_status", "combat_status_target"):
                if payload not in statuses:
                    fail(label, "`%s` names status %r, which is not a STAT row" % (kind, payload))
            else:
                fail(label, "effect %r is outside the ABI's vocabulary" % (atom,))
            # The **target** decision lives in two places on purpose (`rd-wasm`'s
            # `rd_run_potion_effect` and `POTION_NEEDS_TARGET` here): if they disagree, the page aims
            # at nothing and the potion silently lands on the hero.
            wants_target = kind in POTION_NEEDS_TARGET
            if wants_target and any(a.partition(":")[0] not in POTION_NEEDS_TARGET for a in atoms):
                fail(label, "mixes a targeted atom with a non-targeted one")
        # §158: the rule is per-atom, because not every atom reads an amount.
        # §161.3 added the choice atoms, which read none either (the number of cards is the
        # player's answer, not a constant in the content).
        # §179: `combat_flee` takes no amount either (there is nothing to parametrise), and
        # `combat_randomize_costs` only matters when paired with a draw that does.
        NO_AMOUNT = (
            "potion_fill", "combat_flee", "combat_randomize_costs", "combat_upgrade_hand"
        ) + POTION_CHOICE_KINDS
        takes_amount = any(atom.partition(":")[0] not in NO_AMOUNT for atom in atoms)
        if takes_amount:
            if not isinstance(amount, int) or amount <= 0:
                fail(label, "Amount must be a positive integer, got %r" % (amount,))
        elif amount != 0:
            fail(label, "`%s` reads no amount, so it must be 0, got %r"
                 % (atoms[0].partition(":")[0], amount,))
        seen_effects.add(effect)
    if len(potions) < 8:
        fail("Potions", "only %d potions -- too few to make a drop interesting" % len(potions))
    # Two potions with the same effect **and** amount are one potion with two names (the exact bug
    # `swift_potion` shipped: a copy of Block Potion).
    fingerprints = [(potion.get("Effect"), potion.get("Amount")) for potion in potions]
    for fingerprint in set(fingerprints):
        if fingerprints.count(fingerprint) > 1:
            names = [p.get("Id") for p in potions if (p.get("Effect"), p.get("Amount")) == fingerprint]
            fail("Potions", "%s are the same potion twice (%r)" % (names, fingerprint))
    # §158: there is **no per-act potion pool**. `PotionTables` used to hold three lists; the wiki
    # has no such split, and `MAX_POOL_IDS` (8) would have truncated a 33-entry list. So the check is
    # now the opposite one: the table must be **gone**, because a leftover list would be data the
    # kernel never reads.
    if doc.get("PotionTables"):
        fail("PotionTables", "the potion pools were removed in §158 -- this is dead data")
    # §157/§158: the rarity weights (65/25/10) are only meaningful if every band has an entry.
    bands = {rarity: 0 for rarity in RELAPSE_RARITIES}
    for potion in potions:
        rarity = potion.get("Rarity")
        if rarity not in bands:
            fail("Potions.%s" % potion.get("Id"), "unknown Rarity %r" % (rarity,))
            continue
        bands[rarity] += 1
    for rarity in RELAPSE_RARITIES:
        if bands[rarity] == 0:
            fail("Potions", "no %s potion: that band of the 65/25/10 roll would be empty" % rarity)
    ok("potions", "%d potions (C%d/U%d/R%d), %d distinct effects"
       % (len(potions), bands["Common"], bands["Uncommon"], bands["Rare"], len(seen_effects)))


RELAPSE_RARITIES = ("Common", "Uncommon", "Rare")


def check_relic_rarities(doc):
    """§156: every relic declares a rarity the drop weights know about.

    The weights are `Common 50 / Uncommon 33 / Rare 17`; a relic whose `Rarity` is missing or spelled
    differently is silently skipped by the pool reader in `rd-wasm` (`Rarity::from_name` returns
    `None`), so it would simply **never drop** -- a relic that exists and cannot be found is worse
    than one that is absent.
    """
    print("[6f] relic rarities (port-plan.md §156, §160)")
    relics = doc.get("Relics") or []
    # §160: `Event` is a **legal** relic rarity that is *not* droppable -- the wiki's navbox puts
    # `golden_idol` there. The kernel's `pick_relic_avoiding` filters any band that is not in
    # `RELIC_RARITY_WEIGHTS`, so an `Event` relic is holdable (and pays out) but never rolled.
    # §259：`Starter` 与 `Boss` 也是**合法但不可掉落**的桶（`Burning Blood` 是起手遗物，
    # `Coffee Dripper` / `Fusion Hammer` 是 Boss 遗物）。它们与 `Event` 同一条道理：桶让"这是什么"
    # 能说实话，而 `pick_relic_avoiding` 只从 `RELIC_RARITY_WEIGHTS` 的三档里抽，所以抽不到。
    # §265：`Shop` 是第四种"合法但不可掉落"的桶（`twisted_funnel` 只在商店卖）。与 `Event`
    # 完全同一条理由：`pick_relic_avoiding` 只从 `RELIC_RARITY_WEIGHTS` 的三档抽，所以这个桶
    # 能持有、能结算，但**永远抽不到**；桶的意义是让"这是什么"说实话。
    allowed = tuple(RELAPSE_RARITIES) + ("Event", "Starter", "Boss", "Shop")
    missing = [relic.get("Id") for relic in relics if relic.get("Rarity") not in allowed]
    if missing:
        fail("Relics.rarity", "no usable Rarity on %s" % (missing,))
    counts = {}
    for relic in relics:
        counts[relic["Rarity"]] = counts.get(relic["Rarity"], 0) + 1
    for rarity in RELAPSE_RARITIES:
        if counts.get(rarity, 0) == 0:
            fail("Relics.rarity", "no %s relic: the weight band would be empty" % rarity)
    ok("relic rarities", "%d relics over %s" % (len(relics), sorted(counts.items())))


def check_card_keywords(doc):
    """§144：关键字必须**落在机制字段上**，tag 只是文档。

    内核读的是 `CARD.TurnEndHandDestinationZone`（Ethereal）、`CARD.RetainInHandOnTurnEnd`
    （Retain）和 `Tags` 里的 `innate`（Innate）。一条 tag 写着 `ethereal`、而那一格还写着
    `DiscardPile` 的卡，在游戏里就是"一张什么关键字都没有的牌" —— 而且**看不出来**。
    这条检查把两边的说法钉在一起。
    """
    print("[6d] card keywords (port-plan.md §144)")
    cards = doc.get("Cards") or []
    counts = {"ethereal": 0, "retain": 0, "innate": 0, "x_cost": 0}
    for card in cards:
        card_id = card.get("Id")
        tags = {tag.get("value") for tag in card.get("Tags") or [] if isinstance(tag, dict)}
        zone = card.get("TurnEndHandDestinationZone") or "DiscardPile"
        retain = card.get("RetainInHandOnTurnEnd") is True
        label = "Cards.%s" % card_id
        # tag ⇔ mechanism, both directions: a mechanism without the tag is a card whose
        # description lies, and a tag without the mechanism is a card that does nothing.
        if ("ethereal" in tags) != (zone == "ExhaustPile"):
            fail(label, "ethereal tag %s but TurnEndHandDestinationZone is %r"
                 % ("present" if "ethereal" in tags else "absent", zone))
        if ("retain" in tags) != retain:
            fail(label, "retain tag %s but RetainInHandOnTurnEnd is %r"
                 % ("present" if "retain" in tags else "absent",
                    card.get("RetainInHandOnTurnEnd")))
        if "x_cost" in tags:
            # §146：X 费现在是真能力，但两条配套约束必须成立，否则那张牌**看起来正常、算起来不对**：
            #   ① 印刷价格必须是 0 或缺席（真正的费用是"当前全部能量"，`Amount` 不参与结算）；
            #   ② 节目必须真的读 `x.cost`（否则那个 tag 只是个装饰，牌会按 0 遍结算）。
            costs = card.get("Costs") or []
            for entry in costs:
                if entry.get("Amount") != 0:
                    fail(label, "x_cost 卡的印刷费用必须是 0（现在是 %r）"
                         % (entry.get("Amount"),))
            program = json.dumps(card.get("Program") or {}, ensure_ascii=False)
            if '"x.cost"' not in program:
                fail(label, "x_cost 卡的节目没读 x.cost ⇒ X 永远用不上（tag 只是装饰）")
        for keyword in counts:
            if keyword in tags:
                counts[keyword] += 1
    ok("keyword cards", "ethereal %d / retain %d / innate %d / x_cost %d"
       % (counts["ethereal"], counts["retain"], counts["innate"], counts["x_cost"]))
    if counts["ethereal"] + counts["retain"] + counts["innate"] == 0:
        fail("Cards", "no card exercises any keyword -- §144 would be untested in the real image")


EVENT_DECK_EDITS = ("remove_card", "upgrade_card", "transform_card")


def check_event_vocabulary(doc):
    """§143 + §188：每个选项是一个**效果列表**，每个效果都在闭词表里。

    三条判据（每一条对应一种没有症状的错误）：
    * 词表外的效果 ⇒ 下面的 `fail`（点下去一个死按钮）；
    * `Effects*Asc` 与基础**一模一样** ⇒ "A15 变糟"什么都没变；
    * 一个选项里**两个改牌效果** ⇒ 待答的选牌只有一个位置，一定丢一个。
    """
    print("[6c] event vocabulary (port-plan.md §143 / §188)")
    rooms = doc.get("UnknownRooms") or []
    cards = {c["Id"]: c.get("Rarity") for c in doc.get("Cards") or []}
    relics = {r["Id"] for r in doc.get("Relics") or []}
    counts = {"bare": 0, "curse": 0, "relic": 0, "effects": 0, "asc": 0}
    for room in rooms:
        for slot in ("0", "1"):
            base = room.get("Effects" + slot) or []
            asc = room.get("Effects" + slot + "Asc") or []
            label = "UnknownRooms.%s.Effects%s" % (room.get("Id"), slot)
            if not isinstance(base, list):
                fail(label, "not a list: %r" % (base,))
                continue
            if len(base) > 4 or len(asc) > 4:
                fail(label, "more than 4 effects (the kernel's MAX_EVENT_EFFECTS)")
            for kind_label, effects in (("", base), ("Asc", asc)):
                edits = 0
                for entry in effects:
                    effect = entry.get("Effect")
                    where = "%s%s.%s" % (label, kind_label, effect)
                    if not isinstance(effect, str):
                        fail(where, "Effect is not a string: %r" % (effect,))
                        continue
                    counts["effects"] += 1
                    if kind_label:
                        counts["asc"] += 1
                    if effect in EVENT_BARE_EFFECTS:
                        counts["bare"] += 1
                        continue
                    kind, _, payload = effect.partition(":")
                    if kind == "curse" and payload:
                        counts["curse"] += 1
                        if payload not in cards:
                            fail(where, "curse:%s 不是内容里的卡" % payload)
                        elif cards[payload] != "Curse":
                            fail(where, "curse:%s 的 Rarity 是 %s，不是 Curse"
                                 % (payload, cards[payload]))
                        continue
                    if kind == "relic" and payload:
                        counts["relic"] += 1
                        if payload not in relics:
                            fail(where, "relic:%s 不在 Relics 表里" % payload)
                        elif payload not in IMPLEMENTED_RELICS:
                            fail(where, "relic:%s 的效果内核没实现（%s）"
                                 % (payload, " / ".join(IMPLEMENTED_RELICS)))
                        continue
                    fail(where, "词表外的效果 %r" % (effect,))
                edits = sum(1 for e in effects if e.get("Effect") in EVENT_DECK_EDITS)
                if edits > 1:
                    fail(label + kind_label,
                         "%d 个改牌效果（待答选牌只有一个位置）" % edits)
            # §188：A15 的变体必须**真的不一样**。
            if asc and asc == base:
                fail(label + "Asc", "the A15 list equals the base -- this ascension does nothing")
    ok("event effects",
       "%d rooms, %d effect(s) (%d in A15 lists), %d bare / %d curse: / %d relic:"
       % (len(rooms), counts["effects"], counts["asc"], counts["bare"],
          counts["curse"], counts["relic"]))
    # The three per-act pools must name rooms that exist, or the `?` room picks nothing.
    known = {room.get("Id") for room in rooms}
    tables = doc.get("EventTables") or {}
    for name in ("Events", "Events2", "Events3"):
        rows = tables.get(name)
        if not rows:
            fail("EventTables." + name, "missing or empty")
            continue
        for row in rows:
            if row.get("Id") not in known:
                fail("EventTables." + name, "%r is not in UnknownRooms" % (row.get("Id"),))
    ok("event pools", "act1=%d act2=%d act3=%d"
       % (len(tables.get("Events") or []), len(tables.get("Events2") or []),
          len(tables.get("Events3") or [])))


# =============================================================================
# 2b.  the fourth layer -- a key that looks like data but is only documentation
# =============================================================================
#
# WHY THIS LAYER EXISTS (measured, not guessed)
# ---------------------------------------------
# The content format has keys that the kernel **never reads**: the storage layer
# keeps them (they round-trip through both images like everything else), so
# filling them in changes *nothing* and reports *nothing*.  Three examples that
# were verified by hand: `STATUS.DeathPrevention` (a reference rule hook with no
# kernel capability), `Program.MaxNodeDepth` (the kernel uses its own
# `MAX_NODE_DEPTH` constant instead), and the root key `Monsters` (the encounter
# carries its own inline copy, which is what reaches `ENCT`).
#
# A round-trip gate cannot see this by construction: "the image agrees with the
# source" is true for an inert key too.  So the rule is a *declaration*:
# every key with no kernel consumer must be listed in the document's
# `InertKeys` block with the reason it can stay.  That turns "silently inert"
# into "explicitly inert", and it makes the two failures that actually happen
# observable:
#   * someone adds a key nobody reads -> red (you must wire it up or declare it);
#   * a declaration outlives its key, or the kernel grows a reader for a
#     declared-inert key -> red (the manifest is not allowed to rot either way).
#
# WHAT IS DERIVED, AND FROM WHERE (no second copy of the truth)
# -------------------------------------------------------------
# "The kernel reads this key" is *derived* by scanning `kernel/**/*.rs`:
#   * accessor calls `.<snake_case>(`  (e.g. `status.polarity()`),
#   * quoted literals `"<Key>"`        (envelopes take cells by name:
#     `int_field("MaxProgramSteps")`).
# `kernel/rd-core/src/content.rs` is excluded: it holds the row-schema mirror and
# the accessors themselves (`death_prevention => 10`), so counting it would make
# every key look consumed.  Test modules are excluded for the same reason --
# `content.rs:2690-2755` asserts that each accessor returns its cell, which
# proves "the cell is readable", not "somebody uses it".  Comment lines are
# dropped so a doc comment mentioning a key cannot fake a consumer.
# Root keys are the exception: the kernel resolves them by *index* (S_CARD,
# S_STAT, ...), so only `root_by_name("<Key>")` counts, and the compiler is the
# thing that decides which root key becomes a row table (`ENTITY_SECTIONS`).
#
# DIRECTION OF THE APPROXIMATION (stated so it cannot be misread): the derived
# rule is **permissive** -- a same-named accessor for another type also counts as
# a consumer.  So it can under-report (fail to demand a declaration), never
# over-report (never call a consumed key inert).  The two checks below fail
# loudly in the direction that matters and say which line/rule decided.
#
# SUB-KEY PATHS (why root-key granularity was not enough -- measured, 2026-10-19)
# ------------------------------------------------------------------------------
# The `root:` scope started at root-key granularity, so "declare the whole key
# inert" was the only way to record a fact.  That is the wrong unit the moment
# the kernel grows a reader for *one field* of that object: wiring `Start` (the
# deck comes from `Start.Deck` / `Characters[0].Start.Deck`) forced the three
# declarations `root:Start` / `root:Characters` / `root:Deck` to be deleted, and
# the facts hanging under them -- `Start.MaxHealth`, `Start.StartingHealth`,
# `Start.Resources`, `Start.StartingRelics`, `Characters[].UnlockFlag` -- went
# with them.  They did not become false, they became **unrecorded**: the only
# place left for them was prose in an ad-hoc document, and prose is not a gate.
#
# So a `root:` declaration may now name a **sub-key path**:
#
#   root:<Parent>.<Field>       one field of the object under root key <Parent>
#   root:<Parent>[].<Field>     one field of every object element of that list
#
# `Statuses[]:` and `Program:` stay flat: those scopes are already per-record key
# sets, so the record *is* the unit.
#
# WHAT COUNTS AS READING A SUB-KEY (two rules, both derived from the kernel)
# -------------------------------------------------------------------------
#   1. a **hop spelling**: a literal that names this hop, `"<Parent>.<Field>"` or
#      `"<Parent>[<digits>].<Field>"`.  The kernel writes its own paths as data
#      (`DeckOrigin::path()` returns `"Characters[0].Start.Deck"` / `"Start.Deck"`
#      / `"Deck"`; `DeckError::Malformed` carries `"Start"`), so a hop it can
#      describe is a hop it reads.
#   2. an **object-field lookup by name**: `name == "<Field>"`.  This is the only
#      way the kernel addresses a content key of a *generic* object (it walks the
#      opcode field table and compares the stored name).
# `content.rs` is **included** for both rules, which is the opposite of the rule
# above and is deliberate: what is excluded there is the *schema mirror*
# (`death_prevention => 10`, `cell("Id", F_STR, 0)`) and the typed accessors, but
# the deck reader and every `name == "..."` comparison are genuine rule code
# living in the same file.
#
# ⚠️ NOT counted, on purpose: `field_at("<Field>")` and `.<snake_case>(`.  Those
# are **typed** accessors -- `EnemySpec::max_health` reads `MaxHealth` off an
# *enemy* record.  Counting them would make `Start.MaxHealth` look consumed (the
# key would then be undeclarable) while the truth is that nothing reads the
# `Start` object's `MaxHealth`: the hero's HP comes from `FightPlan`.  A name
# that two different record types share is exactly where a name-based rule
# cannot decide, and the honest resolution is to keep the yes/no at the
# granularity the kernel can answer (`name ==`, i.e. "the object I am looking at
# must have this field").
#
# ⇒ The known hole, stated so it cannot be discovered as a surprise: if someone
# adds a *typed* reader over the `Start` object (`impl StartRow { fn max_health(&self) { self.field_at("MaxHealth") } }`)
# and calls it, the gate stays green with `root:Start.MaxHealth` declared inert.
# `tests/mutation` for this gate therefore uses `Start.Deck` (rule 1 + 2 both have
# a line for it), not `MaxHealth`.  What would close the hole is a per-type
# reader index in the kernel; there is none, and inventing one in the gate would
# be a second copy of the truth.

KERNEL_DIR = os.path.join(ROOT, "kernel")
# The declaration is this gate's input, not content: it is a top-level key so that
# it travels with the document it describes, but the compiler lists it in
# `DOC_ROOT_KEYS` and therefore stores it in **neither image** (`check_roundtrip`
# asserts that absence).  It is not part of the inert-key universe either.
MANIFEST_ROOT_KEY = "InertKeys"
INERT_SCOPES = ("root", "Statuses[]", "Program")
# `root:<Parent>.<Field>` / `root:<Parent>[].<Field>` -- see "SUB-KEY PATHS" above.
SUBKEY_SCOPES = ("root",)
SUBKEY_PATH = re.compile(r"^(?P<parent>[A-Za-z_][A-Za-z0-9_]*)(?P<list>\[\])?\.(?P<field>[A-Za-z_][A-Za-z0-9_]*)$")
_COMMENT_PREFIXES = ("//", "/*", "*")
_KERNEL_CODE = {}


def snake_case(name):
    """`MaxNodeDepth` -> `max_node_depth`, the kernel's accessor spelling."""
    out = []
    for index, ch in enumerate(name):
        if ch.isupper() and index and (
                not name[index - 1].isupper()
                or (index + 1 < len(name) and name[index + 1].islower())):
            out.append("_")
        out.append(ch.lower())
    return "".join(out)


def kernel_rule_code():
    """`kernel/**/*.rs` minus test modules and comment lines, keyed by repo path."""
    if not _KERNEL_CODE:
        for base, dirs, files in os.walk(KERNEL_DIR):
            dirs[:] = sorted(d for d in dirs if d != "target")
            for name in sorted(files):
                if not name.endswith(".rs"):
                    continue
                path = os.path.join(base, name)
                with open(path, "r", encoding="utf-8", errors="replace") as fh:
                    text = fh.read()
                cut = re.search(r"^#\[cfg\(test\)\]", text, re.M)
                if cut:
                    text = text[:cut.start()]
                # Blank comment lines instead of dropping them: the failure messages
                # quote `file:line`, and a message that points at the wrong line is
                # worse than no line at all (this repo has been bitten by that).
                kept = ["" if line.lstrip().startswith(_COMMENT_PREFIXES) else line
                        for line in text.splitlines()]
                _KERNEL_CODE[rel(path)] = "\n".join(kept)
    return _KERNEL_CODE


def kernel_reads(key):
    """(bool, where) -- does kernel *rule* code consume this key?"""
    code = kernel_rule_code()
    call = re.compile(r"\.%s\(" % re.escape(snake_case(key)))
    literal = re.compile(r'"%s"' % re.escape(key))
    for path, text in sorted(code.items()):
        if path.endswith("rd-core/src/content.rs"):
            continue
        for pattern in (call, literal):
            hit = pattern.search(text)
            if hit:
                return True, "%s:%d" % (path, text.count("\n", 0, hit.start()) + 1)
    return False, ""


def root_read_by_name(key):
    """(bool, where) -- does any non-test kernel code call `root_by_name("<Key>")`?"""
    pattern = re.compile(r'root_by_name\(\s*"%s"\s*\)' % re.escape(key))
    for path, text in sorted(kernel_rule_code().items()):
        hit = pattern.search(text)
        if hit:
            return True, "%s:%d" % (path, text.count("\n", 0, hit.start()) + 1)
    return False, ""


def scope_keys(doc):
    """The inert-key universe, per scope, straight out of the source document."""
    row_tables = {section for _name, section in contentc_compile.ENTITY_SECTIONS}
    root = [key for key in doc if key not in row_tables and key != MANIFEST_ROOT_KEY]
    statuses, programs = [], []
    for record in doc.get("Statuses") or []:
        for key in record:
            if key not in statuses:
                statuses.append(key)
    for record in list(doc.get("Cards") or []) + list(doc.get("EnemyActions") or []):
        program = record.get("Program")
        if isinstance(program, dict):
            for key in program:
                if key not in programs:
                    programs.append(key)
    return {"root": root, "Statuses[]": statuses, "Program": programs}


def root_subkey_universe(doc):
    """`{path: (parent, is_list, field)}` for every **sub-key** the document has.

    The unit is one level: the fields of the object stored under a root key, or
    the union of the fields of the objects inside a root list.  One level is what
    the facts are about -- `Characters[].Start.Deck` and `Start.Deck` are the same
    term in both images (measured: `content.rs`'s "MEASURED SHAPES" table), so a
    second level would record the same fact twice under two spellings.

    Root keys are **not** filtered here: a sub-key of a wholly-inert root is
    still "present" (so it cannot masquerade as stale), it is only *covered* --
    see `check_inert_keys` (4).
    """
    row_tables = {section for _name, section in contentc_compile.ENTITY_SECTIONS}
    out = {}
    for parent, value in doc.items():
        if parent in row_tables or parent == MANIFEST_ROOT_KEY:
            continue
        fields, is_list = [], False
        if isinstance(value, dict):
            fields = list(value)
        elif isinstance(value, list):
            is_list = True
            for element in value:
                if isinstance(element, dict):
                    for field in element:
                        if field not in fields:
                            fields.append(field)
        for field in fields:
            path = "root:%s%s.%s" % (parent, "[]" if is_list else "", field)
            out[path] = (parent, is_list, field)
    return out


def subkey_reads(parent, field):
    """(bool, where) -- does kernel rule code read `<Parent>`'s `<Field>`?

    Two rules, both from `kernel/**/*.rs` **including** `content.rs` (which the
    whole-key rule excludes) -- see "WHAT COUNTS AS READING A SUB-KEY" above:
    the hop spelled as data, and an object-field lookup by name.  Both are
    reported when both hit: the `name` hit is the reader, the `hop` hit is the
    line that spells the path, and a message with only one of them sends the
    reader to the wrong kind of evidence.
    """
    patterns = (
        ("name", re.compile(r'name\s*==\s*"%s"' % re.escape(field))),
        ("hop", re.compile(r'"%s(?:\[\d*\])?\.%s(?![A-Za-z0-9_])'
                           % (re.escape(parent), re.escape(field)))),
    )
    found = []
    for rule, pattern in patterns:
        for path, text in sorted(kernel_rule_code().items()):
            hit = pattern.search(text)
            if hit:
                found.append("%s:%d (%s rule)"
                             % (path, text.count("\n", 0, hit.start()) + 1, rule))
                break
    return (bool(found), ", ".join(found))


def presentation_keys(doc, scope):
    """Keys the *compiler* strips (`strip_presentation`) -- a consumer, not inert.

    Derived from the compiler's own function, never from a second copy of the
    presentation rule (`contentc-audit.md` §7).
    """
    stripped = contentc_compile.strip_presentation(doc)
    return set(scope_keys(doc)[scope]) - set(scope_keys(stripped)[scope])


def check_inert_keys(doc):
    print("[6b] inert-key declarations (%s)" % MANIFEST_ROOT_KEY)
    entries = doc.get(MANIFEST_ROOT_KEY)
    if entries is None:
        fail(MANIFEST_ROOT_KEY,
             "the declaration block is missing -- every key without a kernel consumer "
             "has to be declared here (see the module docstring of this gate)")
        entries = []
    elif not isinstance(entries, list):
        fail(MANIFEST_ROOT_KEY, "must be a list, got %s" % type(entries).__name__)
        entries = []

    keys = scope_keys(doc)
    subs = root_subkey_universe(doc)

    declared = {}
    for index, entry in enumerate(entries):
        where = "%s[%d]" % (MANIFEST_ROOT_KEY, index)
        if not isinstance(entry, dict):
            fail(where, "must be an object with Path/Why, got %s" % type(entry).__name__)
            continue
        extra = sorted(set(entry) - {"Path", "Why"})
        if extra:
            fail(where, "unexpected key(s) %s (only Path/Why)" % extra)
        path, why = entry.get("Path"), entry.get("Why")
        if not isinstance(path, str) or ":" not in path:
            fail(where, "Path must be '<scope>:<Key>' (or `root:<Parent>.<Field>` / "
                 "`root:<Parent>[].<Field>`), got %r" % (path,))
            continue
        scope, key = path.split(":", 1)
        if scope not in INERT_SCOPES:
            fail(where, "unknown scope %r (known: %s)" % (scope, ", ".join(INERT_SCOPES)))
            continue
        if not key:
            fail(where, "empty key in Path %r" % path)
            continue
        if path in declared:
            fail(where, "duplicate Path %r" % path)
            continue
        if not isinstance(why, str) or len(why.strip()) < 12:
            fail(where, "%s: `Why` must state why the key can stay inert" % path)
            continue
        # Whole key, or (root only) a sub-key path.  "Is this a whole key?" is
        # decided by the document, not by the spelling, so a root key whose name
        # happens to contain a dot stays declarable.
        parent = field = None
        if key not in keys[scope]:
            shape = SUBKEY_PATH.match(key) if scope in SUBKEY_SCOPES else None
            if shape is None:
                fail(where, "Path %r is neither a %r key of the content nor a sub-key "
                     "path (`<Parent>.<Field>` / `<Parent>[].<Field>`)"
                     % (path, scope))
                continue
            parent, field = shape.group("parent"), shape.group("field")
        declared[path] = {"why": why, "scope": scope, "key": key,
                          "parent": parent, "field": field}

    def subkeys_of(path):
        return declared[path]["parent"] is not None

    # Which whole root keys are declared inert: their sub-keys are **covered**, so
    # (2) does not demand them and (4) rejects naming them anyway.
    root_inert = {entry["key"] for path, entry in declared.items()
                  if entry["scope"] == "root" and entry["parent"] is None}

    # (1) A declaration must not outlive its key: a manifest that names something
    # the content no longer has is a lie that reads like coverage.
    for path in sorted(declared):
        scope, key = declared[path]["scope"], declared[path]["key"]
        if subkeys_of(path):
            if path in subs:
                continue
            parent, field = declared[path]["parent"], declared[path]["field"]
            if parent not in keys[scope]:
                why = "its parent root key %r is not in the content" % parent
            elif not any(p == parent for p, _l, _f in subs.values()):
                why = ("root key %r is not an object (nor a list of objects), so it "
                       "has no sub-keys" % parent)
            else:
                why = ("root key %r has no field %r (it has: %s)"
                       % (parent, field,
                          ", ".join(sorted(f for p, _l, f in subs.values() if p == parent))))
            fail("inert.stale", "%s is declared inert but %s -- the declaration "
                 "outlived its key" % (path, why))
            continue
        if key not in keys[scope]:
            fail("inert.stale", "%s is declared inert but does not appear in the content "
                 "-- the declaration outlived its key" % path)

    # (2) Every key with no kernel consumer must be declared.  Same rule for whole
    # keys and for sub-keys; only the "where does a consumer show up" test differs.
    for scope in INERT_SCOPES:
        presentation = presentation_keys(doc, scope)
        for key in keys[scope]:
            path = "%s:%s" % (scope, key)
            if path in declared or key in presentation:
                continue
            if scope == "root":
                reads, where = root_read_by_name(key)
                rule = "no `root_by_name(\"%s\")` call in kernel rule code" % key
            else:
                reads, where = kernel_reads(key)
                rule = "no `.`+`%s(` and no \"%s\" literal in kernel rule code" % (
                    snake_case(key), key)
            if not reads:
                fail("inert.undeclared", "%s is not read by the kernel (%s) and is not "
                     "declared in %s -- wire it up, or declare it and say why it is "
                     "documentation" % (path, rule, MANIFEST_ROOT_KEY))
    for path, (parent, is_list, field) in sorted(subs.items()):
        if parent in root_inert or path in declared:
            continue
        reads, where = subkey_reads(parent, field)
        if not reads:
            hop = "%s[].%s" % (parent, field) if is_list else "%s.%s" % (parent, field)
            fail("inert.undeclared",
                 "%s is not read by the kernel (no hop spelling of `%s` and no "
                 "`name == \"%s\"` in kernel rule code) and is not declared in %s -- "
                 "wire it up, or declare it and say why it is documentation"
                 % (path, hop, field, MANIFEST_ROOT_KEY))

    # (3) A declaration must not rot the other way either: if the kernel grew a
    # consumer, the "inert" claim is now false and has to be deleted.
    for path in sorted(declared):
        scope, key = declared[path]["scope"], declared[path]["key"]
        if subkeys_of(path):
            reads, where = subkey_reads(declared[path]["parent"], declared[path]["field"])
        else:
            reads, where = root_read_by_name(key) if scope == "root" else kernel_reads(key)
        if reads:
            fail("inert.rotted", "%s is declared inert but the kernel reads it at %s -- "
                 "delete the declaration" % (path, where))

    # (4) A sub-key of a wholly-inert root key is **already** covered by that
    # root's declaration: naming it again is noise that reads like extra coverage
    # (and would let a manifest list `Monsters[]` fields as if it checked them).
    # Stricter than the original three checks, never looser.
    for path in sorted(declared):
        if not subkeys_of(path):
            continue
        parent = declared[path]["parent"]
        if parent in root_inert:
            fail("inert.redundant", "%s names a sub-key of root:%s, which is already "
                 "declared inert as a whole -- pick one granularity" % (path, parent))

    declared_sub = sum(1 for path in declared if subkeys_of(path))
    covered = sum(1 for parent, _l, _f in subs.values() if parent in root_inert)
    checked_sub = len(subs) - covered
    ok("inert keys",
       "%d declared (%d whole / %d root sub-key), %d root / %d root sub-key / "
       "%d status / %d envelope keys checked"
       % (len(declared), len(declared) - declared_sub, declared_sub, len(keys["root"]),
          checked_sub, len(keys["Statuses[]"]), len(keys["Program"])))


def check_roundtrip(doc, rom, label, expected):
    """Source document vs image, per key, on every entity and every root key."""
    print("[7] round trip: %s" % label)
    image = rom.document()
    for table in ("Cards", "Statuses", "EnemyActions", "Encounters", "Relics"):
        want = expected.get(table) or []
        got = image.get(table) or []
        if len(want) != len(got):
            fail("%s/%s" % (label, table), "row count %d vs %d" % (len(want), len(got)))
            continue
        for index, (w, g) in enumerate(zip(want, got)):
            problems = diff(w, g, "%s[%d]" % (table, index))
            if problems:
                fail("%s/%s[%d]" % (label, table, index), problems[0])
        ok(label + " " + table, "%d rows, key presence included" % len(want))
    # Document keys (`DOC_ROOT_KEYS`, imported from the compiler -- not a second
    # copy) are build metadata: they exist in the source and in *neither* image.
    # So they leave the compared key set, and the fact that they really are absent
    # becomes an assertion of its own -- otherwise "stripped" would be a claim in a
    # commit message instead of something this gate can fail on.
    doc_keys = contentc_compile.DOC_ROOT_KEYS
    leaked = [k for k in doc_keys if k in image]
    if leaked:
        fail("%s/document-keys" % label,
             "%s is declared a document key but reaches the image -- a documentation "
             "block is being paid for as content" % ", ".join(repr(k) for k in leaked))
    want_roots = sorted(k for k in expected if k not in ROW_TABLES and k not in doc_keys)
    got_roots = sorted(k for k in image if k not in ROW_TABLES and k not in doc_keys)
    if want_roots != got_roots:
        fail("%s/root" % label, "keys %s != %s" % (got_roots, want_roots))
    for key in want_roots:
        problems = diff(expected[key], image.get(key), key)
        if problems:
            fail("%s/root.%s" % (label, key), problems[0])
    ok(label + " roots", "%d keys, per key, %d document keys not stored"
       % (len(want_roots), len(doc_keys)))


def check_idx(rom, label):
    print("[8] id index: %s" % label)
    want = {
        "strike": F.EK_CARD, "defend": F.EK_CARD, "bash": F.EK_CARD,
        "slimed": F.EK_CARD,
        "standard.vulnerable": F.EK_STATUS, "standard.weak": F.EK_STATUS,
        "standard.strength": F.EK_STATUS, "standard.frail": F.EK_STATUS,
        "ritual": F.EK_STATUS,
        "cultist.incantation": F.EK_EACTION, "jaw_worm.chomp": F.EK_EACTION,
        "gremlin_wizard.ultimate_blast": F.EK_EACTION,
        "enc_cultist": F.EK_ENCOUNTER, "enc_small_slimes": F.EK_ENCOUNTER,
        "ironclad": F.EK_CHARACTER,
    }
    for entity_id, kind in sorted(want.items()):
        hit = rom.lookup(entity_id)
        if hit is None:
            fail("idx." + label, "%r missing from SEC_IDX" % entity_id)
        elif hit[0] != kind:
            fail("idx." + label, "%r resolves to kind %d, expected %d"
                 % (entity_id, hit[0], kind))
    ok(label + " SEC_IDX", "%d ids -> right entity kind" % len(want))


# =============================================================================
# 4.  main
# =============================================================================

def main():
    global SRC_PATH, FULL_PATH, CORE_PATH
    ap = argparse.ArgumentParser(description="gate for the sts content package")
    # The three overrides exist so that "source and image disagree" is a
    # *demonstrable* failure: build a mutated copy elsewhere and point the gate at
    # the good source + the mutated image.  The defaults are the package itself.
    ap.add_argument("--src", default=SRC_PATH)
    ap.add_argument("--full", default=FULL_PATH)
    ap.add_argument("--core", default=CORE_PATH)
    args = ap.parse_args()
    SRC_PATH, FULL_PATH, CORE_PATH = args.src, args.full, args.core

    print("sts content gate -- tools/contentc/packages/sts")
    check_preconditions()

    with open(SRC_PATH, "r", encoding="utf-8") as fh:
        doc = json.load(fh)

    full = rdcf_reader.Rom(open(FULL_PATH, "rb").read())
    core = rdcf_reader.Rom(open(CORE_PATH, "rb").read())

    check_quantities(doc)
    check_monsters(doc)
    check_cards_and_actions(doc)
    check_statuses(doc)
    check_conditional_else(doc)
    check_relations(doc)
    check_weak_pool_table(doc)
    check_event_vocabulary(doc)
    check_upgrades(doc)
    check_relic_rarities(doc)
    check_potions(doc)
    check_card_keywords(doc)
    check_relics(doc)
    check_inert_keys(doc)
    check_roundtrip(doc, full, "full", doc)
    # The core image's expectation comes from the compiler's own strip rule --
    # a copy of it here would be a second truth that rots (contentc-audit §7).
    check_roundtrip(doc, core, "core", contentc_compile.strip_presentation(doc))
    check_idx(full, "full")
    check_idx(core, "core")

    st = full.stats()
    print()
    if PROBLEMS:
        print("!! STS_CONTENT FAIL (%d problem(s))" % len(PROBLEMS))
        for problem in PROBLEMS:
            print("   " + problem)
        raise SystemExit(1)
    print("STS_CONTENT PASS (monsters %d, encounters %d, deck %d, statuses %d, "
          "cards %d, enemy_actions %d, full %d B, core %d B)"
          % (INV_COUNTS["monsters"], INV_COUNTS["encounters"], INV_COUNTS["deck"],
             INV_COUNTS["statuses"], len(doc.get("Cards") or []),
             len(doc.get("EnemyActions") or []), st["total_size"],
             os.path.getsize(CORE_PATH)))


if __name__ == "__main__":
    main()
