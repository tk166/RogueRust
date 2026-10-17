"""修饰器管线（Modifier Pipeline）+ 状态行为注册。

**铁律：任何地方都不许直接改数值。** 伤害必须走一条固定顺序的链：

    基础 -> damage.give(攻方: 力量/虚弱) -> damage.receive(受方: 易伤)
         -> damage.final.give -> damage.final.receive -> clamp -> 扣格挡 -> 扣血

每个状态只是在这条链上提供一个"进去一个数、出来一个数"的回调。
**这条链的顺序号就是你的游戏规则**，随手改顺序 = 出现"力量和易伤谁先乘"的双标 bug。

状态的层数存在 Creature 身上，行为是**无状态模块**（每个 id 只在总线上注册一次）。
这比 StS 那种"每个状态实例各自订阅/退订"更省事，也天然躲开了
"回调里注销自己导致 ConcurrentModificationException" 那个坑。
"""

from __future__ import annotations

from .db import STATUS_DB
from .events import (
    Hook,
    BlockCtx,
    DamageCtx,
    EventBus,
    StatusCtx,
    TurnCtx,
)

# --------------------------------------------------------------------------
# 查询管线
# --------------------------------------------------------------------------

def compute_damage(state, source, target, amount: float, kind: str = "ATTACK") -> DamageCtx:
    """计算一次伤害的最终值，并留下可读的推导轨迹（TUI 会把它打出来）。"""
    ctx = DamageCtx(state=state, source=source, target=target,
                    value=float(amount), kind=kind)
    ctx.trace.append(f"基础{int(amount)}")
    bus: EventBus = state.bus
    bus.emit(Hook.DAMAGE_GIVE, ctx)
    bus.emit(Hook.DAMAGE_RECEIVE, ctx)
    bus.emit(Hook.DAMAGE_FINAL_GIVE, ctx)
    bus.emit(Hook.DAMAGE_FINAL_RECEIVE, ctx)
    ctx.value = max(0, int(ctx.value))
    return ctx


def compute_block(state, target, amount: float) -> BlockCtx:
    ctx = BlockCtx(state=state, target=target, value=float(amount))
    ctx.trace.append(f"基础{int(amount)}")
    state.bus.emit(Hook.BLOCK_GAIN, ctx)
    ctx.value = max(0, int(ctx.value))
    return ctx


# --------------------------------------------------------------------------
# 状态行为：模块级纯函数，只看 ctx，绝不捕获 state
# --------------------------------------------------------------------------

def _st(ctx, creature, sid: str) -> int:
    return creature.status(sid) if creature is not None else 0


# --- 攻方：加法先跑（priority 10），乘法后跑（priority 0） ---

def _strength_give(c: DamageCtx) -> None:
    n = _st(c, c.source, "strength")
    if n and c.kind == "ATTACK":
        c.value += n
        c.note("力量", f"+{n}")


def _weak_give(c: DamageCtx) -> None:
    n = _st(c, c.source, "weak")
    if n and c.kind == "ATTACK":
        before = c.value
        c.value *= 0.75
        c.note("虚弱", f"{int(before)}x0.75")


def _vulnerable_receive(c: DamageCtx) -> None:
    n = _st(c, c.target, "vulnerable")
    if n and c.kind == "ATTACK":
        before = c.value
        c.value *= 1.5
        c.note("易伤", f"{int(before)}x1.5")


def _dexterity_block(c: BlockCtx) -> None:
    n = _st(c, c.target, "dexterity")
    if n:
        c.value += n
        c.trace.append(f"敏捷+{n}")


def _frail_block(c: BlockCtx) -> None:
    n = _st(c, c.target, "frail")
    if n:
        before = c.value
        c.value *= 0.75
        c.trace.append(f"脆弱{int(before)}x0.75")


# --- 通知类：可以往队列里塞新动作（这就是连锁反应的来源） ---

def _thorns_on_attacked(c) -> None:
    """被攻击时反伤。注意 kind="THORNS" 不是攻击，所以不会自我循环。"""
    from .actions import DamageAction  # 局部 import 打断循环依赖

    n = _st(c, c.target, "thorns")
    if n and c.kind == "ATTACK" and c.source is not None and c.source is not c.target:
        c.state.queue.add_top(
            DamageAction(c.target, c.source, n, kind="THORNS",
                         note="荆棘反伤")
        )


def _ritual_turn_end(c: TurnCtx) -> None:
    from .actions import ApplyStatusAction

    if c.actor is None:
        return
    n = _st(c, c.actor, "ritual")
    if n and c.side == "monster":
        c.state.queue.add_top(
            ApplyStatusAction(c.actor, "strength", n, source=c.actor)
        )


def _metallicize_turn_end(c: TurnCtx) -> None:
    from .actions import GainBlockAction

    if c.actor is None:
        return
    n = _st(c, c.actor, "metallicize")
    if n:
        c.state.queue.add_top(GainBlockAction(c.actor, n))


def _decay_turn_end(c: TurnCtx) -> None:
    """回合结束时给"会衰减的状态"减 1 层（易伤/虚弱/脆弱）。"""
    from .actions import ReduceStatusAction

    if c.actor is None:
        return
    for sid, d in STATUS_DB.items():
        if d.get("decay") and c.actor.status(sid) > 0:
            c.state.queue.add_top(ReduceStatusAction(c.actor, sid, 1, quiet=True))


def _status_applied(c: StatusCtx) -> None:
    """预留：人工制品之类的"免疫负面状态"在这里把 c.blocked 置 True。"""
    return


# (hook, priority, handler)
STATUS_BEHAVIORS: list[tuple[str, int, object]] = [
    (Hook.DAMAGE_GIVE, 10, _strength_give),
    (Hook.DAMAGE_GIVE, 0, _weak_give),
    (Hook.DAMAGE_RECEIVE, 0, _vulnerable_receive),
    (Hook.BLOCK_GAIN, 10, _dexterity_block),
    (Hook.BLOCK_GAIN, 0, _frail_block),
    (Hook.ATTACKED, 0, _thorns_on_attacked),
    (Hook.TURN_END, 0, _ritual_turn_end),
    (Hook.TURN_END, 0, _metallicize_turn_end),
    (Hook.TURN_END, -10, _decay_turn_end),
    (Hook.STATUS_APPLIED, 0, _status_applied),
]


def register_status_behaviors(bus: EventBus) -> None:
    """每场战斗建总线时注册一次。"""
    for hook, prio, fn in STATUS_BEHAVIORS:
        bus.on(hook, prio)(fn)
