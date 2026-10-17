"""数据模型：生物、战斗状态、以及确定性校验用的快照哈希。

这一层是"唯一的可变真相"（single source of truth）。渲染层只读它，
并且**永远不修改它**——想改世界就得往动作队列里塞一个动作。
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class Creature:
    """玩家和怪物共用。状态层数存在自己身上，行为在 rules.py 里注册。"""

    cid: str
    name: str
    max_hp: int
    hp: int
    is_player: bool = False
    block: int = 0
    statuses: dict[str, int] = field(default_factory=dict)
    slot: int = 0                 # TUI 里的编号 [1] [2] ...
    dead: bool = False
    boss: bool = False

    # 怪物 AI：当前意图**是完全结算好的下一步行动**（不是概率提示），
    # 伤害数字在渲染时按当前力量/虚弱/易伤实时重算 —— 这就是"明牌回合引擎"。
    intent: Optional[dict] = None
    move_history: list[str] = field(default_factory=list)

    # --- 查询 ---
    def status(self, sid: str) -> int:
        return self.statuses.get(sid, 0)

    def has(self, sid: str) -> bool:
        return self.statuses.get(sid, 0) > 0

    def alive(self) -> bool:
        return not self.dead and self.hp > 0

    def pct(self) -> float:
        return 0.0 if self.max_hp <= 0 else self.hp / self.max_hp

    # --- 直接变更（只在 actions.py 里被调用，别在别处写） ---
    def add_status(self, sid: str, n: int) -> int:
        if n == 0:
            return self.status(sid)
        cur = self.statuses.get(sid, 0) + n
        if cur <= 0:
            self.statuses.pop(sid, None)
            return 0
        self.statuses[sid] = cur
        return cur

    def strip_statuses(self) -> None:
        self.statuses.clear()

    def snap(self) -> dict:
        return {
            "name": self.name,
            "hp": self.hp,
            "max": self.max_hp,
            "block": self.block,
            "dead": self.dead,
            "st": {k: v for k, v in sorted(self.statuses.items())},
            "intent": self.intent["id"] if self.intent else None,
            "hist": list(self.move_history),
        }


@dataclass
class CombatState:
    """一场战斗的全部状态。"""

    player: Creature
    enemies: list[Creature] = field(default_factory=list)

    energy: int = 3
    max_energy: int = 3

    draw_pile: list[Any] = field(default_factory=list)
    hand: list[Any] = field(default_factory=list)
    discard: list[Any] = field(default_factory=list)
    exhaust: list[Any] = field(default_factory=list)

    turn: int = 1
    phase: str = "player"        # player / monster / over
    over: bool = False
    result: str = ""             # win / lose
    floor: int = 0
    kind: str = "monster"

    cards_played_turn: int = 0
    attacks_played_turn: int = 0
    skills_played_turn: int = 0

    relics: list[str] = field(default_factory=list)   # 整局持有的遗物 id

    bus: Any = None              # EventBus
    queue: Any = None            # ActionQueue
    rng: Any = None              # RngSet
    log: list[str] = field(default_factory=list)

    # ---------------- 查询 ----------------
    def alive_enemies(self) -> list[Creature]:
        return [e for e in self.enemies if e.alive()]

    def creatures(self) -> list[Creature]:
        return [self.player] + list(self.enemies)

    def player_dead(self) -> bool:
        return not self.player.alive()

    def all_enemies_dead(self) -> bool:
        return not self.alive_enemies()

    # ---------------- 日志 ----------------
    def say(self, text: str) -> None:
        self.log.append(text)

    # ---------------- 确定性 ----------------
    def snap(self) -> dict:
        return {
            "player": self.player.snap(),
            "enemies": [e.snap() for e in self.enemies],
            "energy": self.energy,
            "max_energy": self.max_energy,
            "draw": [c.key() for c in self.draw_pile],
            "hand": [c.key() for c in self.hand],
            "discard": [c.key() for c in self.discard],
            "exhaust": [c.key() for c in self.exhaust],
            "turn": self.turn,
            "phase": self.phase,
            "over": self.over,
            "result": self.result,
            "relics": sorted(self.relics),
            "counters": self.rng.counters() if self.rng else {},
        }

    def digest(self) -> str:
        blob = json.dumps(self.snap(), sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(blob.encode("utf-8")).hexdigest()


# --------------------------------------------------------------------------

def zone_names(state: CombatState) -> dict[str, int]:
    return {
        "手牌": len(state.hand),
        "抽牌堆": len(state.draw_pile),
        "弃牌堆": len(state.discard),
        "消耗": len(state.exhaust),
    }


def find_enemy(state: CombatState, slot: int) -> Optional[Creature]:
    for e in state.enemies:
        if e.slot == slot and e.alive():
            return e
    return None
