"""多流确定性随机数。

对应 StS 的 12 条命名 PRNG 流。三条设计约束：

1. **一个系统一条流**。绝不用全局 ``random``：否则"某处多掷一次骰子"会平移
   整局后续所有随机（今天多抽一张牌，两层后的地图就变了）。
2. **取数是纯函数** ``f(seed, n)``，所以存档只需要存 ``(seed, counter)``，
   回滚 = 把 counter 写回去。这就是"同种子完全复现 / 种子分享 / 撤销"的全部秘密。
3. **每条流的种子要各不相同**。StS 的已知缺陷：多条流用同一个 run seed 冷启动，
   导致跨系统相关（首个 monsterRng 掷点能预测首个 eventRng 结果）。这里用
   名字哈希二次混淆，从根上避免。
"""

from __future__ import annotations

MASK = (1 << 64) - 1
GOLDEN = 0x9E3779B97F4A7C15


def mix(seed: int, n: int) -> int:
    """splitmix64 变体：把 (seed, n) 混成一个 64bit 数。纯函数，无状态。"""
    z = (seed + (n + 1) * GOLDEN) & MASK
    z = ((z ^ (z >> 30)) * 0xBF58476D1CE4E5B9) & MASK
    z = ((z ^ (z >> 27)) * 0x94D049BB133111EB) & MASK
    return (z ^ (z >> 31)) & MASK


def _name_salt(name: str) -> int:
    """FNV-1a 64bit：给每条流一个互不相同的盐。"""
    h = 0xCBF29CE484222325
    for b in name.encode("utf-8"):
        h = ((h ^ b) * 0x100000001B3) & MASK
    return h


class RngStream:
    """一条命名随机流。状态只有 ``(seed, counter)``。"""

    __slots__ = ("name", "seed", "counter")

    def __init__(self, name: str, seed: int, counter: int = 0) -> None:
        self.name = name
        self.seed = seed & MASK
        self.counter = counter

    # ---- 状态存取（存档 / 回滚 / 快照哈希都靠这两个） ----
    def state(self) -> list:
        return [self.name, self.seed, self.counter]

    def restore(self, st: list) -> None:
        self.name, self.seed, self.counter = st

    def clone(self) -> "RngStream":
        return RngStream(self.name, self.seed, self.counter)

    # ---- 取数 ----
    def at(self, n: int) -> int:
        """第 n 个输出，不影响计数器。"""
        return mix(self.seed, n)

    def next_u64(self) -> int:
        v = mix(self.seed, self.counter)
        self.counter += 1
        return v

    def rand_float(self) -> float:
        return self.next_u64() / 2 ** 64

    def rand_int(self, n: int) -> int:
        """[0, n) 均匀整数。"""
        if n <= 0:
            raise ValueError("rand_int 需要 n > 0")
        return self.next_u64() % n

    def chance(self, p: float) -> bool:
        return self.rand_float() < p

    def choice(self, seq):
        return seq[self.rand_int(len(seq))]

    def weighted(self, items, weights):
        total = sum(weights)
        r = self.rand_float() * total
        acc = 0.0
        for it, w in zip(items, weights):
            acc += w
            if r < acc:
                return it
        return items[-1]

    def shuffle(self, seq) -> None:
        """Fisher-Yates，原地。"""
        for i in range(len(seq) - 1, 0, -1):
            j = self.rand_int(i + 1)
            seq[i], seq[j] = seq[j], seq[i]

    def sample(self, seq, k: int) -> list:
        """不放回抽样 k 个（不修改原序列）。"""
        pool = list(seq)
        out = []
        for _ in range(min(k, len(pool))):
            out.append(pool.pop(self.rand_int(len(pool))))
        return out


#: 整局创建一次、全局复用的流
RUN_STREAMS = ("monster", "event", "merchant", "card", "treasure", "relic", "potion")
#: 每层（floor）重置计数器的流
FLOOR_STREAMS = ("monster_hp", "ai", "shuffle", "card_random", "misc")


class RngSet:
    """一整局的所有随机流。"""

    def __init__(self, seed: int) -> None:
        self.seed = seed & MASK
        self.streams: dict[str, RngStream] = {}
        for name in RUN_STREAMS + FLOOR_STREAMS:
            s = mix(self.seed, _name_salt(name))
            self.streams[name] = RngStream(name, s)

    def __getitem__(self, name: str) -> RngStream:
        return self.streams[name]

    def reset_floor(self) -> None:
        """进入新一层时重置"层内流"的计数器。

        注意：只重置计数器，不重置 seed —— 每条流的 seed 本来就是独立的，
        所以不会出现 StS 那种"冷启动同种子导致跨系统相关"。
        """
        for name in FLOOR_STREAMS:
            self.streams[name].counter = 0

    def snapshot(self) -> dict:
        return {k: v.state() for k, v in self.streams.items()}

    def restore(self, snap: dict) -> None:
        for k, st in snap.items():
            self.streams[k].restore(list(st))

    def counters(self) -> dict:
        return {k: v.counter for k, v in self.streams.items()}
