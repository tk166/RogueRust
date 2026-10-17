"""gymnasium 形状的 RogueDeck 训练环境。

底层是 NativeAOT 编出来的原生库（`docs/spec/env-abi.md` 冻结 v1），**没有 .NET 运行时依赖**。
"""

from .env import RogueDeckEnv, decode, expected_observe_len
from .native import ABIMissing, EnvABI

__all__ = ["RogueDeckEnv", "EnvABI", "ABIMissing", "decode", "expected_observe_len"]
