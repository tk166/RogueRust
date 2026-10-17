"""ctypes 绑定：环境 ABI（`docs/spec/env-abi.md` 冻结 v1）。

设计上的两条纪律：

1. **ABI 不存在时必须响亮地失败**，不能静默降级。一个"找不到环境导出就跳过测试"的包装层，
   会让训练脚本在没有环境的情况下"跑得通"并且看不出问题 —— 这比报错糟得多。
2. **观察向量是定长的整数数组，不在 Python 侧做任何语义重编码**。包装层只负责
   忠实搬运与切分；把观察变成给网络的张量是训练侧的职责。
"""

from __future__ import annotations

import array
import ctypes
import glob
import os
from typing import Optional

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
ORACLE_PUB = os.path.join(ROOT, "native", "RogueDeck.Oracle", "bin", "x64", "Release",
                          "net10.0", "win-x64", "publish")

INT_MIN = -2147483648

# name -> 参数个数。返回值一律 c_int。这些是 v1 契约的**必需**导出，缺一个就拒绝工作。
ENV_FUNCS = {
    "rd_env_create": 2,
    "rd_env_destroy": 1,
    "rd_env_reset": 1,
    "rd_env_observe_len": 0,
    "rd_env_observe": 2,
    "rd_env_done": 1,
    "rd_env_result": 1,
    "rd_env_action_count": 1,
    "rd_env_action_kind": 2,
    "rd_env_action_arg": 3,
    "rd_env_step": 2,
    "rd_env_reward": 1,
    "rd_env_last_error_len": 0,
    "rd_env_last_error_char": 1,
    "rd_env_selfcheck": 3,
}


class ABIMissing(RuntimeError):
    """环境 ABI 还没被实现/构建出来。这不是"跳过测试"的理由，是必须报的错。"""


class EnvABI:
    def __init__(self, path: Optional[str] = None) -> None:
        self.path = path or self._find()
        self._lib = ctypes.CDLL(self.path)
        missing = [n for n in ENV_FUNCS if not hasattr(self._lib, n)]
        if missing:
            raise ABIMissing(
                f"{os.path.basename(self.path)} 缺少环境 ABI 导出：{', '.join(sorted(missing)[:6])}"
                f"{' …' if len(missing) > 6 else ''}\n"
                f"  共缺 {len(missing)}/{len(ENV_FUNCS)} 个。环境 ABI 规格见 docs/spec/env-abi.md，"
                f"由 NativeAOT oracle 侧实现（OracleExports.Env.cs）。"
            )
        for name, nargs in ENV_FUNCS.items():
            fn = getattr(self._lib, name)
            fn.restype = ctypes.c_int
            fn.argtypes = [ctypes.c_int] * nargs
        self._bind_bulk_observe()

    def _bind_bulk_observe(self) -> None:
        """可选导出：整条观察一次拷完。

        没有它也能跑（逐项 `rd_env_observe` 语义相同），但**慢一个数量级**：122 个整数 =
        122 次跨 ABI 调用，实测 40 µs/步。所以这里只在**缺了的时候**吱一声，绝不静默降级到
        "能跑就行" —— 训练吞吐差十倍而没人知道，比直接报错难查得多。
        """
        self.has_bulk_observe = hasattr(self._lib, "rd_env_observe_into")
        self._observe_into = getattr(self._lib, "rd_env_observe_into", None)
        if self._observe_into is not None:
            self._observe_into.restype = ctypes.c_int
            self._observe_into.argtypes = [ctypes.c_int, ctypes.c_void_p, ctypes.c_int]
        self.bulk_observe_note = (
            "" if self.has_bulk_observe
            else "该 dll 没有 rd_env_observe_into：观察只能逐项读（约 40 µs/步）。"
                 "重建 oracle 即可（tools\\dnaot.ps1 publish …）。")

    @staticmethod
    def _find() -> str:
        cands = sorted(glob.glob(os.path.join(ORACLE_PUB, "*.dll")))
        if not cands:
            raise ABIMissing(
                f"{ORACLE_PUB} 下没有 dll。先构建：\n"
                f"  powershell -NoProfile -ExecutionPolicy Bypass -File "
                f"{os.path.join(ROOT, 'tools', 'dnaot.ps1')} publish "
                f"native/RogueDeck.Oracle/RogueDeck.Oracle.csproj -c Release -r win-x64"
            )
        for p in cands:
            try:
                lib = ctypes.CDLL(p)
                if hasattr(lib, "rd_env_create"):
                    return p
            except OSError:
                continue
        # 有 dll 但都没有环境导出：仍然报错，并说明缺什么。
        return cands[0]

    # ---- 薄封装 ----

    def observe_len(self) -> int:
        return self._lib.rd_env_observe_len()

    def create(self, config: int, seed: int) -> int:
        h = self._lib.rd_env_create(config, seed)
        if h < 0:
            raise RuntimeError(f"rd_env_create(config={config}, seed={seed}) -> {h}；{self.last_error()}")
        return h

    def destroy(self, h: int) -> None:
        self._lib.rd_env_destroy(h)

    def reset(self, h: int) -> int:
        return self._lib.rd_env_reset(h)

    def _addr_of(self, buf) -> int:
        """拿到 `array('i')` 的数据指针。

        注意 `ctypes.addressof` **只接受 ctypes 对象**，对 `array.array` 会抛
        `TypeError: invalid type`；`array.array.buffer_info()` 才是它的取址方式。
        """
        if isinstance(buf, array.array):
            return buf.buffer_info()[0]
        return ctypes.addressof(buf)

    def observe_into(self, h: int, buf, offset: int = 0) -> int:
        """把观察写进 `buf`（`array('i')`）的 `offset` 处。返回写入个数。"""
        n = self.observe_len()
        if self._observe_into is not None and offset + n <= len(buf):
            rc = self._observe_into(h, self._addr_of(buf) + offset * 4, len(buf) - offset)
            if rc != n:
                raise RuntimeError(f"rd_env_observe_into -> {rc}（期望 {n}）；{self.last_error()}")
            return n
        out = self.observe(h)          # 回退路径：逐项读，语义相同
        for i, v in enumerate(out):
            buf[offset + i] = v
        return len(out)

    def observe(self, h: int) -> list:
        n = self.observe_len()
        if self._observe_into is not None:
            buf = array.array("i", bytes(n * 4))
            rc = self._observe_into(h, self._addr_of(buf), n)
            if rc != n:
                raise RuntimeError(f"rd_env_observe_into -> {rc}（期望 {n}）；{self.last_error()}")
            return buf.tolist()
        out = [0] * n
        for i in range(n):
            v = self._lib.rd_env_observe(h, i)
            if v == INT_MIN:
                raise RuntimeError(f"rd_env_observe(handle, {i}) 越界：observe_len() 说 {n}")
            out[i] = v
        return out

    def done(self, h: int) -> bool:
        return self._lib.rd_env_done(h) != 0

    def result(self, h: int) -> int:
        return self._lib.rd_env_result(h)

    def actions(self, h: int) -> list:
        """[(kind, arg0, arg1), ...] —— 当前合法动作。"""
        out = []
        for i in range(self._lib.rd_env_action_count(h)):
            out.append((
                self._lib.rd_env_action_kind(h, i),
                self._lib.rd_env_action_arg(h, i, 0),
                self._lib.rd_env_action_arg(h, i, 1),
            ))
        return out

    def step(self, h: int, action_index: int) -> int:
        return self._lib.rd_env_step(h, action_index)

    def reward(self, h: int) -> int:
        return self._lib.rd_env_reward(h)

    def selfcheck(self, config: int, seed: int, steps: int) -> int:
        return self._lib.rd_env_selfcheck(config, seed, steps)

    def last_error(self) -> str:
        n = self._lib.rd_env_last_error_len()
        return "".join(chr(self._lib.rd_env_last_error_char(i)) for i in range(n))
