"""gymnasium 形状的环境包装。

`docs/spec/env-abi.md` §4 定义了观察向量的**定长布局**。本模块提供按名取字段的解码器，
这样训练代码写 `obs["hero_hp"]` 而不是 `obs[4]`，而**底层字节一个都不改**。

关于 -1：规格书规定"未占用的槽位填 -1 而不是 0"，因为 0 是真实取值（0 层状态、0 点格挡）。
解码时对"是否存在"的判断一律用 `>= 0`，不要用真值判断。
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from .native import EnvABI

# spec §4 的布局：区段名 -> 每项长度与项数
HEAD = ["round", "turn", "phase", "result", "hero_hp", "hero_hp_max", "hero_block",
        "hero_ward", "energy", "energy_max", "hand_count", "enemy_count"]
STATUS_AXES = ["strength", "vulnerable", "weak", "dexterity", "frail"]
MAX_ENEMIES = 4
MAX_HAND = 10
ENEMY_FIELDS = ["alive", "hp", "hp_max", "block", "ward", "intent_kind", "intent_damage", "status_slots_used"]
PILES = ["draw", "hand", "discard", "exhaust", "queue"]
CARD_FIELDS = ["occupied", "cost", "def_slot", "upgraded"]


def expected_observe_len() -> int:
    """按 spec §4 算出的应有长度；用来和 ABI 公布的长度对账。"""
    return (len(HEAD)
            + len(STATUS_AXES)
            + MAX_ENEMIES * len(ENEMY_FIELDS)
            + MAX_ENEMIES * len(STATUS_AXES)
            + MAX_HAND * len(CARD_FIELDS)
            + len(PILES)
            + 8)


def decode(obs: List[int]) -> Dict[str, Any]:
    """把定长整数向量解成按名的字典。**不改变任何数值。**"""
    need = expected_observe_len()
    if len(obs) != need:
        raise ValueError(f"观察长度 {len(obs)} 与 spec §4 推得的 {need} 不符 —— "
                         f"ABI 或规格书有一边变了，先对账再训练")
    o = 0
    out: Dict[str, Any] = {}
    for k in HEAD:
        out[k] = obs[o]; o += 1
    out["hero_status"] = dict(zip(STATUS_AXES, obs[o:o + len(STATUS_AXES)])); o += len(STATUS_AXES)

    enemies = []
    for _ in range(MAX_ENEMIES):
        e = dict(zip(ENEMY_FIELDS, obs[o:o + len(ENEMY_FIELDS)])); o += len(ENEMY_FIELDS)
        e["status"] = dict(zip(STATUS_AXES, obs[o:o + len(STATUS_AXES)])); o += len(STATUS_AXES)
        enemies.append(e)
    out["enemies"] = enemies

    hand = []
    for _ in range(MAX_HAND):
        c = dict(zip(CARD_FIELDS, obs[o:o + len(CARD_FIELDS)])); o += len(CARD_FIELDS)
        hand.append(c)
    out["hand"] = hand

    out["piles"] = dict(zip(PILES, obs[o:o + len(PILES)])); o += len(PILES)
    out["reserved"] = obs[o:o + 8]
    return out


def enemies_alive(decoded: Dict[str, Any]) -> List[int]:
    """存活敌人下标。判定用 `alive >= 0`，不是真值判断。"""
    return [i for i, e in enumerate(decoded["enemies"]) if e["alive"] >= 0]


def hand_occupied(decoded: Dict[str, Any]) -> List[int]:
    return [i for i, c in enumerate(decoded["hand"]) if c["occupied"] >= 0]


class RogueDeckEnv:
    """一个环境实例。动作是 `actions()` 列表的下标（离散动作空间）。"""

    def __init__(self, config: int = 0, seed: int = 1, abi: Optional[EnvABI] = None) -> None:
        self.abi = abi or EnvABI()
        self.config = config
        self.handle = self.abi.create(config, seed)
        self.seed = seed

    # ---- gymnasium 形状 ----

    def reset(self, seed: Optional[int] = None) -> List[int]:
        if seed is not None:
            # 句柄持有的种子不可变，换种子要重建句柄 —— 这是句柄式设计的代价，明说比偷偷错好。
            self.abi.destroy(self.handle)
            self.seed = seed
            self.handle = self.abi.create(self.config, seed)
        else:
            rc = self.abi.reset(self.handle)
            if rc != 0:
                raise RuntimeError(f"rd_env_reset -> {rc}；{self.abi.last_error()}")
        return self.abi.observe(self.handle)

    def step(self, action_index: int) -> Tuple[List[int], int, bool, Dict[str, Any]]:
        rc = self.abi.step(self.handle, action_index)
        if rc != 0:
            # 规格书 §5：拒绝时状态不变。**直接验证**，别只信返回值。
            raise RuntimeError(
                f"rd_env_step(action={action_index}) -> {rc}；{self.abi.last_error()}")
        obs = self.abi.observe(self.handle)
        return obs, self.abi.reward(self.handle), self.abi.done(self.handle), {"result": self.abi.result(self.handle)}

    # ---- 便利 ----

    def actions(self) -> List[Tuple[int, int, int]]:
        return self.abi.actions(self.handle)

    def action_mask(self) -> List[bool]:
        return [True] * self.abi._lib.rd_env_action_count(self.handle)

    def close(self) -> None:
        self.abi.destroy(self.handle)

    def __enter__(self) -> "RogueDeckEnv":
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()
