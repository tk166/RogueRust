"""内容数据库：卡牌 / 敌人 / 状态 / 遗物。

**卡就是数据，不是类**。升级只是同一份模板的另一份数据（levels[1]），
代码路径完全一致 —— 这是让内容量从 20 张扩到 500 张还不崩的前提。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from .state import Creature

CONTENT_DIR = Path(__file__).with_name("content")


def _load(name: str) -> list:
    with (CONTENT_DIR / name).open(encoding="utf-8") as fh:
        return json.load(fh)


CARDS: list[dict] = _load("cards.json")
ENEMIES: list[dict] = _load("enemies.json")
STATUSES: list[dict] = _load("statuses.json")
RELICS: list[dict] = _load("relics.json")

CARD_DB: dict[str, dict] = {c["id"]: c for c in CARDS}
ENEMY_DB: dict[str, dict] = {e["id"]: e for e in ENEMIES}
STATUS_DB: dict[str, dict] = {s["id"]: s for s in STATUSES}
RELIC_DB: dict[str, dict] = {r["id"]: r for r in RELICS}

PLAYABLE_RARITIES = ("COMMON", "UNCOMMON", "RARE")


# --------------------------------------------------------------------------
# 卡牌实例
# --------------------------------------------------------------------------

@dataclass
class CardInstance:
    """一张具体的牌。同类牌共享同一个 CardDef，只有 uid / 升级 / 临时改费是实例数据。"""

    uid: int
    cid: str
    upgraded: bool = False
    cost_delta: int = 0
    temp: bool = False

    @property
    def defn(self) -> dict:
        return CARD_DB[self.cid]

    @property
    def level(self) -> dict:
        return self.defn["levels"][1 if self.upgraded else 0]

    @property
    def name(self) -> str:
        return self.defn["name"] + ("+" if self.upgraded else "")

    @property
    def type(self) -> str:
        return self.defn["type"]

    @property
    def rarity(self) -> str:
        return self.defn["rarity"]

    @property
    def cost(self) -> int:
        return self.defn["cost"] + self.cost_delta

    @property
    def playable(self) -> bool:
        return self.cost >= 0 and self.type != "CURSE"

    @property
    def target_mode(self) -> str:
        return self.defn["target"]

    @property
    def desc(self) -> str:
        return self.level["desc"]

    @property
    def effects(self) -> list:
        return self.level["effects"]

    def key(self) -> str:
        return f"{self.cid}{'+' if self.upgraded else ''}#{self.uid}"

    def upgraded_copy(self) -> "CardInstance":
        return CardInstance(self.uid, self.cid, True)


def make_card(cid: str, uid: int, upgraded: bool = False) -> CardInstance:
    return CardInstance(uid, cid, upgraded)


def make_deck(spec: list[tuple[str, int]], start_uid: int = 0) -> tuple[list[CardInstance], int]:
    """按 (card_id, 张数) 造牌组，返回 (牌组, 下一个可用 uid)。"""
    deck: list[CardInstance] = []
    uid = start_uid
    for cid, n in spec:
        for _ in range(n):
            deck.append(make_card(cid, uid))
            uid += 1
    return deck, uid


def reward_pool(exclude: set[str] | None = None) -> list[str]:
    exclude = exclude or set()
    return [
        c["id"] for c in CARDS
        if c["rarity"] in PLAYABLE_RARITIES and c["id"] not in exclude
    ]


# --------------------------------------------------------------------------
# 敌人
# --------------------------------------------------------------------------

def make_monster(
    eid: str,
    rng,
    slot: int = 0,
    hp_bonus: int = 0,
) -> Creature:
    d = ENEMY_DB[eid]
    lo, hi = d["hp"]
    hp = rng.rand_int(hi - lo + 1) + lo + hp_bonus
    return Creature(
        cid=eid,
        name=d["name"],
        max_hp=hp,
        hp=hp,
        slot=slot,
        boss=bool(d.get("boss")),
    )


# --------------------------------------------------------------------------
# 遭遇表
# --------------------------------------------------------------------------

WEAK_ENCOUNTERS = [["louse"], ["louse", "louse"], ["cultist"]]
NORMAL_ENCOUNTERS = [
    ["jaw_worm"], ["acid_slime"], ["cultist"], ["louse", "louse"],
    ["jaw_worm", "louse"],
]
ELITE_ENCOUNTERS = [["jaw_worm", "acid_slime"], ["cultist", "acid_slime"]]


def roll_encounter(rng, kind: str) -> list[str]:
    if kind == "elite":
        return list(rng.choice(ELITE_ENCOUNTERS))
    if kind == "boss":
        return ["guardian"]
    if kind == "weak":
        return list(rng.choice(WEAK_ENCOUNTERS))
    return list(rng.choice(NORMAL_ENCOUNTERS))


# --------------------------------------------------------------------------
# 状态 / 遗物 显示名
# --------------------------------------------------------------------------

def status_name(sid: str) -> str:
    return STATUS_DB.get(sid, {}).get("name", sid)


def relic_name(rid: str) -> str:
    return RELIC_DB.get(rid, {}).get("name", rid)


def relic_desc(rid: str) -> str:
    return RELIC_DB.get(rid, {}).get("desc", "")


STARTER_DECK: list[tuple[str, int]] = [
    ("strike", 5), ("defend", 4), ("bash", 1),
]
STARTER_RELIC = "burning_blood"


def starter_deck() -> tuple[list[CardInstance], int]:
    return make_deck(STARTER_DECK, 0)


def find_card_def(cid: str) -> Optional[dict]:
    return CARD_DB.get(cid)
