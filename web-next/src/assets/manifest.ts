// 生成物：`python native/build_assets.py` 重建，**不要手改**。
//
// 素材清单：内容 id → 素材描述。**穷尽**（每个内容 id 都有一条），所以"内容加了东西
// 而美术没跟上"在结构上不会静默 —— 清单是生成的，注册表对缺失 id 还会计数（见 registry.ts）。
//
// 三维敌人：16 种「立体几何排列组合」原型（原型本体是 `geometry.ts` 里的纯数据）。
// 二维元素：两位大写字母 + 调色板（`letters_for` 的规则见生成器文件头）。

// §398：生成器**自己的** sha256（这个 .py 文件的）—— 闸门 45 用 Node 重算并与它比对。
// 改了生成器（palette/scale/boss 规则…）却没重跑 ⇒ 指纹对不上 ⇒ 闸门红。
// 这条是审阅 §4 指出的盲点：验收链的 PATH 是剥空的，跑不了 python，但**能**算 sha256。
export const GENERATOR_SHA = "e49d6270a5804c9304fbd300b8ab73ce15a059f4551c1ebd3b8b5a4751579a4d";

// §398：哈希对拍表（Python 侧算好的真值）。闸门 45 用它逐条验证 `registry.ts` 的 JS 实现
// 与生成器**逐字节**一致 —— 否则"清单里有的 id"与"降级时的 id"会落到不同原型/调色板。
export const HASH_FIXTURES: readonly { text: string; hash: number }[] = [
 {
  "text": "",
  "hash": 2166136261
 },
 {
  "text": "strike",
  "hash": 632598351
 },
 {
  "text": "not_a_real_enemy",
  "hash": 2453344752
 },
 {
  "text": "new_monster_id",
  "hash": 2615040844
 },
 {
  "text": "中文",
  "hash": 3297308741
 },
 {
  "text": "standard.vulnerable|p",
  "hash": 3443628802
 }
];

export interface EnemyAsset {
  readonly archetype: string;
  readonly palette: number;
  readonly scale: number;
  readonly boss: boolean;
  /** §398：玩法身份（`boss` / `elite` / `normal`）。`boss` 只留给真 Boss，精英不再冒充。 */
  readonly tier: "boss" | "elite" | "normal";
}

export interface BadgeAsset {
  readonly letters: string;
  readonly palette: number;
}

export const ASSET_COUNTS = {"cards": 295, "enemies": 61, "potions": 33, "relics": 152, "statuses": 149};

export const PALETTES = [
 {
  "name": "ember",
  "body": "#c0503f",
  "accent": "#f0a13a",
  "eye": "#ffe9c9"
 },
 {
  "name": "frost",
  "body": "#3f7cc0",
  "accent": "#7fd0f0",
  "eye": "#e8f7ff"
 },
 {
  "name": "venom",
  "body": "#5f9f4a",
  "accent": "#b8e06a",
  "eye": "#f2ffd9"
 },
 {
  "name": "void",
  "body": "#6b4a9f",
  "accent": "#b28ae0",
  "eye": "#f0e6ff"
 },
 {
  "name": "rust",
  "body": "#8a5a2b",
  "accent": "#d8a24a",
  "eye": "#fff2dc"
 },
 {
  "name": "bone",
  "body": "#9aa7b8",
  "accent": "#e6edf3",
  "eye": "#2b3440"
 },
 {
  "name": "blood",
  "body": "#8f2f3a",
  "accent": "#e0606b",
  "eye": "#ffe0e2"
 },
 {
  "name": "jade",
  "body": "#2f8f7a",
  "accent": "#6fe0c0",
  "eye": "#e0fff8"
 }
] as const;

export const ARCHETYPES = ["slime", "humanoid", "beast", "construct", "gremlin", "slaver", "louse", "sentinel", "spire_guard", "floating_orb", "plant", "crystal", "boss_blob", "boss_machine", "worm", "ghost"] as const;

export const ENEMY_ASSETS: Record<string, EnemyAsset> = {
 "spike_slime_s": {
  "archetype": "slime",
  "palette": 1,
  "scale": 0.78,
  "boss": false,
  "tier": "normal"
 },
 "fat_gremlin": {
  "archetype": "gremlin",
  "palette": 4,
  "scale": 1.0,
  "boss": false,
  "tier": "normal"
 },
 "sneaky_gremlin": {
  "archetype": "gremlin",
  "palette": 3,
  "scale": 1.0,
  "boss": false,
  "tier": "normal"
 },
 "blue_slaver": {
  "archetype": "slaver",
  "palette": 1,
  "scale": 1.0,
  "boss": false,
  "tier": "normal"
 },
 "acid_slime_s": {
  "archetype": "slime",
  "palette": 2,
  "scale": 0.78,
  "boss": false,
  "tier": "normal"
 },
 "acid_slime_m": {
  "archetype": "slime",
  "palette": 2,
  "scale": 1.0,
  "boss": false,
  "tier": "normal"
 },
 "spike_slime_m": {
  "archetype": "slime",
  "palette": 1,
  "scale": 1.0,
  "boss": false,
  "tier": "normal"
 },
 "jaw_worm": {
  "archetype": "worm",
  "palette": 4,
  "scale": 1.0,
  "boss": false,
  "tier": "normal"
 },
 "cultist": {
  "archetype": "humanoid",
  "palette": 3,
  "scale": 1.0,
  "boss": false,
  "tier": "normal"
 },
 "gremlin_wizard": {
  "archetype": "gremlin",
  "palette": 7,
  "scale": 1.0,
  "boss": false,
  "tier": "normal"
 },
 "sentry_1": {
  "archetype": "plant",
  "palette": 6,
  "scale": 1.3,
  "boss": false,
  "tier": "elite"
 },
 "sentry_2": {
  "archetype": "sentinel",
  "palette": 3,
  "scale": 1.3,
  "boss": false,
  "tier": "elite"
 },
 "sentry_3": {
  "archetype": "gremlin",
  "palette": 0,
  "scale": 1.3,
  "boss": false,
  "tier": "elite"
 },
 "slime_boss": {
  "archetype": "boss_blob",
  "palette": 2,
  "scale": 1.55,
  "boss": true,
  "tier": "boss"
 },
 "time_eater": {
  "archetype": "boss_machine",
  "palette": 3,
  "scale": 1.55,
  "boss": true,
  "tier": "boss"
 },
 "shelled_parasite": {
  "archetype": "beast",
  "palette": 2,
  "scale": 1.0,
  "boss": false,
  "tier": "normal"
 },
 "chosen": {
  "archetype": "humanoid",
  "palette": 3,
  "scale": 1.0,
  "boss": false,
  "tier": "normal"
 },
 "byrd": {
  "archetype": "ghost",
  "palette": 2,
  "scale": 1.0,
  "boss": false,
  "tier": "normal"
 },
 "spiker": {
  "archetype": "crystal",
  "palette": 5,
  "scale": 1.0,
  "boss": false,
  "tier": "normal"
 },
 "orb_walker": {
  "archetype": "construct",
  "palette": 7,
  "scale": 1.0,
  "boss": false,
  "tier": "normal"
 },
 "the_champ": {
  "archetype": "boss_machine",
  "palette": 6,
  "scale": 1.55,
  "boss": true,
  "tier": "boss"
 },
 "gremlin_leader": {
  "archetype": "construct",
  "palette": 7,
  "scale": 1.3,
  "boss": false,
  "tier": "elite"
 },
 "giant_head": {
  "archetype": "floating_orb",
  "palette": 5,
  "scale": 1.3,
  "boss": false,
  "tier": "elite"
 },
 "darkling": {
  "archetype": "ghost",
  "palette": 3,
  "scale": 1.0,
  "boss": false,
  "tier": "normal"
 },
 "maw": {
  "archetype": "gremlin",
  "palette": 0,
  "scale": 1.0,
  "boss": false,
  "tier": "normal"
 },
 "spire_growth": {
  "archetype": "plant",
  "palette": 7,
  "scale": 1.0,
  "boss": false,
  "tier": "normal"
 },
 "louse_red": {
  "archetype": "louse",
  "palette": 6,
  "scale": 1.0,
  "boss": false,
  "tier": "normal"
 },
 "louse_green": {
  "archetype": "crystal",
  "palette": 7,
  "scale": 1.0,
  "boss": false,
  "tier": "normal"
 },
 "fungi_beast": {
  "archetype": "plant",
  "palette": 3,
  "scale": 1.0,
  "boss": false,
  "tier": "normal"
 },
 "slaver_red": {
  "archetype": "plant",
  "palette": 6,
  "scale": 1.0,
  "boss": false,
  "tier": "normal"
 },
 "gremlin_nob": {
  "archetype": "boss_machine",
  "palette": 0,
  "scale": 1.3,
  "boss": false,
  "tier": "elite"
 },
 "lagavulin": {
  "archetype": "beast",
  "palette": 6,
  "scale": 1.3,
  "boss": false,
  "tier": "elite"
 },
 "book_of_stabbing": {
  "archetype": "sentinel",
  "palette": 3,
  "scale": 1.3,
  "boss": false,
  "tier": "elite"
 },
 "taskmaster": {
  "archetype": "slaver",
  "palette": 4,
  "scale": 1.3,
  "boss": false,
  "tier": "elite"
 },
 "nemesis": {
  "archetype": "sentinel",
  "palette": 3,
  "scale": 1.3,
  "boss": false,
  "tier": "elite"
 },
 "reptomancer": {
  "archetype": "ghost",
  "palette": 3,
  "scale": 1.3,
  "boss": false,
  "tier": "elite"
 },
 "dagger": {
  "archetype": "crystal",
  "palette": 5,
  "scale": 1.0,
  "boss": false,
  "tier": "normal"
 },
 "the_guardian": {
  "archetype": "boss_machine",
  "palette": 5,
  "scale": 1.55,
  "boss": true,
  "tier": "boss"
 },
 "hexaghost": {
  "archetype": "floating_orb",
  "palette": 3,
  "scale": 1.55,
  "boss": true,
  "tier": "boss"
 },
 "bronze_automaton": {
  "archetype": "boss_machine",
  "palette": 4,
  "scale": 1.55,
  "boss": true,
  "tier": "boss"
 },
 "bronze_orb": {
  "archetype": "floating_orb",
  "palette": 4,
  "scale": 1.0,
  "boss": false,
  "tier": "normal"
 },
 "the_collector": {
  "archetype": "gremlin",
  "palette": 0,
  "scale": 1.55,
  "boss": true,
  "tier": "boss"
 },
 "torch_head": {
  "archetype": "crystal",
  "palette": 0,
  "scale": 1.0,
  "boss": false,
  "tier": "normal"
 },
 "awakened_one": {
  "archetype": "boss_blob",
  "palette": 7,
  "scale": 1.55,
  "boss": true,
  "tier": "boss"
 },
 "donu": {
  "archetype": "construct",
  "palette": 0,
  "scale": 1.55,
  "boss": true,
  "tier": "boss"
 },
 "deca": {
  "archetype": "construct",
  "palette": 1,
  "scale": 1.55,
  "boss": true,
  "tier": "boss"
 },
 "looter": {
  "archetype": "humanoid",
  "palette": 5,
  "scale": 1.0,
  "boss": false,
  "tier": "normal"
 },
 "spike_slime_l": {
  "archetype": "slime",
  "palette": 1,
  "scale": 1.2,
  "boss": false,
  "tier": "normal"
 },
 "acid_slime_l": {
  "archetype": "slime",
  "palette": 2,
  "scale": 1.2,
  "boss": false,
  "tier": "normal"
 },
 "snecko": {
  "archetype": "plant",
  "palette": 6,
  "scale": 1.0,
  "boss": false,
  "tier": "normal"
 },
 "spheric_guardian": {
  "archetype": "floating_orb",
  "palette": 4,
  "scale": 1.0,
  "boss": false,
  "tier": "normal"
 },
 "snake_plant": {
  "archetype": "plant",
  "palette": 7,
  "scale": 1.0,
  "boss": false,
  "tier": "normal"
 },
 "centurion": {
  "archetype": "sentinel",
  "palette": 4,
  "scale": 1.0,
  "boss": false,
  "tier": "normal"
 },
 "mystic": {
  "archetype": "humanoid",
  "palette": 3,
  "scale": 1.0,
  "boss": false,
  "tier": "normal"
 },
 "mugger": {
  "archetype": "louse",
  "palette": 2,
  "scale": 1.0,
  "boss": false,
  "tier": "normal"
 },
 "repulsor": {
  "archetype": "construct",
  "palette": 3,
  "scale": 1.0,
  "boss": false,
  "tier": "normal"
 },
 "exploder": {
  "archetype": "crystal",
  "palette": 0,
  "scale": 1.0,
  "boss": false,
  "tier": "normal"
 },
 "transient": {
  "archetype": "ghost",
  "palette": 5,
  "scale": 1.0,
  "boss": false,
  "tier": "normal"
 },
 "pointy": {
  "archetype": "spire_guard",
  "palette": 4,
  "scale": 1.0,
  "boss": false,
  "tier": "normal"
 },
 "romeo": {
  "archetype": "humanoid",
  "palette": 5,
  "scale": 1.0,
  "boss": false,
  "tier": "normal"
 },
 "bear": {
  "archetype": "construct",
  "palette": 7,
  "scale": 1.0,
  "boss": false,
  "tier": "normal"
 }
};

export const BADGE_ASSETS: Record<"cards" | "relics" | "potions" | "statuses", Record<string, BadgeAsset>> = {
 "cards": {
  "strike": {
   "letters": "ST",
   "palette": 0
  },
  "defend": {
   "letters": "DE",
   "palette": 1
  },
  "bash": {
   "letters": "BA",
   "palette": 6
  },
  "slimed": {
   "letters": "SL",
   "palette": 4
  },
  "strike+": {
   "letters": "ST",
   "palette": 3
  },
  "defend+": {
   "letters": "DE",
   "palette": 5
  },
  "bash+": {
   "letters": "BA",
   "palette": 7
  },
  "twin_strike": {
   "letters": "TS",
   "palette": 5
  },
  "iron_wave": {
   "letters": "IW",
   "palette": 2
  },
  "clothesline": {
   "letters": "CL",
   "palette": 2
  },
  "anger": {
   "letters": "AN",
   "palette": 7
  },
  "uppercut": {
   "letters": "UP",
   "palette": 4
  },
  "injury": {
   "letters": "IN",
   "palette": 7
  },
  "sentinel": {
   "letters": "SE",
   "palette": 0
  },
  "patient_guard": {
   "letters": "PG",
   "palette": 3
  },
  "swift_strike": {
   "letters": "SS",
   "palette": 6
  },
  "whirlwind": {
   "letters": "WH",
   "palette": 2
  },
  "whirlwind+": {
   "letters": "WH",
   "palette": 3
  },
  "apparition": {
   "letters": "AP",
   "palette": 1
  },
  "buffer": {
   "letters": "BU",
   "palette": 2
  },
  "anger+": {
   "letters": "AN",
   "palette": 4
  },
  "twin_strike+": {
   "letters": "TS",
   "palette": 2
  },
  "iron_wave+": {
   "letters": "IW",
   "palette": 3
  },
  "clothesline+": {
   "letters": "CL",
   "palette": 3
  },
  "uppercut+": {
   "letters": "UP",
   "palette": 5
  },
  "sentinel+": {
   "letters": "SE",
   "palette": 1
  },
  "patient_guard+": {
   "letters": "PG",
   "palette": 0
  },
  "swift_strike+": {
   "letters": "SS",
   "palette": 7
  },
  "apparition+": {
   "letters": "AP",
   "palette": 6
  },
  "buffer+": {
   "letters": "BU",
   "palette": 3
  },
  "inflame": {
   "letters": "IN",
   "palette": 2
  },
  "inflame+": {
   "letters": "IN",
   "palette": 3
  },
  "metallicize": {
   "letters": "ME",
   "palette": 5
  },
  "metallicize+": {
   "letters": "ME",
   "palette": 2
  },
  "combust": {
   "letters": "CO",
   "palette": 7
  },
  "combust+": {
   "letters": "CO",
   "palette": 4
  },
  "wound": {
   "letters": "WO",
   "palette": 3
  },
  "burn": {
   "letters": "BU",
   "palette": 5
  },
  "bandage_up": {
   "letters": "BU",
   "palette": 6
  },
  "blind": {
   "letters": "BL",
   "palette": 7
  },
  "dark_shackles": {
   "letters": "DS",
   "palette": 5
  },
  "ascenders_bane": {
   "letters": "AB",
   "palette": 3
  },
  "dazed": {
   "letters": "DA",
   "palette": 6
  },
  "burn+": {
   "letters": "BU",
   "palette": 2
  },
  "void": {
   "letters": "VO",
   "palette": 2
  },
  "barricade": {
   "letters": "BA",
   "palette": 7
  },
  "blur": {
   "letters": "BL",
   "palette": 1
  },
  "barricade+": {
   "letters": "BA",
   "palette": 4
  },
  "blur+": {
   "letters": "BL",
   "palette": 6
  },
  "berserk": {
   "letters": "BE",
   "palette": 6
  },
  "berserk+": {
   "letters": "BE",
   "palette": 7
  },
  "cleave": {
   "letters": "CL",
   "palette": 4
  },
  "cleave+": {
   "letters": "CL",
   "palette": 5
  },
  "pommel_strike": {
   "letters": "PS",
   "palette": 1
  },
  "pommel_strike+": {
   "letters": "PS",
   "palette": 6
  },
  "shrug_it_off": {
   "letters": "SI",
   "palette": 3
  },
  "shrug_it_off+": {
   "letters": "SI",
   "palette": 0
  },
  "thunderclap": {
   "letters": "TH",
   "palette": 4
  },
  "thunderclap+": {
   "letters": "TH",
   "palette": 5
  },
  "bludgeon": {
   "letters": "BL",
   "palette": 2
  },
  "bludgeon+": {
   "letters": "BL",
   "palette": 3
  },
  "impervious": {
   "letters": "IM",
   "palette": 5
  },
  "impervious+": {
   "letters": "IM",
   "palette": 2
  },
  "pummel": {
   "letters": "PU",
   "palette": 0
  },
  "pummel+": {
   "letters": "PU",
   "palette": 1
  },
  "wild_strike": {
   "letters": "WS",
   "palette": 3
  },
  "wild_strike+": {
   "letters": "WS",
   "palette": 0
  },
  "ghostly_armor": {
   "letters": "GA",
   "palette": 4
  },
  "ghostly_armor+": {
   "letters": "GA",
   "palette": 5
  },
  "battle_trance": {
   "letters": "BT",
   "palette": 2
  },
  "battle_trance+": {
   "letters": "BT",
   "palette": 3
  },
  "doubt": {
   "letters": "DO",
   "palette": 2
  },
  "writhe": {
   "letters": "WR",
   "palette": 7
  },
  "second_wind": {
   "letters": "SW",
   "palette": 3
  },
  "second_wind+": {
   "letters": "SW",
   "palette": 0
  },
  "fiend_fire": {
   "letters": "FF",
   "palette": 7
  },
  "fiend_fire+": {
   "letters": "FF",
   "palette": 4
  },
  "dual_wield": {
   "letters": "DW",
   "palette": 6
  },
  "dual_wield+": {
   "letters": "DW",
   "palette": 7
  },
  "armaments": {
   "letters": "AR",
   "palette": 6
  },
  "armaments+": {
   "letters": "AR",
   "palette": 7
  },
  "warcry": {
   "letters": "WA",
   "palette": 6
  },
  "warcry+": {
   "letters": "WA",
   "palette": 7
  },
  "nightmare": {
   "letters": "NI",
   "palette": 1
  },
  "nightmare+": {
   "letters": "NI",
   "palette": 6
  },
  "sword_boomerang": {
   "letters": "SB",
   "palette": 6
  },
  "sword_boomerang+": {
   "letters": "SB",
   "palette": 7
  },
  "body_slam": {
   "letters": "BS",
   "palette": 0
  },
  "body_slam+": {
   "letters": "BS",
   "palette": 1
  },
  "rip_and_tear": {
   "letters": "RA",
   "palette": 2
  },
  "rip_and_tear+": {
   "letters": "RA",
   "palette": 3
  },
  "rampage": {
   "letters": "RA",
   "palette": 3
  },
  "rampage+": {
   "letters": "RA",
   "palette": 0
  },
  "searing_blow": {
   "letters": "SB",
   "palette": 2
  },
  "searing_blow+": {
   "letters": "SB",
   "palette": 3
  },
  "searing_blow++": {
   "letters": "SB",
   "palette": 0
  },
  "searing_blow+++": {
   "letters": "SB",
   "palette": 1
  },
  "searing_blow++++": {
   "letters": "SB",
   "palette": 6
  },
  "searing_blow+++++": {
   "letters": "SB",
   "palette": 7
  },
  "searing_blow++++++": {
   "letters": "SB",
   "palette": 4
  },
  "searing_blow+++++++": {
   "letters": "SB",
   "palette": 5
  },
  "flex": {
   "letters": "FL",
   "palette": 7
  },
  "flex+": {
   "letters": "FL",
   "palette": 4
  },
  "limit_break": {
   "letters": "LB",
   "palette": 3
  },
  "limit_break+": {
   "letters": "LB",
   "palette": 0
  },
  "perfected_strike": {
   "letters": "PS",
   "palette": 3
  },
  "perfected_strike+": {
   "letters": "PS",
   "palette": 0
  },
  "true_grit": {
   "letters": "TG",
   "palette": 1
  },
  "true_grit+": {
   "letters": "TG",
   "palette": 6
  },
  "reaper": {
   "letters": "RE",
   "palette": 7
  },
  "reaper+": {
   "letters": "RE",
   "palette": 4
  },
  "skewer": {
   "letters": "SK",
   "palette": 5
  },
  "skewer+": {
   "letters": "SK",
   "palette": 2
  },
  "malaise": {
   "letters": "MA",
   "palette": 4
  },
  "malaise+": {
   "letters": "MA",
   "palette": 5
  },
  "entrench": {
   "letters": "EN",
   "palette": 1
  },
  "entrench+": {
   "letters": "EN",
   "palette": 6
  },
  "carnage": {
   "letters": "CA",
   "palette": 3
  },
  "carnage+": {
   "letters": "CA",
   "palette": 0
  },
  "disarm": {
   "letters": "DI",
   "palette": 6
  },
  "disarm+": {
   "letters": "DI",
   "palette": 7
  },
  "immolate": {
   "letters": "IM",
   "palette": 2
  },
  "immolate+": {
   "letters": "IM",
   "palette": 3
  },
  "intimidate": {
   "letters": "IN",
   "palette": 6
  },
  "intimidate+": {
   "letters": "IN",
   "palette": 7
  },
  "shockwave": {
   "letters": "SH",
   "palette": 3
  },
  "shockwave+": {
   "letters": "SH",
   "palette": 0
  },
  "seeing_red": {
   "letters": "SR",
   "palette": 5
  },
  "seeing_red+": {
   "letters": "SR",
   "palette": 2
  },
  "flame_barrier": {
   "letters": "FB",
   "palette": 7
  },
  "flame_barrier+": {
   "letters": "FB",
   "palette": 4
  },
  "rage": {
   "letters": "RA",
   "palette": 1
  },
  "rage+": {
   "letters": "RA",
   "palette": 6
  },
  "power_through": {
   "letters": "PT",
   "palette": 3
  },
  "power_through+": {
   "letters": "PT",
   "palette": 0
  },
  "reckless_charge": {
   "letters": "RC",
   "palette": 7
  },
  "reckless_charge+": {
   "letters": "RC",
   "palette": 4
  },
  "sever_soul": {
   "letters": "SS",
   "palette": 5
  },
  "sever_soul+": {
   "letters": "SS",
   "palette": 2
  },
  "dropkick": {
   "letters": "DR",
   "palette": 7
  },
  "dropkick+": {
   "letters": "DR",
   "palette": 4
  },
  "headbutt": {
   "letters": "HE",
   "palette": 7
  },
  "headbutt+": {
   "letters": "HE",
   "palette": 4
  },
  "demon_form": {
   "letters": "DF",
   "palette": 2
  },
  "demon_form+": {
   "letters": "DF",
   "palette": 3
  },
  "bloodletting": {
   "letters": "BL",
   "palette": 5
  },
  "bloodletting+": {
   "letters": "BL",
   "palette": 2
  },
  "hemokinesis": {
   "letters": "HE",
   "palette": 3
  },
  "hemokinesis+": {
   "letters": "HE",
   "palette": 0
  },
  "offering": {
   "letters": "OF",
   "palette": 2
  },
  "offering+": {
   "letters": "OF",
   "palette": 3
  },
  "brutality": {
   "letters": "BR",
   "palette": 4
  },
  "brutality+": {
   "letters": "BR",
   "palette": 5
  },
  "rupture": {
   "letters": "RU",
   "palette": 1
  },
  "rupture+": {
   "letters": "RU",
   "palette": 6
  },
  "juggernaut": {
   "letters": "JU",
   "palette": 4
  },
  "juggernaut+": {
   "letters": "JU",
   "palette": 5
  },
  "evolve": {
   "letters": "EV",
   "palette": 5
  },
  "evolve+": {
   "letters": "EV",
   "palette": 2
  },
  "fire_breathing": {
   "letters": "FB",
   "palette": 5
  },
  "fire_breathing+": {
   "letters": "FB",
   "palette": 2
  },
  "dark_embrace": {
   "letters": "DE",
   "palette": 6
  },
  "dark_embrace+": {
   "letters": "DE",
   "palette": 7
  },
  "feel_no_pain": {
   "letters": "FN",
   "palette": 7
  },
  "feel_no_pain+": {
   "letters": "FN",
   "palette": 4
  },
  "heavy_blade": {
   "letters": "HB",
   "palette": 2
  },
  "heavy_blade+": {
   "letters": "HB",
   "palette": 3
  },
  "double_tap": {
   "letters": "DT",
   "palette": 7
  },
  "double_tap+": {
   "letters": "DT",
   "palette": 4
  },
  "exhume": {
   "letters": "EX",
   "palette": 4
  },
  "exhume+": {
   "letters": "EX",
   "palette": 5
  },
  "feed": {
   "letters": "FE",
   "palette": 4
  },
  "feed+": {
   "letters": "FE",
   "palette": 5
  },
  "clash": {
   "letters": "CL",
   "palette": 1
  },
  "clash+": {
   "letters": "CL",
   "palette": 6
  },
  "burning_pact": {
   "letters": "BP",
   "palette": 0
  },
  "burning_pact+": {
   "letters": "BP",
   "palette": 1
  },
  "infernal_blade": {
   "letters": "IB",
   "palette": 2
  },
  "infernal_blade+": {
   "letters": "IB",
   "palette": 3
  },
  "havoc": {
   "letters": "HA",
   "palette": 1
  },
  "havoc+": {
   "letters": "HA",
   "palette": 6
  },
  "spot_weakness": {
   "letters": "SW",
   "palette": 6
  },
  "spot_weakness+": {
   "letters": "SW",
   "palette": 7
  },
  "blood_for_blood": {
   "letters": "BF",
   "palette": 7
  },
  "blood_for_blood+": {
   "letters": "BF",
   "palette": 4
  },
  "corruption": {
   "letters": "CO",
   "palette": 5
  },
  "corruption+": {
   "letters": "CO",
   "palette": 2
  },
  "trip": {
   "letters": "TR",
   "palette": 3
  },
  "trip+": {
   "letters": "TR",
   "palette": 0
  },
  "panacea": {
   "letters": "PA",
   "palette": 1
  },
  "panacea+": {
   "letters": "PA",
   "palette": 6
  },
  "finesse": {
   "letters": "FI",
   "palette": 1
  },
  "finesse+": {
   "letters": "FI",
   "palette": 6
  },
  "flash_of_steel": {
   "letters": "FO",
   "palette": 6
  },
  "flash_of_steel+": {
   "letters": "FO",
   "palette": 7
  },
  "good_instincts": {
   "letters": "GI",
   "palette": 7
  },
  "good_instincts+": {
   "letters": "GI",
   "palette": 4
  },
  "master_of_strategy": {
   "letters": "MO",
   "palette": 6
  },
  "master_of_strategy+": {
   "letters": "MO",
   "palette": 7
  },
  "dramatic_entrance": {
   "letters": "DE",
   "palette": 0
  },
  "dramatic_entrance+": {
   "letters": "DE",
   "palette": 1
  },
  "impatience": {
   "letters": "IM",
   "palette": 5
  },
  "impatience+": {
   "letters": "IM",
   "palette": 2
  },
  "deep_breath": {
   "letters": "DB",
   "palette": 5
  },
  "deep_breath+": {
   "letters": "DB",
   "palette": 2
  },
  "insight": {
   "letters": "IN",
   "palette": 4
  },
  "insight+": {
   "letters": "IN",
   "palette": 5
  },
  "miracle": {
   "letters": "MI",
   "palette": 3
  },
  "miracle+": {
   "letters": "MI",
   "palette": 0
  },
  "mayhem": {
   "letters": "MA",
   "palette": 5
  },
  "mayhem+": {
   "letters": "MA",
   "palette": 2
  },
  "magnetism": {
   "letters": "MA",
   "palette": 1
  },
  "magnetism+": {
   "letters": "MA",
   "palette": 6
  },
  "chrysalis": {
   "letters": "CH",
   "palette": 6
  },
  "chrysalis+": {
   "letters": "CH",
   "palette": 7
  },
  "metamorphosis": {
   "letters": "ME",
   "palette": 3
  },
  "metamorphosis+": {
   "letters": "ME",
   "palette": 0
  },
  "jack_of_all_trades": {
   "letters": "JO",
   "palette": 5
  },
  "jack_of_all_trades+": {
   "letters": "JO",
   "palette": 2
  },
  "transmutation": {
   "letters": "TR",
   "palette": 1
  },
  "transmutation+": {
   "letters": "TR",
   "palette": 6
  },
  "secret_technique": {
   "letters": "ST",
   "palette": 5
  },
  "secret_technique+": {
   "letters": "ST",
   "palette": 2
  },
  "secret_weapon": {
   "letters": "SW",
   "palette": 5
  },
  "secret_weapon+": {
   "letters": "SW",
   "palette": 2
  },
  "violence": {
   "letters": "VI",
   "palette": 1
  },
  "violence+": {
   "letters": "VI",
   "palette": 6
  },
  "purity": {
   "letters": "PU",
   "palette": 1
  },
  "purity+": {
   "letters": "PU",
   "palette": 6
  },
  "apotheosis": {
   "letters": "AP",
   "palette": 7
  },
  "apotheosis+": {
   "letters": "AP",
   "palette": 4
  },
  "panic_button": {
   "letters": "PB",
   "palette": 0
  },
  "panic_button+": {
   "letters": "PB",
   "palette": 1
  },
  "thinking_ahead": {
   "letters": "TA",
   "palette": 6
  },
  "thinking_ahead+": {
   "letters": "TA",
   "palette": 7
  },
  "mind_blast": {
   "letters": "MB",
   "palette": 1
  },
  "mind_blast+": {
   "letters": "MB",
   "palette": 6
  },
  "enlightenment": {
   "letters": "EN",
   "palette": 2
  },
  "enlightenment+": {
   "letters": "EN",
   "palette": 3
  },
  "madness": {
   "letters": "MA",
   "palette": 1
  },
  "madness+": {
   "letters": "MA",
   "palette": 6
  },
  "omega": {
   "letters": "OM",
   "palette": 3
  },
  "omega+": {
   "letters": "OM",
   "palette": 0
  },
  "panache": {
   "letters": "PA",
   "palette": 4
  },
  "panache+": {
   "letters": "PA",
   "palette": 5
  },
  "sadistic_nature": {
   "letters": "SN",
   "palette": 2
  },
  "sadistic_nature+": {
   "letters": "SN",
   "palette": 3
  },
  "the_bomb": {
   "letters": "TB",
   "palette": 4
  },
  "the_bomb+": {
   "letters": "TB",
   "palette": 5
  },
  "ritual_dagger": {
   "letters": "RD",
   "palette": 6
  },
  "ritual_dagger+": {
   "letters": "RD",
   "palette": 7
  },
  "hand_of_greed": {
   "letters": "HO",
   "palette": 5
  },
  "hand_of_greed+": {
   "letters": "HO",
   "palette": 2
  },
  "discovery": {
   "letters": "DI",
   "palette": 2
  },
  "discovery+": {
   "letters": "DI",
   "palette": 3
  },
  "forethought": {
   "letters": "FO",
   "palette": 7
  },
  "forethought+": {
   "letters": "FO",
   "palette": 4
  },
  "clumsy": {
   "letters": "CL",
   "palette": 5
  },
  "curse_of_the_bell": {
   "letters": "CO",
   "palette": 6
  },
  "decay": {
   "letters": "DE",
   "palette": 6
  },
  "necronomicurse": {
   "letters": "NE",
   "palette": 6
  },
  "normality": {
   "letters": "NO",
   "palette": 5
  },
  "pain": {
   "letters": "PA",
   "palette": 0
  },
  "parasite": {
   "letters": "PA",
   "palette": 5
  },
  "pride": {
   "letters": "PR",
   "palette": 2
  },
  "regret": {
   "letters": "RE",
   "palette": 1
  },
  "shame": {
   "letters": "SH",
   "palette": 4
  },
  "bite": {
   "letters": "BI",
   "palette": 2
  },
  "bite+": {
   "letters": "BI",
   "palette": 3
  },
  "expunger": {
   "letters": "EX",
   "palette": 6
  },
  "expunger+": {
   "letters": "EX",
   "palette": 7
  },
  "shiv": {
   "letters": "SH",
   "palette": 0
  },
  "shiv+": {
   "letters": "SH",
   "palette": 1
  },
  "smite": {
   "letters": "SM",
   "palette": 4
  },
  "smite+": {
   "letters": "SM",
   "palette": 5
  },
  "beta": {
   "letters": "BE",
   "palette": 2
  },
  "beta+": {
   "letters": "BE",
   "palette": 3
  },
  "through_violence": {
   "letters": "TV",
   "palette": 3
  },
  "through_violence+": {
   "letters": "TV",
   "palette": 0
  },
  "j.a.x.": {
   "letters": "JA",
   "palette": 1
  },
  "j.a.x.+": {
   "letters": "JA",
   "palette": 6
  },
  "safety": {
   "letters": "SA",
   "palette": 6
  },
  "safety+": {
   "letters": "SA",
   "palette": 7
  },
  "become_almighty": {
   "letters": "BA",
   "palette": 5
  },
  "become_almighty+": {
   "letters": "BA",
   "palette": 2
  },
  "live_forever": {
   "letters": "LF",
   "palette": 2
  },
  "live_forever+": {
   "letters": "LF",
   "palette": 3
  },
  "fame_and_fortune": {
   "letters": "FA",
   "palette": 3
  },
  "fame_and_fortune+": {
   "letters": "FA",
   "palette": 0
  },
  "wish": {
   "letters": "WI",
   "palette": 7
  },
  "wish+": {
   "letters": "WI",
   "palette": 4
  },
  "conjure_blade": {
   "letters": "CB",
   "palette": 1
  },
  "conjure_blade+": {
   "letters": "CB",
   "palette": 6
  },
  "jax": {
   "letters": "JA",
   "palette": 7
  },
  "jax+": {
   "letters": "JA",
   "palette": 4
  }
 },
 "relics": {
  "akabeko": {
   "letters": "AK",
   "palette": 1
  },
  "anchor": {
   "letters": "AN",
   "palette": 1
  },
  "ancient_tea_set": {
   "letters": "AT",
   "palette": 3
  },
  "art_of_war": {
   "letters": "AO",
   "palette": 5
  },
  "astrolabe": {
   "letters": "AS",
   "palette": 4
  },
  "bag_of_marbles": {
   "letters": "BO",
   "palette": 4
  },
  "bag_of_preparation": {
   "letters": "BO",
   "palette": 3
  },
  "bird_faced_urn": {
   "letters": "BF",
   "palette": 0
  },
  "black_blood": {
   "letters": "BB",
   "palette": 1
  },
  "black_star": {
   "letters": "BS",
   "palette": 3
  },
  "blood_vial": {
   "letters": "BV",
   "palette": 6
  },
  "bloody_idol": {
   "letters": "BI",
   "palette": 7
  },
  "brimstone": {
   "letters": "BR",
   "palette": 6
  },
  "bronze_scales": {
   "letters": "BS",
   "palette": 7
  },
  "burning_blood": {
   "letters": "BB",
   "palette": 0
  },
  "busted_crown": {
   "letters": "BC",
   "palette": 4
  },
  "calipers": {
   "letters": "CA",
   "palette": 0
  },
  "captains_wheel": {
   "letters": "CW",
   "palette": 6
  },
  "centennial_puzzle": {
   "letters": "CP",
   "palette": 7
  },
  "ceramic_fish": {
   "letters": "CF",
   "palette": 0
  },
  "champion_belt": {
   "letters": "CB",
   "palette": 0
  },
  "charons_ashes": {
   "letters": "CA",
   "palette": 4
  },
  "cloak_clasp": {
   "letters": "CC",
   "palette": 7
  },
  "clockwork_souvenir": {
   "letters": "CS",
   "palette": 2
  },
  "coffee_dripper": {
   "letters": "CD",
   "palette": 2
  },
  "darkstone_periapt": {
   "letters": "DP",
   "palette": 6
  },
  "dream_catcher": {
   "letters": "DC",
   "palette": 5
  },
  "du_vu_doll": {
   "letters": "DV",
   "palette": 0
  },
  "duality": {
   "letters": "DU",
   "palette": 3
  },
  "ectoplasm": {
   "letters": "EC",
   "palette": 1
  },
  "empty_cage": {
   "letters": "EC",
   "palette": 5
  },
  "eternal_feather": {
   "letters": "EF",
   "palette": 4
  },
  "fossilized_helix": {
   "letters": "FH",
   "palette": 2
  },
  "frozen_egg": {
   "letters": "FE",
   "palette": 7
  },
  "fusion_hammer": {
   "letters": "FH",
   "palette": 2
  },
  "ginger": {
   "letters": "GI",
   "palette": 3
  },
  "girya": {
   "letters": "GI",
   "palette": 1
  },
  "golden_idol": {
   "letters": "GI",
   "palette": 5
  },
  "gremlin_horn": {
   "letters": "GH",
   "palette": 5
  },
  "gremlin_visage": {
   "letters": "GV",
   "palette": 5
  },
  "happy_flower": {
   "letters": "HF",
   "palette": 3
  },
  "horn_cleat": {
   "letters": "HC",
   "palette": 2
  },
  "ice_cream": {
   "letters": "IC",
   "palette": 7
  },
  "incense_burner": {
   "letters": "IB",
   "palette": 5
  },
  "ink_bottle": {
   "letters": "IB",
   "palette": 2
  },
  "juzu_bracelet": {
   "letters": "JB",
   "palette": 4
  },
  "kunai": {
   "letters": "KU",
   "palette": 5
  },
  "lantern": {
   "letters": "LA",
   "palette": 5
  },
  "lees_waffle": {
   "letters": "LW",
   "palette": 6
  },
  "letter_opener": {
   "letters": "LO",
   "palette": 7
  },
  "lizard_tail": {
   "letters": "LT",
   "palette": 2
  },
  "mango": {
   "letters": "MA",
   "palette": 3
  },
  "mark_of_pain": {
   "letters": "MO",
   "palette": 7
  },
  "mark_of_the_bloom": {
   "letters": "MO",
   "palette": 2
  },
  "maw_bank": {
   "letters": "MB",
   "palette": 5
  },
  "meal_ticket": {
   "letters": "MT",
   "palette": 5
  },
  "meat_on_the_bone": {
   "letters": "MO",
   "palette": 3
  },
  "membership_card": {
   "letters": "MC",
   "palette": 2
  },
  "mercury_hourglass": {
   "letters": "MH",
   "palette": 1
  },
  "molten_egg": {
   "letters": "ME",
   "palette": 6
  },
  "mutagenic_strength": {
   "letters": "MS",
   "palette": 4
  },
  "nunchaku": {
   "letters": "NU",
   "palette": 6
  },
  "odd_mushroom": {
   "letters": "OM",
   "palette": 3
  },
  "oddly_smooth_stone": {
   "letters": "OS",
   "palette": 4
  },
  "old_coin": {
   "letters": "OC",
   "palette": 0
  },
  "omamori": {
   "letters": "OM",
   "palette": 3
  },
  "orichalcum": {
   "letters": "OR",
   "palette": 2
  },
  "ornamental_fan": {
   "letters": "OF",
   "palette": 4
  },
  "pandoras_box": {
   "letters": "PB",
   "palette": 5
  },
  "pantograph": {
   "letters": "PA",
   "palette": 5
  },
  "paper_krane": {
   "letters": "PK",
   "palette": 5
  },
  "paper_phrog": {
   "letters": "PP",
   "palette": 4
  },
  "peace_pipe": {
   "letters": "PP",
   "palette": 0
  },
  "pear": {
   "letters": "PE",
   "palette": 7
  },
  "pen_nib": {
   "letters": "PN",
   "palette": 0
  },
  "philosophers_stone": {
   "letters": "PS",
   "palette": 5
  },
  "pocketwatch": {
   "letters": "PO",
   "palette": 4
  },
  "potion_belt": {
   "letters": "PB",
   "palette": 4
  },
  "prayer_wheel": {
   "letters": "PW",
   "palette": 4
  },
  "preserved_insect": {
   "letters": "PI",
   "palette": 2
  },
  "question_card": {
   "letters": "QC",
   "palette": 6
  },
  "red_mask": {
   "letters": "RM",
   "palette": 3
  },
  "red_skull": {
   "letters": "RS",
   "palette": 0
  },
  "regal_pillow": {
   "letters": "RP",
   "palette": 2
  },
  "ring_of_the_serpent": {
   "letters": "RO",
   "palette": 7
  },
  "ring_of_the_snake": {
   "letters": "RO",
   "palette": 4
  },
  "runic_cube": {
   "letters": "RC",
   "palette": 4
  },
  "runic_pyramid": {
   "letters": "RP",
   "palette": 3
  },
  "self_forming_clay": {
   "letters": "SF",
   "palette": 0
  },
  "shovel": {
   "letters": "SH",
   "palette": 0
  },
  "shuriken": {
   "letters": "SH",
   "palette": 4
  },
  "slavers_collar": {
   "letters": "SC",
   "palette": 7
  },
  "sling_of_courage": {
   "letters": "SO",
   "palette": 3
  },
  "smiling_mask": {
   "letters": "SM",
   "palette": 7
  },
  "snecko_skull": {
   "letters": "SS",
   "palette": 6
  },
  "sozu": {
   "letters": "SO",
   "palette": 0
  },
  "ssserpent_head": {
   "letters": "SH",
   "palette": 3
  },
  "stone_calendar": {
   "letters": "SC",
   "palette": 7
  },
  "strawberry": {
   "letters": "ST",
   "palette": 2
  },
  "the_boot": {
   "letters": "TB",
   "palette": 7
  },
  "the_courier": {
   "letters": "TC",
   "palette": 6
  },
  "the_specimen": {
   "letters": "TS",
   "palette": 5
  },
  "thread_and_needle": {
   "letters": "TA",
   "palette": 1
  },
  "tiny_chest": {
   "letters": "TC",
   "palette": 7
  },
  "torii": {
   "letters": "TO",
   "palette": 2
  },
  "toxic_egg": {
   "letters": "TE",
   "palette": 0
  },
  "toy_ornithopter": {
   "letters": "TO",
   "palette": 4
  },
  "tungsten_rod": {
   "letters": "TR",
   "palette": 1
  },
  "turnip": {
   "letters": "TU",
   "palette": 1
  },
  "twisted_funnel": {
   "letters": "TF",
   "palette": 0
  },
  "unceasing_top": {
   "letters": "UT",
   "palette": 4
  },
  "vajra": {
   "letters": "VA",
   "palette": 5
  },
  "war_paint": {
   "letters": "WP",
   "palette": 4
  },
  "whetstone": {
   "letters": "WH",
   "palette": 2
  },
  "white_beast_statue": {
   "letters": "WB",
   "palette": 1
  },
  "snecko_eye": {
   "letters": "SE",
   "palette": 6
  },
  "cultist_headpiece": {
   "letters": "CH",
   "palette": 2
  },
  "spirit_poop": {
   "letters": "SP",
   "palette": 5
  },
  "face_of_cleric": {
   "letters": "FO",
   "palette": 3
  },
  "nloths_hungry_face": {
   "letters": "NH",
   "palette": 3
  },
  "nloths_gift": {
   "letters": "NG",
   "palette": 6
  },
  "matryoshka": {
   "letters": "MA",
   "palette": 4
  },
  "cursed_key": {
   "letters": "CK",
   "palette": 5
  },
  "calling_bell": {
   "letters": "CB",
   "palette": 3
  },
  "sacred_bark": {
   "letters": "SB",
   "palette": 2
  },
  "cauldron": {
   "letters": "CA",
   "palette": 1
  },
  "dollys_mirror": {
   "letters": "DM",
   "palette": 4
  },
  "orrery": {
   "letters": "OR",
   "palette": 2
  },
  "tiny_house": {
   "letters": "TH",
   "palette": 6
  },
  "singing_bowl": {
   "letters": "SB",
   "palette": 5
  },
  "the_abacus": {
   "letters": "TA",
   "palette": 0
  },
  "sundial": {
   "letters": "SU",
   "palette": 1
  },
  "hand_drill": {
   "letters": "HD",
   "palette": 0
  },
  "chemical_x": {
   "letters": "CX",
   "palette": 0
  },
  "strike_dummy": {
   "letters": "SD",
   "palette": 2
  },
  "velvet_choker": {
   "letters": "VC",
   "palette": 0
  },
  "runic_dome": {
   "letters": "RD",
   "palette": 6
  },
  "magic_flower": {
   "letters": "MF",
   "palette": 4
  },
  "medical_kit": {
   "letters": "MK",
   "palette": 1
  },
  "blue_candle": {
   "letters": "BC",
   "palette": 5
  },
  "enchiridion": {
   "letters": "EN",
   "palette": 5
  },
  "orange_pellets": {
   "letters": "OP",
   "palette": 1
  },
  "dead_branch": {
   "letters": "DB",
   "palette": 6
  },
  "nilrys_codex": {
   "letters": "NC",
   "palette": 4
  },
  "warped_tongs": {
   "letters": "WT",
   "palette": 4
  },
  "mummified_hand": {
   "letters": "MH",
   "palette": 2
  },
  "neows_lament": {
   "letters": "NL",
   "palette": 5
  },
  "strange_spoon": {
   "letters": "SS",
   "palette": 3
  },
  "wing_boots": {
   "letters": "WB",
   "palette": 6
  },
  "gambling_chip": {
   "letters": "GC",
   "palette": 7
  },
  "toolbox": {
   "letters": "TO",
   "palette": 2
  },
  "frozen_eye": {
   "letters": "FE",
   "palette": 7
  }
 },
 "potions": {
  "fire_potion": {
   "letters": "FP",
   "palette": 0
  },
  "block_potion": {
   "letters": "BP",
   "palette": 1
  },
  "energy_potion": {
   "letters": "EP",
   "palette": 4
  },
  "blood_potion": {
   "letters": "BP",
   "palette": 7
  },
  "swift_potion": {
   "letters": "SP",
   "palette": 2
  },
  "explosive_potion": {
   "letters": "EP",
   "palette": 6
  },
  "strength_potion": {
   "letters": "SP",
   "palette": 2
  },
  "regen_potion": {
   "letters": "RP",
   "palette": 0
  },
  "weak_potion": {
   "letters": "WP",
   "palette": 5
  },
  "fear_potion": {
   "letters": "FP",
   "palette": 7
  },
  "fruit_juice": {
   "letters": "FJ",
   "palette": 2
  },
  "ancient_potion": {
   "letters": "AP",
   "palette": 7
  },
  "dexterity_potion": {
   "letters": "DP",
   "palette": 7
  },
  "essence_of_steel": {
   "letters": "EO",
   "palette": 7
  },
  "liquid_bronze": {
   "letters": "LB",
   "palette": 2
  },
  "heart_of_iron": {
   "letters": "HO",
   "palette": 0
  },
  "cultist_potion": {
   "letters": "CP",
   "palette": 3
  },
  "flex_potion": {
   "letters": "FP",
   "palette": 0
  },
  "speed_potion": {
   "letters": "SP",
   "palette": 2
  },
  "entropic_brew": {
   "letters": "EB",
   "palette": 0
  },
  "elixir": {
   "letters": "EL",
   "palette": 2
  },
  "gamblers_brew": {
   "letters": "GB",
   "palette": 7
  },
  "liquid_memories": {
   "letters": "LM",
   "palette": 5
  },
  "attack_potion": {
   "letters": "AP",
   "palette": 1
  },
  "skill_potion": {
   "letters": "SP",
   "palette": 4
  },
  "power_potion": {
   "letters": "PP",
   "palette": 4
  },
  "blessing_of_the_forge": {
   "letters": "BO",
   "palette": 4
  },
  "snecko_oil": {
   "letters": "SO",
   "palette": 5
  },
  "smoke_bomb": {
   "letters": "SB",
   "palette": 3
  },
  "fairy_in_a_bottle": {
   "letters": "FI",
   "palette": 5
  },
  "duplication_potion": {
   "letters": "DP",
   "palette": 3
  },
  "distilled_chaos": {
   "letters": "DC",
   "palette": 2
  },
  "colorless_potion": {
   "letters": "CP",
   "palette": 5
  }
 },
 "statuses": {
  "standard.hex": {
   "letters": "SH",
   "palette": 7
  },
  "standard.strength": {
   "letters": "SS",
   "palette": 0
  },
  "standard.vulnerable": {
   "letters": "SV",
   "palette": 6
  },
  "standard.weak": {
   "letters": "SW",
   "palette": 4
  },
  "standard.frail": {
   "letters": "SF",
   "palette": 3
  },
  "ritual": {
   "letters": "RI",
   "palette": 6
  },
  "standard.metallicize": {
   "letters": "SM",
   "palette": 7
  },
  "standard.thorns": {
   "letters": "ST",
   "palette": 0
  },
  "standard.spore_cloud": {
   "letters": "SS",
   "palette": 5
  },
  "standard.artifact": {
   "letters": "SA",
   "palette": 4
  },
  "standard.enrage": {
   "letters": "SE",
   "palette": 4
  },
  "standard.regen": {
   "letters": "SR",
   "palette": 7
  },
  "standard.rage": {
   "letters": "SR",
   "palette": 7
  },
  "standard.flame_barrier": {
   "letters": "SF",
   "palette": 1
  },
  "standard.combust": {
   "letters": "SC",
   "palette": 1
  },
  "standard.split": {
   "letters": "SS",
   "palette": 6
  },
  "standard.time_warp": {
   "letters": "ST",
   "palette": 6
  },
  "standard.constricted": {
   "letters": "SC",
   "palette": 2
  },
  "standard.intangible": {
   "letters": "SI",
   "palette": 1
  },
  "standard.buffer": {
   "letters": "SB",
   "palette": 0
  },
  "standard.plated_armor": {
   "letters": "SP",
   "palette": 2
  },
  "standard.dexterity": {
   "letters": "SD",
   "palette": 1
  },
  "standard.lose_strength": {
   "letters": "SL",
   "palette": 1
  },
  "standard.lose_dexterity": {
   "letters": "SL",
   "palette": 0
  },
  "standard.regain_strength": {
   "letters": "SR",
   "palette": 4
  },
  "standard.phantom_veil": {
   "letters": "SP",
   "palette": 0
  },
  "standard.fairy_in_a_bottle": {
   "letters": "SF",
   "palette": 4
  },
  "standard.duplication": {
   "letters": "SD",
   "palette": 6
  },
  "standard.sharp_hide": {
   "letters": "SS",
   "palette": 3
  },
  "standard.curiosity": {
   "letters": "SC",
   "palette": 7
  },
  "standard.mode_shift": {
   "letters": "SM",
   "palette": 6
  },
  "standard.unawakened": {
   "letters": "SU",
   "palette": 7
  },
  "standard.stasis": {
   "letters": "SS",
   "palette": 1
  },
  "standard.stasis_ready": {
   "letters": "SS",
   "palette": 1
  },
  "standard.draw_reduction": {
   "letters": "SD",
   "palette": 2
  },
  "standard.entangled": {
   "letters": "SE",
   "palette": 2
  },
  "standard.entangle_ready": {
   "letters": "SE",
   "palette": 6
  },
  "standard.barricade": {
   "letters": "SB",
   "palette": 1
  },
  "standard.blur": {
   "letters": "SB",
   "palette": 7
  },
  "standard.slow": {
   "letters": "SS",
   "palette": 7
  },
  "standard.berserk": {
   "letters": "SB",
   "palette": 4
  },
  "standard.flying": {
   "letters": "SF",
   "palette": 1
  },
  "standard.curl_up": {
   "letters": "SC",
   "palette": 0
  },
  "standard.nightmare_pending": {
   "letters": "SN",
   "palette": 3
  },
  "standard.no_draw": {
   "letters": "SN",
   "palette": 0
  },
  "standard.demon_form": {
   "letters": "SD",
   "palette": 0
  },
  "standard.brutality": {
   "letters": "SB",
   "palette": 6
  },
  "standard.rupture": {
   "letters": "SR",
   "palette": 3
  },
  "standard.juggernaut": {
   "letters": "SJ",
   "palette": 6
  },
  "standard.evolve": {
   "letters": "SE",
   "palette": 7
  },
  "standard.fire_breathing": {
   "letters": "SF",
   "palette": 7
  },
  "standard.dark_embrace": {
   "letters": "SD",
   "palette": 4
  },
  "standard.feel_no_pain": {
   "letters": "SF",
   "palette": 5
  },
  "standard.double_tap": {
   "letters": "SD",
   "palette": 1
  },
  "standard.corruption": {
   "letters": "SC",
   "palette": 3
  },
  "standard.mayhem": {
   "letters": "SM",
   "palette": 3
  },
  "standard.magnetism": {
   "letters": "SM",
   "palette": 7
  },
  "standard.no_block_from_cards": {
   "letters": "SN",
   "palette": 0
  },
  "standard.cap_cost_at": {
   "letters": "SC",
   "palette": 2
  },
  "standard.omega": {
   "letters": "SO",
   "palette": 5
  },
  "standard.panache": {
   "letters": "SP",
   "palette": 6
  },
  "standard.sadistic_nature": {
   "letters": "SS",
   "palette": 4
  },
  "standard.the_bomb": {
   "letters": "ST",
   "palette": 2
  },
  "standard.the_bomb_damage": {
   "letters": "ST",
   "palette": 6
  },
  "standard.painful_stabs": {
   "letters": "SP",
   "palette": 7
  },
  "standard.lagavulin_asleep": {
   "letters": "SL",
   "palette": 6
  },
  "standard.orichalcum": {
   "letters": "SO",
   "palette": 3
  },
  "standard.cloak_clasp": {
   "letters": "SC",
   "palette": 4
  },
  "standard.stone_calendar": {
   "letters": "SS",
   "palette": 2
  },
  "standard.mercury_hourglass": {
   "letters": "SM",
   "palette": 6
  },
  "standard.horn_cleat": {
   "letters": "SH",
   "palette": 7
  },
  "standard.captains_wheel": {
   "letters": "SC",
   "palette": 7
  },
  "standard.incense_burner": {
   "letters": "SI",
   "palette": 4
  },
  "standard.pocketwatch": {
   "letters": "SP",
   "palette": 7
  },
  "standard.lantern": {
   "letters": "SL",
   "palette": 6
  },
  "standard.bag_of_preparation": {
   "letters": "SB",
   "palette": 2
  },
  "standard.ice_cream": {
   "letters": "SI",
   "palette": 0
  },
  "standard.calipers": {
   "letters": "SC",
   "palette": 1
  },
  "standard.double_damage": {
   "letters": "SD",
   "palette": 5
  },
  "standard.kunai": {
   "letters": "SK",
   "palette": 6
  },
  "standard.shuriken": {
   "letters": "SS",
   "palette": 1
  },
  "standard.ornamental_fan": {
   "letters": "SO",
   "palette": 5
  },
  "standard.letter_opener": {
   "letters": "SL",
   "palette": 0
  },
  "standard.nunchaku": {
   "letters": "SN",
   "palette": 7
  },
  "standard.ink_bottle": {
   "letters": "SI",
   "palette": 7
  },
  "standard.pen_nib": {
   "letters": "SP",
   "palette": 7
  },
  "standard.gremlin_horn": {
   "letters": "SG",
   "palette": 0
  },
  "standard.the_specimen": {
   "letters": "ST",
   "palette": 0
  },
  "standard.the_boot": {
   "letters": "ST",
   "palette": 2
  },
  "standard.torii": {
   "letters": "ST",
   "palette": 5
  },
  "standard.tungsten_rod": {
   "letters": "ST",
   "palette": 0
  },
  "standard.poison": {
   "letters": "SP",
   "palette": 6
  },
  "standard.paper_phrog": {
   "letters": "SP",
   "palette": 3
  },
  "standard.paper_krane": {
   "letters": "SP",
   "palette": 6
  },
  "standard.champion_belt": {
   "letters": "SC",
   "palette": 7
  },
  "standard.snecko_skull": {
   "letters": "SS",
   "palette": 3
  },
  "standard.ginger": {
   "letters": "SG",
   "palette": 6
  },
  "standard.turnip": {
   "letters": "ST",
   "palette": 4
  },
  "standard.red_skull": {
   "letters": "SR",
   "palette": 3
  },
  "standard.odd_mushroom": {
   "letters": "SO",
   "palette": 6
  },
  "standard.ring_of_the_snake": {
   "letters": "SR",
   "palette": 3
  },
  "standard.ring_of_the_serpent": {
   "letters": "SR",
   "palette": 4
  },
  "standard.philosophers_stone": {
   "letters": "SP",
   "palette": 0
  },
  "standard.happy_flower": {
   "letters": "SH",
   "palette": 6
  },
  "standard.art_of_war": {
   "letters": "SA",
   "palette": 4
  },
  "standard.brimstone": {
   "letters": "SB",
   "palette": 1
  },
  "standard.mark_of_pain": {
   "letters": "SM",
   "palette": 6
  },
  "standard.mutagenic_strength": {
   "letters": "SM",
   "palette": 5
  },
  "standard.centennial_puzzle": {
   "letters": "SC",
   "palette": 0
  },
  "standard.runic_cube": {
   "letters": "SR",
   "palette": 1
  },
  "standard.charons_ashes": {
   "letters": "SC",
   "palette": 7
  },
  "standard.duality": {
   "letters": "SD",
   "palette": 0
  },
  "standard.akabeko": {
   "letters": "SA",
   "palette": 6
  },
  "standard.self_forming_clay": {
   "letters": "SS",
   "palette": 7
  },
  "standard.bird_faced_urn": {
   "letters": "SB",
   "palette": 5
  },
  "standard.runic_pyramid": {
   "letters": "SR",
   "palette": 0
  },
  "standard.lizard_tail": {
   "letters": "SL",
   "palette": 5
  },
  "standard.unceasing_top": {
   "letters": "SU",
   "palette": 7
  },
  "standard.slavers_collar": {
   "letters": "SS",
   "palette": 6
  },
  "standard.busted_crown": {
   "letters": "SB",
   "palette": 1
  },
  "standard.ectoplasm": {
   "letters": "SE",
   "palette": 2
  },
  "standard.ancient_tea_set": {
   "letters": "SA",
   "palette": 0
  },
  "standard.sozu": {
   "letters": "SS",
   "palette": 1
  },
  "standard.split_spike_l": {
   "letters": "SS",
   "palette": 4
  },
  "standard.split_acid_l": {
   "letters": "SS",
   "palette": 1
  },
  "standard.confusion": {
   "letters": "SC",
   "palette": 6
  },
  "standard.snecko_eye": {
   "letters": "SS",
   "palette": 7
  },
  "standard.cursed_key": {
   "letters": "SC",
   "palette": 0
  },
  "standard.the_abacus": {
   "letters": "ST",
   "palette": 1
  },
  "standard.sundial": {
   "letters": "SS",
   "palette": 2
  },
  "standard.hand_drill": {
   "letters": "SH",
   "palette": 5
  },
  "standard.chemical_x": {
   "letters": "SC",
   "palette": 1
  },
  "standard.strike_dummy": {
   "letters": "SS",
   "palette": 7
  },
  "standard.velvet_choker": {
   "letters": "SV",
   "palette": 3
  },
  "standard.runic_dome": {
   "letters": "SR",
   "palette": 7
  },
  "standard.magic_flower": {
   "letters": "SM",
   "palette": 5
  },
  "standard.medical_kit": {
   "letters": "SM",
   "palette": 2
  },
  "standard.blue_candle": {
   "letters": "SB",
   "palette": 6
  },
  "standard.enchiridion": {
   "letters": "SE",
   "palette": 6
  },
  "standard.orange_pellets": {
   "letters": "SO",
   "palette": 4
  },
  "standard.dead_branch": {
   "letters": "SD",
   "palette": 1
  },
  "standard.nilrys_codex": {
   "letters": "SN",
   "palette": 1
  },
  "standard.warped_tongs": {
   "letters": "SW",
   "palette": 1
  },
  "standard.mummified_hand": {
   "letters": "SM",
   "palette": 3
  },
  "standard.strange_spoon": {
   "letters": "SS",
   "palette": 0
  },
  "standard.malleable": {
   "letters": "SM",
   "palette": 3
  },
  "standard.fading": {
   "letters": "SF",
   "palette": 3
  },
  "standard.energized": {
   "letters": "SE",
   "palette": 5
  },
  "standard.draw_card_next_turn": {
   "letters": "SD",
   "palette": 1
  }
 }
};
