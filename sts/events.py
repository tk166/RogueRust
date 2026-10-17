"""事件总线：阶段代码只发事件，谁关心谁订阅。

对应 StS 的 ``AbstractPower`` 钩子族 / BaseMod 的 ``ISubscriber``。

三条硬约束（违反任意一条，内容量一大就会崩）：

1. **处理器必须是模块级纯函数**，只读写 ctx。绝不许闭包捕获 state，
   否则深拷贝存档会把整个世界复制一份。
2. **emit 时对订阅者列表做快照**，允许处理器在回调里注册/注销
   （StS 那边会直接抛 ConcurrentModificationException，很痛）。
3. **触发深度上限**，防止 A→B→A 的无限触发链把进程打死。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable


class Hook:
    """所有可挂钩的时刻。这份清单就是你的"架构总线图"。"""

    COMBAT_START = "combat.start"
    COMBAT_END = "combat.end"

    TURN_START = "turn.start"          # turn.start.player / .monster
    TURN_END = "turn.end"              # turn.end.player / .monster
    ROUND_END = "round.end"

    # 修饰器查询（handler 改 ctx.value，不改世界）
    DAMAGE_GIVE = "damage.give"            # 攻击方侧：力量 / 虚弱
    DAMAGE_RECEIVE = "damage.receive"      # 受方侧：易伤
    DAMAGE_FINAL_GIVE = "damage.final.give"
    DAMAGE_FINAL_RECEIVE = "damage.final.receive"
    BLOCK_GAIN = "block.gain"              # 敏捷 / 脆弱

    # 通知（handler 可以入队新动作）
    ATTACK_DEALT = "attack.dealt"
    ATTACKED = "attacked"                  # 荆棘在这里反伤
    HP_LOST = "hp.lost"
    CARD_PLAYED = "card.played"
    CARD_DRAWN = "card.drawn"
    CARD_EXHAUSTED = "card.exhausted"
    STATUS_APPLIED = "status.applied"
    DEATH = "death"


# --------------------------------------------------------------------------
# 上下文对象：处理器只碰这些
# --------------------------------------------------------------------------

@dataclass
class DamageCtx:
    state: Any
    source: Any            # Creature | None
    target: Any            # Creature
    value: float           # 可被修饰器改写
    kind: str = "ATTACK"   # ATTACK / THORNS / POISON / ...
    trace: list[str] = field(default_factory=list)

    def note(self, who: str, detail: str) -> None:
        self.trace.append(f"{who} {detail}")


@dataclass
class BlockCtx:
    state: Any
    target: Any
    value: float
    trace: list[str] = field(default_factory=list)


@dataclass
class TurnCtx:
    state: Any
    side: str              # "player" | "monster"
    actor: Any = None      # 回合归属的生物（怪物回合时是那只怪物）


@dataclass
class AttackCtx:
    state: Any
    source: Any
    target: Any
    dealt: int = 0         # 实际打出的伤害（已扣格挡前）
    hp_lost: int = 0
    kind: str = "ATTACK"


@dataclass
class HpLostCtx:
    state: Any
    target: Any
    amount: int
    source: Any = None


@dataclass
class CardCtx:
    state: Any
    card: Any
    owner: Any = None
    target: Any = None


@dataclass
class StatusCtx:
    state: Any
    target: Any
    status: str
    stacks: int
    source: Any = None
    blocked: bool = False      # 人工制品之类的"免疫这次施加"钩子把它置 True


@dataclass
class DeathCtx:
    state: Any
    creature: Any


# --------------------------------------------------------------------------

Handler = Callable[[Any], None]


class EventBus:
    def __init__(self, max_depth: int = 48) -> None:
        self._subs: dict[str, list[tuple[int, int, Handler]]] = {}
        self._seq = 0
        self._depth = 0
        self.max_depth = max_depth
        self.trace: list[str] = []      # 触发链留下的诊断信息
        self.truncated = 0

    def on(self, hook: str, priority: int = 0) -> Callable[[Handler], Handler]:
        """装饰器注册。priority 大的先跑；同优先级按注册顺序。"""

        def deco(fn: Handler) -> Handler:
            self._subs.setdefault(hook, []).append((priority, self._seq, fn))
            self._seq += 1
            self._subs[hook].sort(key=lambda t: (-t[0], t[1]))
            return fn

        return deco

    def sub_count(self, hook: str) -> int:
        return len(self._subs.get(hook, ()))

    def emit(self, hook: str, ctx):
        """同步派发。返回同一个 ctx（方便链式取回被改写的 value）。"""
        subs = self._subs.get(hook)
        if not subs:
            return ctx
        if self._depth >= self.max_depth:
            self.truncated += 1
            self.trace.append(
                f"[触发链超深 {self.max_depth}] 截断 hook={hook}：疑似 A->B->A 无限触发"
            )
            return ctx
        self._depth += 1
        try:
            # 快照：允许处理器在回调里订阅/退订
            for _, _, fn in list(subs):
                fn(ctx)
        finally:
            self._depth -= 1
        return ctx

    @staticmethod
    def merge_trace(trace: list[str]) -> str:
        return " -> ".join(trace) if trace else ""
