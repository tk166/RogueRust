"""出厂调参常量（对应"shipped tuning constants"）。规则代码里不许出现魔法数字。"""

BASE_ENERGY = 3          # 每回合基础能量
BASE_DRAW = 5            # 每回合基础抽牌
HAND_CAP = 10            # 手牌上限，超出的抽牌直接进弃牌堆

MAP_ROWS = 15            # 每幕层数
MAP_COLS = 7             # 网格宽度
MAP_PATHS = 6            # 生成几条路径

REST_HEAL_PCT = 0.30     # 火堆回血比例
PURGE_BASE_COST = 75     # 商店删牌基础价
PURGE_STEP = 25          # 每删一次涨价
SHOP_CARD_COST = 50

ELITE_HP_BONUS = 8       # 精英怪血量加成

REWARD_CARD_COUNT = 3    # 战斗奖励三选一
GOLD_MONSTER = (10, 20)
GOLD_ELITE = (25, 35)
GOLD_BOSS = (95, 105)
GOLD_TREASURE = (30, 50)

POTION_DROP_CHANCE = 0.40
