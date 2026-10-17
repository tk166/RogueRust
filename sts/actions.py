"""动作队列 —— 整个战斗系统的脊椎。

**任何状态改变都不是函数调用，而是往队列里塞一个"动作"对象。**

好处（也是为什么必须这么写）：
1. 逻辑顺序与动画节奏解耦：``duration`` 只是给表现层的元数据，逻辑不等它，
   所以 headless 自对弈和带动画的手玩跑的是同一条代码路径。
2. 连锁反应天然有序：治疗荆棘、仪式加力量、回合结束衰减，全部走队列。
3. 可重入：动作可以在执行中往队列顶端插新动作（荆棘反伤就是这么做的）。

三条纪律：
* 动作之外不许改 Creature（hp/block/statuses 只在 apply_hit / 各 Action 里写）。
* 队列有硬上限，防止 A->B->A 的触发链把进程打死（``strict`` 时直接抛异常）。
* 表现层不许直接调 Action，只能通过 combat.py 的 API。
"""

from __future__ import annotations

from collections import deque
from typing import Optional

from .config import HAND_CAP
from .db import status_name
from .events import (
    AttackCtx,
    CardCtx,
    DeathCtx,
    EventBus,
    Hook,
    HpLostCtx,
    StatusCtx,
)
from .rules import compute_block, compute_damage


class Action:
    """一个可入队的行为。``duration`` 仅供表现层决定停顿时长。"""

    label = "动作"
    duration = 0.0

    def __init__(self) -> None:
        self.done = False

    def start(self, state) -> None:      # noqa: D401 - 预热（可选）
        return None

    def update(self, state) -> bool:     # 返回 True 表示这个动作结束
        return True

    def __repr__(self) -> str:           # 便于调试
        return f"<{type(self).__name__}>"


class ActionQueue:
    MAX_ACTIONS = 20000

    def __init__(self) -> None:
        self._q: deque[Action] = deque()
        self.executed = 0

    def __len__(self) -> int:
        return len(self._q)

    def is_empty(self) -> bool:
        return not self._q

    def add_bottom(self, *actions: Action) -> None:
        for a in actions:
            self._q.append(a)

    def add_top(self, *actions: Action) -> None:
        for a in reversed(actions):
            self._q.appendleft(a)

    def clear(self) -> None:
        self._q.clear()

    def drain(self, state, strict: bool = False) -> int:
        """跑空队列。返回执行的动作数。"""
        n = 0
        while self._q:
            n += 1
            if n > self.MAX_ACTIONS:
                msg = f"动作队列超过 {self.MAX_ACTIONS} 上限，疑似无限触发链；已清空"
                state.say(f"[ERROR] {msg}")
                self._q.clear()
                if strict:
                    raise RuntimeError(msg)
                break
            action = self._q.popleft()
            action.start(state)
            guard = 0
            while not action.update(state):
                guard += 1
                if guard > 10000:
                    raise RuntimeError(f"动作 {action!r} 不收敛")
        self.executed += n
        return n


# --------------------------------------------------------------------------
# 伤害：整个游戏最核心的一个动作
# --------------------------------------------------------------------------

def apply_hit(state, source, target, q) -> None:
    """把一条已经算好最终值的伤害落到世界状态上，并广播通知钩子。"""
    amount = q.value
    blocked = min(target.block, amount)
    target.block -= blocked
    hp_loss = amount - blocked
    if hp_loss:
        target.hp = max(0, target.hp - hp_loss)

    if amount > 0:
        src = source.name if source is not None else "环境"
        line = f"{src} -> {target.name} 造成 {amount} 伤害"
        trace = EventBus.merge_trace(q.trace)
        if trace:
            line += f"  [{trace}]"
        line += f"  (格挡 {blocked}, 扣血 {hp_loss})"
        state.say(line)

    ctx = AttackCtx(state=state, source=source, target=target,
                    dealt=amount, hp_lost=hp_loss, kind=q.kind)
    state.bus.emit(Hook.ATTACKED, ctx)
    if hp_loss:
        state.bus.emit(Hook.HP_LOST, HpLostCtx(state=state, target=target,
                                               amount=hp_loss, source=source))
    if q.kind in ("ATTACK", "THORNS") and source is not None:
        state.bus.emit(Hook.ATTACK_DEALT, ctx)

    if target.hp <= 0 and not target.dead:
        target.dead = True
        state.queue.add_bottom(DeathAction(target))


class DamageAction(Action):
    label = "伤害"
    duration = 0.25

    def __init__(self, source, target, amount: int, kind: str = "ATTACK",
                 note: Optional[str] = None) -> None:
        super().__init__()
        self.source = source
        self.target = target
        self.amount = amount
        self.kind = kind
        self.note = note

    def update(self, state) -> bool:
        self.done = True
        if not self.target.alive():
            return True
        q = compute_damage(state, self.source, self.target, self.amount, self.kind)
        apply_hit(state, self.source, self.target, q)
        return True


class GainBlockAction(Action):
    label = "格挡"
    duration = 0.15

    def __init__(self, target, amount: int) -> None:
        super().__init__()
        self.target = target
        self.amount = amount

    def update(self, state) -> bool:
        self.done = True
        if not self.target.alive():
            return True
        q = compute_block(state, self.target, self.amount)
        self.target.block += q.value
        trace = EventBus.merge_trace(q.trace)
        suffix = f"  [{trace}]" if len(q.trace) > 1 else ""
        state.say(f"{self.target.name} 获得 {q.value} 点格挡{suffix}")
        return True


class ApplyStatusAction(Action):
    label = "施加状态"
    duration = 0.15

    def __init__(self, target, status: str, stacks: int, source=None) -> None:
        super().__init__()
        self.target = target
        self.status = status
        self.stacks = stacks
        self.source = source

    def update(self, state) -> bool:
        self.done = True
        if not self.target.alive():
            return True
        ctx = StatusCtx(state=state, target=self.target, status=self.status,
                        stacks=self.stacks, source=self.source)
        state.bus.emit(Hook.STATUS_APPLIED, ctx)
        if ctx.blocked:
            state.say(f"{self.target.name} 免疫了 {status_name(self.status)}")
            return True
        total = self.target.add_status(self.status, ctx.stacks)
        name = status_name(self.status)
        if ctx.stacks > 0:
            state.say(f"{self.target.name} 获得 {ctx.stacks} 层 {name}（共 {total}）")
        else:
            state.say(f"{self.target.name} 的 {name} 减少 {-ctx.stacks} 层（剩 {total}）")
        return True


class ReduceStatusAction(Action):
    label = "减少状态"
    duration = 0.0

    def __init__(self, target, status: str, stacks: int = 1, quiet: bool = False) -> None:
        super().__init__()
        self.target = target
        self.status = status
        self.stacks = stacks
        self.quiet = quiet

    def update(self, state) -> bool:
        self.done = True
        cur = self.target.status(self.status)
        if cur <= 0:
            return True
        left = cur - self.stacks
        if left <= 0:
            self.target.statuses.pop(self.status, None)
            left = 0
        else:
            self.target.statuses[self.status] = left
        if not self.quiet:
            state.say(f"{self.target.name} 的 {status_name(self.status)} 减少 "
                      f"{min(self.stacks, cur)} 层（剩 {left}）")
        return True


class DrawCardsAction(Action):
    label = "抽牌"
    duration = 0.15

    def __init__(self, n: int) -> None:
        super().__init__()
        self.n = n

    def update(self, state) -> bool:
        self.done = True
        for _ in range(self.n):
            if not state.draw_pile:
                if state.discard:
                    moved = len(state.discard)
                    state.draw_pile.extend(state.discard)
                    state.discard.clear()
                    state.rng["shuffle"].shuffle(state.draw_pile)
                    state.say(f"洗牌：弃牌堆 {moved} 张洗回抽牌堆")
                else:
                    state.say("牌堆已空，无法继续抽牌")
                    break
            card = state.draw_pile.pop(0)
            if len(state.hand) >= HAND_CAP:
                state.discard.append(card)
                state.say(f"手牌已满（{HAND_CAP}），{card.name} 被弃掉")
            else:
                state.hand.append(card)
                state.bus.emit(Hook.CARD_DRAWN,
                               CardCtx(state=state, card=card, owner=state.player))
        return True


class DiscardHandAction(Action):
    label = "弃手牌"
    duration = 0.15

    def update(self, state) -> bool:
        self.done = True
        n = len(state.hand)
        if n:
            state.discard.extend(state.hand)
            state.hand.clear()
            state.say(f"弃掉手中 {n} 张牌")
        return True


class ExhaustCardAction(Action):
    label = "消耗"

    def __init__(self, card) -> None:
        super().__init__()
        self.card = card

    def update(self, state) -> bool:
        self.done = True
        state.exhaust.append(self.card)
        state.say(f"{self.card.name} 被消耗")
        state.bus.emit(Hook.CARD_EXHAUSTED,
                       CardCtx(state=state, card=self.card, owner=state.player))
        return True


class HealAction(Action):
    label = "治疗"
    duration = 0.2

    def __init__(self, target, amount: int, reason: str = "") -> None:
        super().__init__()
        self.target = target
        self.amount = amount
        self.reason = reason

    def update(self, state) -> bool:
        self.done = True
        if not self.target.alive():
            return True
        before = self.target.hp
        self.target.hp = min(self.target.max_hp, self.target.hp + self.amount)
        gained = self.target.hp - before
        if gained:
            tag = f"（{self.reason}）" if self.reason else ""
            state.say(f"{self.target.name} 回复 {gained} 点生命{tag}")
        return True


class LoseHpAction(Action):
    """直接扣血，无视格挡（自伤/毒）。"""

    label = "失去生命"
    duration = 0.2

    def __init__(self, target, amount: int, reason: str = "") -> None:
        super().__init__()
        self.target = target
        self.amount = amount
        self.reason = reason

    def update(self, state) -> bool:
        self.done = True
        if not self.target.alive():
            return True
        self.target.hp = max(0, self.target.hp - self.amount)
        tag = f"（{self.reason}）" if self.reason else ""
        state.say(f"{self.target.name} 失去 {self.amount} 点生命{tag}")
        state.bus.emit(Hook.HP_LOST, HpLostCtx(state=state, target=self.target,
                                               amount=self.amount))
        if self.target.hp <= 0 and not self.target.dead:
            self.target.dead = True
            state.queue.add_bottom(DeathAction(self.target))
        return True


class DeathAction(Action):
    label = "死亡"
    duration = 0.3

    def __init__(self, creature) -> None:
        super().__init__()
        self.creature = creature

    def update(self, state) -> bool:
        self.done = True
        c = self.creature
        state.say(f"*** {c.name} 被击败 ***")
        state.bus.emit(Hook.DEATH, DeathCtx(state=state, creature=c))
        c.strip_statuses()
        c.block = 0
        return True


class LogAction(Action):
    label = "日志"

    def __init__(self, text: str) -> None:
        super().__init__()
        self.text = text

    def update(self, state) -> bool:
        self.done = True
        state.say(self.text)
        return True
