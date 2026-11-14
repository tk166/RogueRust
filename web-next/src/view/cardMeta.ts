// 生成物：`python native/build_zh_i18n.py` 重建，**不要手改**。
//
// 「种类」「要不要玩家选目标」「费用」「稀有度」都来自内容包
// （`Cards[].Tags` + `Costs[]` + `Rarity` + 程序里的 `sel.eventTarget`）。
// ⚠️ **不从动作表的 targetSlot 反推**：内核故意为"每张可出的牌 × 每个活敌人"各发一条
// 动作（它无法廉价判断定向性），那是**枚举策略**，不是卡牌语义（第十四轮 Review P1-A）。

export interface CardMeta {
  readonly kind: "attack" | "skill" | "power" | "status" | "curse";
  readonly targeting: "none" | "singleEnemy";
  /** 能量费；`"X"` = X 费牌，`"-"` = 不可打出（诅咒/状态）。 */
  readonly cost: number | "X" | "-";
  /** 内容包的 `Rarity`（`Common` / `Uncommon` / `Rare` / …）。 */
  readonly rarity: string;
}

const cardMeta: Record<string, CardMeta> = {
 "strike": {
  "kind": "attack",
  "targeting": "singleEnemy",
  "cost": 1,
  "rarity": "Basic"
 },
 "defend": {
  "kind": "skill",
  "targeting": "none",
  "cost": 1,
  "rarity": "Basic"
 },
 "bash": {
  "kind": "attack",
  "targeting": "singleEnemy",
  "cost": 2,
  "rarity": "Basic"
 },
 "slimed": {
  "kind": "status",
  "targeting": "none",
  "cost": 1,
  "rarity": "Status"
 },
 "strike+": {
  "kind": "attack",
  "targeting": "singleEnemy",
  "cost": 1,
  "rarity": "Basic"
 },
 "defend+": {
  "kind": "skill",
  "targeting": "none",
  "cost": 1,
  "rarity": "Basic"
 },
 "bash+": {
  "kind": "attack",
  "targeting": "singleEnemy",
  "cost": 2,
  "rarity": "Basic"
 },
 "twin_strike": {
  "kind": "attack",
  "targeting": "singleEnemy",
  "cost": 1,
  "rarity": "Common"
 },
 "iron_wave": {
  "kind": "attack",
  "targeting": "singleEnemy",
  "cost": 1,
  "rarity": "Common"
 },
 "clothesline": {
  "kind": "attack",
  "targeting": "singleEnemy",
  "cost": 2,
  "rarity": "Common"
 },
 "anger": {
  "kind": "attack",
  "targeting": "singleEnemy",
  "cost": 0,
  "rarity": "Common"
 },
 "uppercut": {
  "kind": "attack",
  "targeting": "singleEnemy",
  "cost": 2,
  "rarity": "Uncommon"
 },
 "injury": {
  "kind": "curse",
  "targeting": "none",
  "cost": "-",
  "rarity": "Curse"
 },
 "sentinel": {
  "kind": "skill",
  "targeting": "none",
  "cost": 1,
  "rarity": "Uncommon"
 },
 "patient_guard": {
  "kind": "skill",
  "targeting": "none",
  "cost": 1,
  "rarity": "Common"
 },
 "swift_strike": {
  "kind": "attack",
  "targeting": "singleEnemy",
  "cost": 1,
  "rarity": "Common"
 },
 "whirlwind": {
  "kind": "attack",
  "targeting": "none",
  "cost": "X",
  "rarity": "Uncommon"
 },
 "whirlwind+": {
  "kind": "attack",
  "targeting": "none",
  "cost": "X",
  "rarity": "Uncommon"
 },
 "apparition": {
  "kind": "skill",
  "targeting": "none",
  "cost": 1,
  "rarity": "Special"
 },
 "buffer": {
  "kind": "power",
  "targeting": "none",
  "cost": 2,
  "rarity": "Rare"
 },
 "anger+": {
  "kind": "attack",
  "targeting": "singleEnemy",
  "cost": 0,
  "rarity": "Common"
 },
 "twin_strike+": {
  "kind": "attack",
  "targeting": "singleEnemy",
  "cost": 1,
  "rarity": "Common"
 },
 "iron_wave+": {
  "kind": "attack",
  "targeting": "singleEnemy",
  "cost": 1,
  "rarity": "Common"
 },
 "clothesline+": {
  "kind": "attack",
  "targeting": "singleEnemy",
  "cost": 2,
  "rarity": "Common"
 },
 "uppercut+": {
  "kind": "attack",
  "targeting": "singleEnemy",
  "cost": 2,
  "rarity": "Uncommon"
 },
 "sentinel+": {
  "kind": "skill",
  "targeting": "none",
  "cost": 1,
  "rarity": "Uncommon"
 },
 "patient_guard+": {
  "kind": "skill",
  "targeting": "none",
  "cost": 1,
  "rarity": "Common"
 },
 "swift_strike+": {
  "kind": "attack",
  "targeting": "singleEnemy",
  "cost": 1,
  "rarity": "Common"
 },
 "apparition+": {
  "kind": "skill",
  "targeting": "none",
  "cost": 1,
  "rarity": "Special"
 },
 "buffer+": {
  "kind": "power",
  "targeting": "none",
  "cost": 2,
  "rarity": "Rare"
 },
 "inflame": {
  "kind": "power",
  "targeting": "none",
  "cost": 1,
  "rarity": "Uncommon"
 },
 "inflame+": {
  "kind": "power",
  "targeting": "none",
  "cost": 1,
  "rarity": "Uncommon"
 },
 "metallicize": {
  "kind": "power",
  "targeting": "none",
  "cost": 1,
  "rarity": "Uncommon"
 },
 "metallicize+": {
  "kind": "power",
  "targeting": "none",
  "cost": 1,
  "rarity": "Uncommon"
 },
 "combust": {
  "kind": "power",
  "targeting": "none",
  "cost": 1,
  "rarity": "Uncommon"
 },
 "combust+": {
  "kind": "power",
  "targeting": "none",
  "cost": 1,
  "rarity": "Uncommon"
 },
 "wound": {
  "kind": "status",
  "targeting": "none",
  "cost": "-",
  "rarity": "Status"
 },
 "burn": {
  "kind": "status",
  "targeting": "none",
  "cost": "-",
  "rarity": "Status"
 },
 "bandage_up": {
  "kind": "skill",
  "targeting": "none",
  "cost": 0,
  "rarity": "Uncommon"
 },
 "blind": {
  "kind": "skill",
  "targeting": "none",
  "cost": 0,
  "rarity": "Uncommon"
 },
 "dark_shackles": {
  "kind": "skill",
  "targeting": "singleEnemy",
  "cost": 0,
  "rarity": "Uncommon"
 },
 "ascenders_bane": {
  "kind": "curse",
  "targeting": "none",
  "cost": "-",
  "rarity": "Curse"
 },
 "dazed": {
  "kind": "status",
  "targeting": "none",
  "cost": "-",
  "rarity": "Status"
 },
 "burn+": {
  "kind": "status",
  "targeting": "none",
  "cost": "-",
  "rarity": "Status"
 },
 "void": {
  "kind": "status",
  "targeting": "none",
  "cost": "-",
  "rarity": "Status"
 },
 "barricade": {
  "kind": "power",
  "targeting": "none",
  "cost": 3,
  "rarity": "Rare"
 },
 "blur": {
  "kind": "skill",
  "targeting": "none",
  "cost": 1,
  "rarity": "Uncommon"
 },
 "barricade+": {
  "kind": "power",
  "targeting": "none",
  "cost": 2,
  "rarity": "Rare"
 },
 "blur+": {
  "kind": "skill",
  "targeting": "none",
  "cost": 0,
  "rarity": "Uncommon"
 },
 "berserk": {
  "kind": "power",
  "targeting": "none",
  "cost": 0,
  "rarity": "Rare"
 },
 "berserk+": {
  "kind": "power",
  "targeting": "none",
  "cost": 0,
  "rarity": "Rare"
 },
 "cleave": {
  "kind": "attack",
  "targeting": "none",
  "cost": 1,
  "rarity": "Common"
 },
 "cleave+": {
  "kind": "attack",
  "targeting": "none",
  "cost": 1,
  "rarity": "Common"
 },
 "pommel_strike": {
  "kind": "attack",
  "targeting": "singleEnemy",
  "cost": 1,
  "rarity": "Common"
 },
 "pommel_strike+": {
  "kind": "attack",
  "targeting": "singleEnemy",
  "cost": 1,
  "rarity": "Common"
 },
 "shrug_it_off": {
  "kind": "skill",
  "targeting": "none",
  "cost": 1,
  "rarity": "Common"
 },
 "shrug_it_off+": {
  "kind": "skill",
  "targeting": "none",
  "cost": 1,
  "rarity": "Common"
 },
 "thunderclap": {
  "kind": "attack",
  "targeting": "none",
  "cost": 1,
  "rarity": "Common"
 },
 "thunderclap+": {
  "kind": "attack",
  "targeting": "none",
  "cost": 1,
  "rarity": "Common"
 },
 "bludgeon": {
  "kind": "attack",
  "targeting": "singleEnemy",
  "cost": 3,
  "rarity": "Rare"
 },
 "bludgeon+": {
  "kind": "attack",
  "targeting": "singleEnemy",
  "cost": 3,
  "rarity": "Rare"
 },
 "impervious": {
  "kind": "skill",
  "targeting": "none",
  "cost": 2,
  "rarity": "Rare"
 },
 "impervious+": {
  "kind": "skill",
  "targeting": "none",
  "cost": 2,
  "rarity": "Rare"
 },
 "pummel": {
  "kind": "attack",
  "targeting": "singleEnemy",
  "cost": 1,
  "rarity": "Uncommon"
 },
 "pummel+": {
  "kind": "attack",
  "targeting": "singleEnemy",
  "cost": 1,
  "rarity": "Uncommon"
 },
 "wild_strike": {
  "kind": "attack",
  "targeting": "singleEnemy",
  "cost": 1,
  "rarity": "Common"
 },
 "wild_strike+": {
  "kind": "attack",
  "targeting": "singleEnemy",
  "cost": 1,
  "rarity": "Common"
 },
 "ghostly_armor": {
  "kind": "skill",
  "targeting": "none",
  "cost": 1,
  "rarity": "Uncommon"
 },
 "ghostly_armor+": {
  "kind": "skill",
  "targeting": "none",
  "cost": 1,
  "rarity": "Uncommon"
 },
 "battle_trance": {
  "kind": "skill",
  "targeting": "none",
  "cost": 0,
  "rarity": "Uncommon"
 },
 "battle_trance+": {
  "kind": "skill",
  "targeting": "none",
  "cost": 0,
  "rarity": "Uncommon"
 },
 "doubt": {
  "kind": "curse",
  "targeting": "none",
  "cost": "-",
  "rarity": "Curse"
 },
 "writhe": {
  "kind": "curse",
  "targeting": "none",
  "cost": "-",
  "rarity": "Curse"
 },
 "second_wind": {
  "kind": "skill",
  "targeting": "none",
  "cost": 1,
  "rarity": "Uncommon"
 },
 "second_wind+": {
  "kind": "skill",
  "targeting": "none",
  "cost": 1,
  "rarity": "Uncommon"
 },
 "fiend_fire": {
  "kind": "attack",
  "targeting": "singleEnemy",
  "cost": 2,
  "rarity": "Rare"
 },
 "fiend_fire+": {
  "kind": "attack",
  "targeting": "singleEnemy",
  "cost": 2,
  "rarity": "Rare"
 },
 "dual_wield": {
  "kind": "skill",
  "targeting": "none",
  "cost": 1,
  "rarity": "Uncommon"
 },
 "dual_wield+": {
  "kind": "skill",
  "targeting": "none",
  "cost": 1,
  "rarity": "Uncommon"
 },
 "armaments": {
  "kind": "skill",
  "targeting": "none",
  "cost": 1,
  "rarity": "Common"
 },
 "armaments+": {
  "kind": "skill",
  "targeting": "none",
  "cost": 1,
  "rarity": "Common"
 },
 "warcry": {
  "kind": "skill",
  "targeting": "none",
  "cost": 0,
  "rarity": "Common"
 },
 "warcry+": {
  "kind": "skill",
  "targeting": "none",
  "cost": 0,
  "rarity": "Common"
 },
 "nightmare": {
  "kind": "skill",
  "targeting": "none",
  "cost": 3,
  "rarity": "Rare"
 },
 "nightmare+": {
  "kind": "skill",
  "targeting": "none",
  "cost": 2,
  "rarity": "Rare"
 },
 "sword_boomerang": {
  "kind": "attack",
  "targeting": "none",
  "cost": 1,
  "rarity": "Common"
 },
 "sword_boomerang+": {
  "kind": "attack",
  "targeting": "none",
  "cost": 1,
  "rarity": "Common"
 },
 "body_slam": {
  "kind": "attack",
  "targeting": "singleEnemy",
  "cost": 1,
  "rarity": "Common"
 },
 "body_slam+": {
  "kind": "attack",
  "targeting": "singleEnemy",
  "cost": 0,
  "rarity": "Common"
 },
 "rip_and_tear": {
  "kind": "attack",
  "targeting": "none",
  "cost": 1,
  "rarity": "Uncommon"
 },
 "rip_and_tear+": {
  "kind": "attack",
  "targeting": "none",
  "cost": 1,
  "rarity": "Uncommon"
 },
 "rampage": {
  "kind": "attack",
  "targeting": "singleEnemy",
  "cost": 1,
  "rarity": "Uncommon"
 },
 "rampage+": {
  "kind": "attack",
  "targeting": "singleEnemy",
  "cost": 1,
  "rarity": "Uncommon"
 },
 "searing_blow": {
  "kind": "attack",
  "targeting": "singleEnemy",
  "cost": 2,
  "rarity": "Uncommon"
 },
 "searing_blow+": {
  "kind": "attack",
  "targeting": "singleEnemy",
  "cost": 2,
  "rarity": "Uncommon"
 },
 "searing_blow++": {
  "kind": "attack",
  "targeting": "singleEnemy",
  "cost": 2,
  "rarity": "Uncommon"
 },
 "searing_blow+++": {
  "kind": "attack",
  "targeting": "singleEnemy",
  "cost": 2,
  "rarity": "Uncommon"
 },
 "searing_blow++++": {
  "kind": "attack",
  "targeting": "singleEnemy",
  "cost": 2,
  "rarity": "Uncommon"
 },
 "searing_blow+++++": {
  "kind": "attack",
  "targeting": "singleEnemy",
  "cost": 2,
  "rarity": "Uncommon"
 },
 "searing_blow++++++": {
  "kind": "attack",
  "targeting": "singleEnemy",
  "cost": 2,
  "rarity": "Uncommon"
 },
 "searing_blow+++++++": {
  "kind": "attack",
  "targeting": "singleEnemy",
  "cost": 2,
  "rarity": "Uncommon"
 },
 "flex": {
  "kind": "skill",
  "targeting": "none",
  "cost": 0,
  "rarity": "Common"
 },
 "flex+": {
  "kind": "skill",
  "targeting": "none",
  "cost": 0,
  "rarity": "Common"
 },
 "limit_break": {
  "kind": "skill",
  "targeting": "none",
  "cost": 1,
  "rarity": "Rare"
 },
 "limit_break+": {
  "kind": "skill",
  "targeting": "none",
  "cost": 1,
  "rarity": "Rare"
 },
 "perfected_strike": {
  "kind": "attack",
  "targeting": "singleEnemy",
  "cost": 2,
  "rarity": "Common"
 },
 "perfected_strike+": {
  "kind": "attack",
  "targeting": "singleEnemy",
  "cost": 2,
  "rarity": "Common"
 },
 "true_grit": {
  "kind": "skill",
  "targeting": "none",
  "cost": 1,
  "rarity": "Common"
 },
 "true_grit+": {
  "kind": "skill",
  "targeting": "none",
  "cost": 1,
  "rarity": "Common"
 },
 "reaper": {
  "kind": "attack",
  "targeting": "none",
  "cost": 2,
  "rarity": "Rare"
 },
 "reaper+": {
  "kind": "attack",
  "targeting": "none",
  "cost": 2,
  "rarity": "Rare"
 },
 "skewer": {
  "kind": "attack",
  "targeting": "singleEnemy",
  "cost": "X",
  "rarity": "Uncommon"
 },
 "skewer+": {
  "kind": "attack",
  "targeting": "singleEnemy",
  "cost": "X",
  "rarity": "Uncommon"
 },
 "malaise": {
  "kind": "skill",
  "targeting": "singleEnemy",
  "cost": "X",
  "rarity": "Rare"
 },
 "malaise+": {
  "kind": "skill",
  "targeting": "singleEnemy",
  "cost": "X",
  "rarity": "Rare"
 },
 "entrench": {
  "kind": "skill",
  "targeting": "none",
  "cost": 2,
  "rarity": "Uncommon"
 },
 "entrench+": {
  "kind": "skill",
  "targeting": "none",
  "cost": 1,
  "rarity": "Uncommon"
 },
 "carnage": {
  "kind": "attack",
  "targeting": "singleEnemy",
  "cost": 2,
  "rarity": "Uncommon"
 },
 "carnage+": {
  "kind": "attack",
  "targeting": "singleEnemy",
  "cost": 2,
  "rarity": "Uncommon"
 },
 "disarm": {
  "kind": "skill",
  "targeting": "singleEnemy",
  "cost": 1,
  "rarity": "Uncommon"
 },
 "disarm+": {
  "kind": "skill",
  "targeting": "singleEnemy",
  "cost": 1,
  "rarity": "Uncommon"
 },
 "immolate": {
  "kind": "attack",
  "targeting": "none",
  "cost": 2,
  "rarity": "Rare"
 },
 "immolate+": {
  "kind": "attack",
  "targeting": "none",
  "cost": 2,
  "rarity": "Rare"
 },
 "intimidate": {
  "kind": "skill",
  "targeting": "none",
  "cost": 0,
  "rarity": "Uncommon"
 },
 "intimidate+": {
  "kind": "skill",
  "targeting": "none",
  "cost": 0,
  "rarity": "Uncommon"
 },
 "shockwave": {
  "kind": "skill",
  "targeting": "none",
  "cost": 2,
  "rarity": "Uncommon"
 },
 "shockwave+": {
  "kind": "skill",
  "targeting": "none",
  "cost": 2,
  "rarity": "Uncommon"
 },
 "seeing_red": {
  "kind": "skill",
  "targeting": "none",
  "cost": 1,
  "rarity": "Uncommon"
 },
 "seeing_red+": {
  "kind": "skill",
  "targeting": "none",
  "cost": 0,
  "rarity": "Uncommon"
 },
 "flame_barrier": {
  "kind": "skill",
  "targeting": "none",
  "cost": 2,
  "rarity": "Uncommon"
 },
 "flame_barrier+": {
  "kind": "skill",
  "targeting": "none",
  "cost": 2,
  "rarity": "Uncommon"
 },
 "rage": {
  "kind": "skill",
  "targeting": "none",
  "cost": 0,
  "rarity": "Uncommon"
 },
 "rage+": {
  "kind": "skill",
  "targeting": "none",
  "cost": 0,
  "rarity": "Uncommon"
 },
 "power_through": {
  "kind": "skill",
  "targeting": "none",
  "cost": 1,
  "rarity": "Uncommon"
 },
 "power_through+": {
  "kind": "skill",
  "targeting": "none",
  "cost": 1,
  "rarity": "Uncommon"
 },
 "reckless_charge": {
  "kind": "attack",
  "targeting": "singleEnemy",
  "cost": 0,
  "rarity": "Uncommon"
 },
 "reckless_charge+": {
  "kind": "attack",
  "targeting": "singleEnemy",
  "cost": 0,
  "rarity": "Uncommon"
 },
 "sever_soul": {
  "kind": "attack",
  "targeting": "singleEnemy",
  "cost": 2,
  "rarity": "Uncommon"
 },
 "sever_soul+": {
  "kind": "attack",
  "targeting": "singleEnemy",
  "cost": 2,
  "rarity": "Uncommon"
 },
 "dropkick": {
  "kind": "attack",
  "targeting": "singleEnemy",
  "cost": 1,
  "rarity": "Uncommon"
 },
 "dropkick+": {
  "kind": "attack",
  "targeting": "singleEnemy",
  "cost": 1,
  "rarity": "Uncommon"
 },
 "headbutt": {
  "kind": "attack",
  "targeting": "singleEnemy",
  "cost": 1,
  "rarity": "Common"
 },
 "headbutt+": {
  "kind": "attack",
  "targeting": "singleEnemy",
  "cost": 1,
  "rarity": "Common"
 },
 "demon_form": {
  "kind": "power",
  "targeting": "none",
  "cost": 3,
  "rarity": "Rare"
 },
 "demon_form+": {
  "kind": "power",
  "targeting": "none",
  "cost": 3,
  "rarity": "Rare"
 },
 "bloodletting": {
  "kind": "skill",
  "targeting": "none",
  "cost": 0,
  "rarity": "Uncommon"
 },
 "bloodletting+": {
  "kind": "skill",
  "targeting": "none",
  "cost": 0,
  "rarity": "Uncommon"
 },
 "hemokinesis": {
  "kind": "attack",
  "targeting": "singleEnemy",
  "cost": 1,
  "rarity": "Uncommon"
 },
 "hemokinesis+": {
  "kind": "attack",
  "targeting": "singleEnemy",
  "cost": 1,
  "rarity": "Uncommon"
 },
 "offering": {
  "kind": "skill",
  "targeting": "none",
  "cost": 0,
  "rarity": "Rare"
 },
 "offering+": {
  "kind": "skill",
  "targeting": "none",
  "cost": 0,
  "rarity": "Rare"
 },
 "brutality": {
  "kind": "power",
  "targeting": "none",
  "cost": 0,
  "rarity": "Rare"
 },
 "brutality+": {
  "kind": "power",
  "targeting": "none",
  "cost": 0,
  "rarity": "Rare"
 },
 "rupture": {
  "kind": "power",
  "targeting": "none",
  "cost": 1,
  "rarity": "Uncommon"
 },
 "rupture+": {
  "kind": "power",
  "targeting": "none",
  "cost": 1,
  "rarity": "Uncommon"
 },
 "juggernaut": {
  "kind": "power",
  "targeting": "none",
  "cost": 2,
  "rarity": "Rare"
 },
 "juggernaut+": {
  "kind": "power",
  "targeting": "none",
  "cost": 2,
  "rarity": "Rare"
 },
 "evolve": {
  "kind": "power",
  "targeting": "none",
  "cost": 1,
  "rarity": "Uncommon"
 },
 "evolve+": {
  "kind": "power",
  "targeting": "none",
  "cost": 1,
  "rarity": "Uncommon"
 },
 "fire_breathing": {
  "kind": "power",
  "targeting": "none",
  "cost": 1,
  "rarity": "Uncommon"
 },
 "fire_breathing+": {
  "kind": "power",
  "targeting": "none",
  "cost": 1,
  "rarity": "Uncommon"
 },
 "dark_embrace": {
  "kind": "power",
  "targeting": "none",
  "cost": 2,
  "rarity": "Uncommon"
 },
 "dark_embrace+": {
  "kind": "power",
  "targeting": "none",
  "cost": 1,
  "rarity": "Uncommon"
 },
 "feel_no_pain": {
  "kind": "power",
  "targeting": "none",
  "cost": 1,
  "rarity": "Uncommon"
 },
 "feel_no_pain+": {
  "kind": "power",
  "targeting": "none",
  "cost": 1,
  "rarity": "Uncommon"
 },
 "heavy_blade": {
  "kind": "attack",
  "targeting": "singleEnemy",
  "cost": 2,
  "rarity": "Common"
 },
 "heavy_blade+": {
  "kind": "attack",
  "targeting": "singleEnemy",
  "cost": 2,
  "rarity": "Common"
 },
 "double_tap": {
  "kind": "skill",
  "targeting": "none",
  "cost": 1,
  "rarity": "Rare"
 },
 "double_tap+": {
  "kind": "skill",
  "targeting": "none",
  "cost": 1,
  "rarity": "Rare"
 },
 "exhume": {
  "kind": "skill",
  "targeting": "none",
  "cost": 1,
  "rarity": "Rare"
 },
 "exhume+": {
  "kind": "skill",
  "targeting": "none",
  "cost": 0,
  "rarity": "Rare"
 },
 "feed": {
  "kind": "attack",
  "targeting": "singleEnemy",
  "cost": 1,
  "rarity": "Rare"
 },
 "feed+": {
  "kind": "attack",
  "targeting": "singleEnemy",
  "cost": 1,
  "rarity": "Rare"
 },
 "clash": {
  "kind": "attack",
  "targeting": "singleEnemy",
  "cost": 0,
  "rarity": "Common"
 },
 "clash+": {
  "kind": "attack",
  "targeting": "singleEnemy",
  "cost": 0,
  "rarity": "Common"
 },
 "burning_pact": {
  "kind": "skill",
  "targeting": "none",
  "cost": 1,
  "rarity": "Uncommon"
 },
 "burning_pact+": {
  "kind": "skill",
  "targeting": "none",
  "cost": 1,
  "rarity": "Uncommon"
 },
 "infernal_blade": {
  "kind": "skill",
  "targeting": "none",
  "cost": 1,
  "rarity": "Uncommon"
 },
 "infernal_blade+": {
  "kind": "skill",
  "targeting": "none",
  "cost": 0,
  "rarity": "Uncommon"
 },
 "havoc": {
  "kind": "skill",
  "targeting": "none",
  "cost": 1,
  "rarity": "Common"
 },
 "havoc+": {
  "kind": "skill",
  "targeting": "none",
  "cost": 0,
  "rarity": "Common"
 },
 "spot_weakness": {
  "kind": "skill",
  "targeting": "singleEnemy",
  "cost": 1,
  "rarity": "Uncommon"
 },
 "spot_weakness+": {
  "kind": "skill",
  "targeting": "singleEnemy",
  "cost": 1,
  "rarity": "Uncommon"
 },
 "blood_for_blood": {
  "kind": "attack",
  "targeting": "singleEnemy",
  "cost": 4,
  "rarity": "Uncommon"
 },
 "blood_for_blood+": {
  "kind": "attack",
  "targeting": "singleEnemy",
  "cost": 3,
  "rarity": "Uncommon"
 },
 "corruption": {
  "kind": "power",
  "targeting": "none",
  "cost": 3,
  "rarity": "Rare"
 },
 "corruption+": {
  "kind": "power",
  "targeting": "none",
  "cost": 2,
  "rarity": "Rare"
 },
 "trip": {
  "kind": "skill",
  "targeting": "singleEnemy",
  "cost": 0,
  "rarity": "Uncommon"
 },
 "trip+": {
  "kind": "skill",
  "targeting": "none",
  "cost": 0,
  "rarity": "Uncommon"
 },
 "panacea": {
  "kind": "skill",
  "targeting": "none",
  "cost": 0,
  "rarity": "Uncommon"
 },
 "panacea+": {
  "kind": "skill",
  "targeting": "none",
  "cost": 0,
  "rarity": "Uncommon"
 },
 "finesse": {
  "kind": "skill",
  "targeting": "none",
  "cost": 0,
  "rarity": "Uncommon"
 },
 "finesse+": {
  "kind": "skill",
  "targeting": "none",
  "cost": 0,
  "rarity": "Uncommon"
 },
 "flash_of_steel": {
  "kind": "attack",
  "targeting": "singleEnemy",
  "cost": 0,
  "rarity": "Uncommon"
 },
 "flash_of_steel+": {
  "kind": "attack",
  "targeting": "singleEnemy",
  "cost": 0,
  "rarity": "Uncommon"
 },
 "good_instincts": {
  "kind": "skill",
  "targeting": "none",
  "cost": 0,
  "rarity": "Uncommon"
 },
 "good_instincts+": {
  "kind": "skill",
  "targeting": "none",
  "cost": 0,
  "rarity": "Uncommon"
 },
 "master_of_strategy": {
  "kind": "skill",
  "targeting": "none",
  "cost": 0,
  "rarity": "Rare"
 },
 "master_of_strategy+": {
  "kind": "skill",
  "targeting": "none",
  "cost": 0,
  "rarity": "Rare"
 },
 "dramatic_entrance": {
  "kind": "attack",
  "targeting": "none",
  "cost": 0,
  "rarity": "Uncommon"
 },
 "dramatic_entrance+": {
  "kind": "attack",
  "targeting": "none",
  "cost": 0,
  "rarity": "Uncommon"
 },
 "impatience": {
  "kind": "skill",
  "targeting": "none",
  "cost": 0,
  "rarity": "Uncommon"
 },
 "impatience+": {
  "kind": "skill",
  "targeting": "none",
  "cost": 0,
  "rarity": "Uncommon"
 },
 "deep_breath": {
  "kind": "skill",
  "targeting": "none",
  "cost": 0,
  "rarity": "Uncommon"
 },
 "deep_breath+": {
  "kind": "skill",
  "targeting": "none",
  "cost": 0,
  "rarity": "Uncommon"
 },
 "insight": {
  "kind": "skill",
  "targeting": "none",
  "cost": 0,
  "rarity": "Special"
 },
 "insight+": {
  "kind": "skill",
  "targeting": "none",
  "cost": 0,
  "rarity": "Special"
 },
 "miracle": {
  "kind": "skill",
  "targeting": "none",
  "cost": 0,
  "rarity": "Special"
 },
 "miracle+": {
  "kind": "skill",
  "targeting": "none",
  "cost": 0,
  "rarity": "Special"
 },
 "mayhem": {
  "kind": "power",
  "targeting": "none",
  "cost": 2,
  "rarity": "Rare"
 },
 "mayhem+": {
  "kind": "power",
  "targeting": "none",
  "cost": 1,
  "rarity": "Rare"
 },
 "magnetism": {
  "kind": "power",
  "targeting": "none",
  "cost": 2,
  "rarity": "Rare"
 },
 "magnetism+": {
  "kind": "power",
  "targeting": "none",
  "cost": 1,
  "rarity": "Rare"
 },
 "chrysalis": {
  "kind": "skill",
  "targeting": "none",
  "cost": 2,
  "rarity": "Rare"
 },
 "chrysalis+": {
  "kind": "skill",
  "targeting": "none",
  "cost": 2,
  "rarity": "Rare"
 },
 "metamorphosis": {
  "kind": "skill",
  "targeting": "none",
  "cost": 2,
  "rarity": "Rare"
 },
 "metamorphosis+": {
  "kind": "skill",
  "targeting": "none",
  "cost": 2,
  "rarity": "Rare"
 },
 "jack_of_all_trades": {
  "kind": "skill",
  "targeting": "none",
  "cost": 0,
  "rarity": "Uncommon"
 },
 "jack_of_all_trades+": {
  "kind": "skill",
  "targeting": "none",
  "cost": 0,
  "rarity": "Uncommon"
 },
 "transmutation": {
  "kind": "skill",
  "targeting": "none",
  "cost": "X",
  "rarity": "Rare"
 },
 "transmutation+": {
  "kind": "skill",
  "targeting": "none",
  "cost": "X",
  "rarity": "Rare"
 },
 "secret_technique": {
  "kind": "skill",
  "targeting": "none",
  "cost": 0,
  "rarity": "Rare"
 },
 "secret_technique+": {
  "kind": "skill",
  "targeting": "none",
  "cost": 0,
  "rarity": "Rare"
 },
 "secret_weapon": {
  "kind": "skill",
  "targeting": "none",
  "cost": 0,
  "rarity": "Rare"
 },
 "secret_weapon+": {
  "kind": "skill",
  "targeting": "none",
  "cost": 0,
  "rarity": "Rare"
 },
 "violence": {
  "kind": "skill",
  "targeting": "none",
  "cost": 0,
  "rarity": "Rare"
 },
 "violence+": {
  "kind": "skill",
  "targeting": "none",
  "cost": 0,
  "rarity": "Rare"
 },
 "purity": {
  "kind": "skill",
  "targeting": "none",
  "cost": 0,
  "rarity": "Uncommon"
 },
 "purity+": {
  "kind": "skill",
  "targeting": "none",
  "cost": 0,
  "rarity": "Uncommon"
 },
 "apotheosis": {
  "kind": "skill",
  "targeting": "none",
  "cost": 2,
  "rarity": "Rare"
 },
 "apotheosis+": {
  "kind": "skill",
  "targeting": "none",
  "cost": 1,
  "rarity": "Rare"
 },
 "panic_button": {
  "kind": "skill",
  "targeting": "none",
  "cost": 0,
  "rarity": "Uncommon"
 },
 "panic_button+": {
  "kind": "skill",
  "targeting": "none",
  "cost": 0,
  "rarity": "Uncommon"
 },
 "thinking_ahead": {
  "kind": "skill",
  "targeting": "none",
  "cost": 0,
  "rarity": "Rare"
 },
 "thinking_ahead+": {
  "kind": "skill",
  "targeting": "none",
  "cost": 0,
  "rarity": "Rare"
 },
 "mind_blast": {
  "kind": "attack",
  "targeting": "singleEnemy",
  "cost": 2,
  "rarity": "Uncommon"
 },
 "mind_blast+": {
  "kind": "attack",
  "targeting": "singleEnemy",
  "cost": 1,
  "rarity": "Uncommon"
 },
 "enlightenment": {
  "kind": "skill",
  "targeting": "none",
  "cost": 0,
  "rarity": "Uncommon"
 },
 "enlightenment+": {
  "kind": "skill",
  "targeting": "none",
  "cost": 0,
  "rarity": "Uncommon"
 },
 "madness": {
  "kind": "skill",
  "targeting": "none",
  "cost": 1,
  "rarity": "Uncommon"
 },
 "madness+": {
  "kind": "skill",
  "targeting": "none",
  "cost": 0,
  "rarity": "Uncommon"
 },
 "omega": {
  "kind": "power",
  "targeting": "none",
  "cost": 3,
  "rarity": "Special"
 },
 "omega+": {
  "kind": "power",
  "targeting": "none",
  "cost": 3,
  "rarity": "Special"
 },
 "panache": {
  "kind": "power",
  "targeting": "none",
  "cost": 0,
  "rarity": "Rare"
 },
 "panache+": {
  "kind": "power",
  "targeting": "none",
  "cost": 0,
  "rarity": "Rare"
 },
 "sadistic_nature": {
  "kind": "power",
  "targeting": "none",
  "cost": 0,
  "rarity": "Rare"
 },
 "sadistic_nature+": {
  "kind": "power",
  "targeting": "none",
  "cost": 0,
  "rarity": "Rare"
 },
 "the_bomb": {
  "kind": "skill",
  "targeting": "none",
  "cost": 2,
  "rarity": "Rare"
 },
 "the_bomb+": {
  "kind": "skill",
  "targeting": "none",
  "cost": 2,
  "rarity": "Rare"
 },
 "ritual_dagger": {
  "kind": "attack",
  "targeting": "singleEnemy",
  "cost": 1,
  "rarity": "Special"
 },
 "ritual_dagger+": {
  "kind": "attack",
  "targeting": "singleEnemy",
  "cost": 1,
  "rarity": "Special"
 },
 "hand_of_greed": {
  "kind": "attack",
  "targeting": "singleEnemy",
  "cost": 2,
  "rarity": "Rare"
 },
 "hand_of_greed+": {
  "kind": "attack",
  "targeting": "singleEnemy",
  "cost": 2,
  "rarity": "Rare"
 },
 "discovery": {
  "kind": "skill",
  "targeting": "none",
  "cost": 1,
  "rarity": "Uncommon"
 },
 "discovery+": {
  "kind": "skill",
  "targeting": "none",
  "cost": 1,
  "rarity": "Uncommon"
 },
 "forethought": {
  "kind": "skill",
  "targeting": "none",
  "cost": 0,
  "rarity": "Uncommon"
 },
 "forethought+": {
  "kind": "skill",
  "targeting": "none",
  "cost": 0,
  "rarity": "Uncommon"
 },
 "clumsy": {
  "kind": "curse",
  "targeting": "none",
  "cost": "-",
  "rarity": "Curse"
 },
 "curse_of_the_bell": {
  "kind": "curse",
  "targeting": "none",
  "cost": "-",
  "rarity": "Curse"
 },
 "decay": {
  "kind": "curse",
  "targeting": "none",
  "cost": "-",
  "rarity": "Curse"
 },
 "necronomicurse": {
  "kind": "curse",
  "targeting": "none",
  "cost": "-",
  "rarity": "Curse"
 },
 "normality": {
  "kind": "curse",
  "targeting": "none",
  "cost": "-",
  "rarity": "Curse"
 },
 "pain": {
  "kind": "curse",
  "targeting": "none",
  "cost": "-",
  "rarity": "Curse"
 },
 "parasite": {
  "kind": "curse",
  "targeting": "none",
  "cost": "-",
  "rarity": "Curse"
 },
 "pride": {
  "kind": "curse",
  "targeting": "none",
  "cost": 1,
  "rarity": "Curse"
 },
 "regret": {
  "kind": "curse",
  "targeting": "none",
  "cost": "-",
  "rarity": "Curse"
 },
 "shame": {
  "kind": "curse",
  "targeting": "none",
  "cost": "-",
  "rarity": "Curse"
 },
 "bite": {
  "kind": "attack",
  "targeting": "singleEnemy",
  "cost": 1,
  "rarity": "Special"
 },
 "bite+": {
  "kind": "attack",
  "targeting": "singleEnemy",
  "cost": 1,
  "rarity": "Special"
 },
 "expunger": {
  "kind": "attack",
  "targeting": "singleEnemy",
  "cost": 1,
  "rarity": "Special"
 },
 "expunger+": {
  "kind": "attack",
  "targeting": "singleEnemy",
  "cost": 1,
  "rarity": "Special"
 },
 "shiv": {
  "kind": "attack",
  "targeting": "singleEnemy",
  "cost": 0,
  "rarity": "Special"
 },
 "shiv+": {
  "kind": "attack",
  "targeting": "singleEnemy",
  "cost": 0,
  "rarity": "Special"
 },
 "smite": {
  "kind": "attack",
  "targeting": "singleEnemy",
  "cost": 1,
  "rarity": "Special"
 },
 "smite+": {
  "kind": "attack",
  "targeting": "singleEnemy",
  "cost": 1,
  "rarity": "Special"
 },
 "beta": {
  "kind": "skill",
  "targeting": "none",
  "cost": 2,
  "rarity": "Special"
 },
 "beta+": {
  "kind": "skill",
  "targeting": "none",
  "cost": 1,
  "rarity": "Special"
 },
 "through_violence": {
  "kind": "attack",
  "targeting": "singleEnemy",
  "cost": 0,
  "rarity": "Special"
 },
 "through_violence+": {
  "kind": "attack",
  "targeting": "singleEnemy",
  "cost": 0,
  "rarity": "Special"
 },
 "j.a.x.": {
  "kind": "skill",
  "targeting": "none",
  "cost": 0,
  "rarity": "Special"
 },
 "j.a.x.+": {
  "kind": "skill",
  "targeting": "none",
  "cost": 0,
  "rarity": "Special"
 },
 "safety": {
  "kind": "skill",
  "targeting": "none",
  "cost": 1,
  "rarity": "Special"
 },
 "safety+": {
  "kind": "skill",
  "targeting": "none",
  "cost": 1,
  "rarity": "Special"
 },
 "become_almighty": {
  "kind": "power",
  "targeting": "none",
  "cost": "-",
  "rarity": "Special"
 },
 "become_almighty+": {
  "kind": "power",
  "targeting": "none",
  "cost": "-",
  "rarity": "Special"
 },
 "live_forever": {
  "kind": "power",
  "targeting": "none",
  "cost": "-",
  "rarity": "Special"
 },
 "live_forever+": {
  "kind": "power",
  "targeting": "none",
  "cost": "-",
  "rarity": "Special"
 },
 "fame_and_fortune": {
  "kind": "skill",
  "targeting": "none",
  "cost": "-",
  "rarity": "Special"
 },
 "fame_and_fortune+": {
  "kind": "skill",
  "targeting": "none",
  "cost": "-",
  "rarity": "Special"
 },
 "wish": {
  "kind": "skill",
  "targeting": "none",
  "cost": 3,
  "rarity": "Rare"
 },
 "wish+": {
  "kind": "skill",
  "targeting": "none",
  "cost": 3,
  "rarity": "Rare"
 },
 "conjure_blade": {
  "kind": "skill",
  "targeting": "none",
  "cost": "X",
  "rarity": "Rare"
 },
 "conjure_blade+": {
  "kind": "skill",
  "targeting": "none",
  "cost": "X",
  "rarity": "Rare"
 },
 "jax": {
  "kind": "skill",
  "targeting": "none",
  "cost": 0,
  "rarity": "Special"
 },
 "jax+": {
  "kind": "skill",
  "targeting": "none",
  "cost": 0,
  "rarity": "Special"
 }
};

export default cardMeta;
