// 生成物：`python native/build_zh_i18n.py` 重建，**不要手改**。
//
// 「种类」与「要不要玩家选目标」都来自内容包（`Cards[].Tags` + 程序里的 `sel.eventTarget`）。
// ⚠️ **不从动作表的 targetSlot 反推**：内核故意为"每张可出的牌 × 每个活敌人"各发一条
// 动作（它无法廉价判断定向性），那是**枚举策略**，不是卡牌语义（第十四轮 Review P1-A）。

export interface CardMeta {
  readonly kind: "attack" | "skill" | "power" | "status" | "curse";
  readonly targeting: "none" | "singleEnemy";
}

const cardMeta: Record<string, CardMeta> = {
 "strike": {
  "kind": "attack",
  "targeting": "singleEnemy"
 },
 "defend": {
  "kind": "skill",
  "targeting": "none"
 },
 "bash": {
  "kind": "attack",
  "targeting": "singleEnemy"
 },
 "slimed": {
  "kind": "status",
  "targeting": "none"
 },
 "strike+": {
  "kind": "attack",
  "targeting": "singleEnemy"
 },
 "defend+": {
  "kind": "skill",
  "targeting": "none"
 },
 "bash+": {
  "kind": "attack",
  "targeting": "singleEnemy"
 },
 "twin_strike": {
  "kind": "attack",
  "targeting": "singleEnemy"
 },
 "iron_wave": {
  "kind": "attack",
  "targeting": "singleEnemy"
 },
 "clothesline": {
  "kind": "attack",
  "targeting": "singleEnemy"
 },
 "anger": {
  "kind": "attack",
  "targeting": "singleEnemy"
 },
 "uppercut": {
  "kind": "attack",
  "targeting": "singleEnemy"
 },
 "injury": {
  "kind": "curse",
  "targeting": "none"
 },
 "sentinel": {
  "kind": "skill",
  "targeting": "none"
 },
 "patient_guard": {
  "kind": "skill",
  "targeting": "none"
 },
 "swift_strike": {
  "kind": "attack",
  "targeting": "singleEnemy"
 },
 "whirlwind": {
  "kind": "attack",
  "targeting": "none"
 },
 "whirlwind+": {
  "kind": "attack",
  "targeting": "none"
 },
 "apparition": {
  "kind": "skill",
  "targeting": "none"
 },
 "buffer": {
  "kind": "power",
  "targeting": "none"
 },
 "anger+": {
  "kind": "attack",
  "targeting": "singleEnemy"
 },
 "twin_strike+": {
  "kind": "attack",
  "targeting": "singleEnemy"
 },
 "iron_wave+": {
  "kind": "attack",
  "targeting": "singleEnemy"
 },
 "clothesline+": {
  "kind": "attack",
  "targeting": "singleEnemy"
 },
 "uppercut+": {
  "kind": "attack",
  "targeting": "singleEnemy"
 },
 "sentinel+": {
  "kind": "skill",
  "targeting": "none"
 },
 "patient_guard+": {
  "kind": "skill",
  "targeting": "none"
 },
 "swift_strike+": {
  "kind": "attack",
  "targeting": "singleEnemy"
 },
 "apparition+": {
  "kind": "skill",
  "targeting": "none"
 },
 "buffer+": {
  "kind": "power",
  "targeting": "none"
 },
 "inflame": {
  "kind": "power",
  "targeting": "none"
 },
 "inflame+": {
  "kind": "power",
  "targeting": "none"
 },
 "metallicize": {
  "kind": "power",
  "targeting": "none"
 },
 "metallicize+": {
  "kind": "power",
  "targeting": "none"
 },
 "combust": {
  "kind": "power",
  "targeting": "none"
 },
 "combust+": {
  "kind": "power",
  "targeting": "none"
 },
 "wound": {
  "kind": "status",
  "targeting": "none"
 },
 "burn": {
  "kind": "status",
  "targeting": "none"
 },
 "bandage_up": {
  "kind": "skill",
  "targeting": "none"
 },
 "blind": {
  "kind": "skill",
  "targeting": "none"
 },
 "dark_shackles": {
  "kind": "skill",
  "targeting": "singleEnemy"
 },
 "ascenders_bane": {
  "kind": "curse",
  "targeting": "none"
 },
 "dazed": {
  "kind": "status",
  "targeting": "none"
 },
 "burn+": {
  "kind": "status",
  "targeting": "none"
 },
 "void": {
  "kind": "status",
  "targeting": "none"
 },
 "barricade": {
  "kind": "power",
  "targeting": "none"
 },
 "blur": {
  "kind": "skill",
  "targeting": "none"
 },
 "barricade+": {
  "kind": "power",
  "targeting": "none"
 },
 "blur+": {
  "kind": "skill",
  "targeting": "none"
 },
 "berserk": {
  "kind": "power",
  "targeting": "none"
 },
 "berserk+": {
  "kind": "power",
  "targeting": "none"
 },
 "cleave": {
  "kind": "attack",
  "targeting": "none"
 },
 "cleave+": {
  "kind": "attack",
  "targeting": "none"
 },
 "pommel_strike": {
  "kind": "attack",
  "targeting": "singleEnemy"
 },
 "pommel_strike+": {
  "kind": "attack",
  "targeting": "singleEnemy"
 },
 "shrug_it_off": {
  "kind": "skill",
  "targeting": "none"
 },
 "shrug_it_off+": {
  "kind": "skill",
  "targeting": "none"
 },
 "thunderclap": {
  "kind": "attack",
  "targeting": "none"
 },
 "thunderclap+": {
  "kind": "attack",
  "targeting": "none"
 },
 "bludgeon": {
  "kind": "attack",
  "targeting": "singleEnemy"
 },
 "bludgeon+": {
  "kind": "attack",
  "targeting": "singleEnemy"
 },
 "impervious": {
  "kind": "skill",
  "targeting": "none"
 },
 "impervious+": {
  "kind": "skill",
  "targeting": "none"
 },
 "pummel": {
  "kind": "attack",
  "targeting": "singleEnemy"
 },
 "pummel+": {
  "kind": "attack",
  "targeting": "singleEnemy"
 },
 "wild_strike": {
  "kind": "attack",
  "targeting": "singleEnemy"
 },
 "wild_strike+": {
  "kind": "attack",
  "targeting": "singleEnemy"
 },
 "ghostly_armor": {
  "kind": "skill",
  "targeting": "none"
 },
 "ghostly_armor+": {
  "kind": "skill",
  "targeting": "none"
 },
 "battle_trance": {
  "kind": "skill",
  "targeting": "none"
 },
 "battle_trance+": {
  "kind": "skill",
  "targeting": "none"
 },
 "doubt": {
  "kind": "curse",
  "targeting": "none"
 },
 "writhe": {
  "kind": "curse",
  "targeting": "none"
 },
 "second_wind": {
  "kind": "skill",
  "targeting": "none"
 },
 "second_wind+": {
  "kind": "skill",
  "targeting": "none"
 },
 "fiend_fire": {
  "kind": "attack",
  "targeting": "singleEnemy"
 },
 "fiend_fire+": {
  "kind": "attack",
  "targeting": "singleEnemy"
 },
 "dual_wield": {
  "kind": "skill",
  "targeting": "none"
 },
 "dual_wield+": {
  "kind": "skill",
  "targeting": "none"
 },
 "armaments": {
  "kind": "skill",
  "targeting": "none"
 },
 "armaments+": {
  "kind": "skill",
  "targeting": "none"
 },
 "warcry": {
  "kind": "skill",
  "targeting": "none"
 },
 "warcry+": {
  "kind": "skill",
  "targeting": "none"
 },
 "nightmare": {
  "kind": "skill",
  "targeting": "none"
 },
 "nightmare+": {
  "kind": "skill",
  "targeting": "none"
 },
 "sword_boomerang": {
  "kind": "attack",
  "targeting": "none"
 },
 "sword_boomerang+": {
  "kind": "attack",
  "targeting": "none"
 },
 "body_slam": {
  "kind": "attack",
  "targeting": "singleEnemy"
 },
 "body_slam+": {
  "kind": "attack",
  "targeting": "singleEnemy"
 },
 "rip_and_tear": {
  "kind": "attack",
  "targeting": "none"
 },
 "rip_and_tear+": {
  "kind": "attack",
  "targeting": "none"
 },
 "rampage": {
  "kind": "attack",
  "targeting": "singleEnemy"
 },
 "rampage+": {
  "kind": "attack",
  "targeting": "singleEnemy"
 },
 "searing_blow": {
  "kind": "attack",
  "targeting": "singleEnemy"
 },
 "searing_blow+": {
  "kind": "attack",
  "targeting": "singleEnemy"
 },
 "searing_blow++": {
  "kind": "attack",
  "targeting": "singleEnemy"
 },
 "searing_blow+++": {
  "kind": "attack",
  "targeting": "singleEnemy"
 },
 "searing_blow++++": {
  "kind": "attack",
  "targeting": "singleEnemy"
 },
 "searing_blow+++++": {
  "kind": "attack",
  "targeting": "singleEnemy"
 },
 "searing_blow++++++": {
  "kind": "attack",
  "targeting": "singleEnemy"
 },
 "searing_blow+++++++": {
  "kind": "attack",
  "targeting": "singleEnemy"
 },
 "flex": {
  "kind": "skill",
  "targeting": "none"
 },
 "flex+": {
  "kind": "skill",
  "targeting": "none"
 },
 "limit_break": {
  "kind": "skill",
  "targeting": "none"
 },
 "limit_break+": {
  "kind": "skill",
  "targeting": "none"
 },
 "perfected_strike": {
  "kind": "attack",
  "targeting": "singleEnemy"
 },
 "perfected_strike+": {
  "kind": "attack",
  "targeting": "singleEnemy"
 },
 "true_grit": {
  "kind": "skill",
  "targeting": "none"
 },
 "true_grit+": {
  "kind": "skill",
  "targeting": "none"
 },
 "reaper": {
  "kind": "attack",
  "targeting": "none"
 },
 "reaper+": {
  "kind": "attack",
  "targeting": "none"
 },
 "skewer": {
  "kind": "attack",
  "targeting": "singleEnemy"
 },
 "skewer+": {
  "kind": "attack",
  "targeting": "singleEnemy"
 },
 "malaise": {
  "kind": "skill",
  "targeting": "singleEnemy"
 },
 "malaise+": {
  "kind": "skill",
  "targeting": "singleEnemy"
 },
 "entrench": {
  "kind": "skill",
  "targeting": "none"
 },
 "entrench+": {
  "kind": "skill",
  "targeting": "none"
 },
 "carnage": {
  "kind": "attack",
  "targeting": "singleEnemy"
 },
 "carnage+": {
  "kind": "attack",
  "targeting": "singleEnemy"
 },
 "disarm": {
  "kind": "skill",
  "targeting": "singleEnemy"
 },
 "disarm+": {
  "kind": "skill",
  "targeting": "singleEnemy"
 },
 "immolate": {
  "kind": "attack",
  "targeting": "none"
 },
 "immolate+": {
  "kind": "attack",
  "targeting": "none"
 },
 "intimidate": {
  "kind": "skill",
  "targeting": "none"
 },
 "intimidate+": {
  "kind": "skill",
  "targeting": "none"
 },
 "shockwave": {
  "kind": "skill",
  "targeting": "none"
 },
 "shockwave+": {
  "kind": "skill",
  "targeting": "none"
 },
 "seeing_red": {
  "kind": "skill",
  "targeting": "none"
 },
 "seeing_red+": {
  "kind": "skill",
  "targeting": "none"
 },
 "flame_barrier": {
  "kind": "skill",
  "targeting": "none"
 },
 "flame_barrier+": {
  "kind": "skill",
  "targeting": "none"
 },
 "rage": {
  "kind": "skill",
  "targeting": "none"
 },
 "rage+": {
  "kind": "skill",
  "targeting": "none"
 },
 "power_through": {
  "kind": "skill",
  "targeting": "none"
 },
 "power_through+": {
  "kind": "skill",
  "targeting": "none"
 },
 "reckless_charge": {
  "kind": "attack",
  "targeting": "singleEnemy"
 },
 "reckless_charge+": {
  "kind": "attack",
  "targeting": "singleEnemy"
 },
 "sever_soul": {
  "kind": "attack",
  "targeting": "singleEnemy"
 },
 "sever_soul+": {
  "kind": "attack",
  "targeting": "singleEnemy"
 },
 "dropkick": {
  "kind": "attack",
  "targeting": "singleEnemy"
 },
 "dropkick+": {
  "kind": "attack",
  "targeting": "singleEnemy"
 },
 "headbutt": {
  "kind": "attack",
  "targeting": "singleEnemy"
 },
 "headbutt+": {
  "kind": "attack",
  "targeting": "singleEnemy"
 },
 "demon_form": {
  "kind": "power",
  "targeting": "none"
 },
 "demon_form+": {
  "kind": "power",
  "targeting": "none"
 },
 "bloodletting": {
  "kind": "skill",
  "targeting": "none"
 },
 "bloodletting+": {
  "kind": "skill",
  "targeting": "none"
 },
 "hemokinesis": {
  "kind": "attack",
  "targeting": "singleEnemy"
 },
 "hemokinesis+": {
  "kind": "attack",
  "targeting": "singleEnemy"
 },
 "offering": {
  "kind": "skill",
  "targeting": "none"
 },
 "offering+": {
  "kind": "skill",
  "targeting": "none"
 },
 "brutality": {
  "kind": "power",
  "targeting": "none"
 },
 "brutality+": {
  "kind": "power",
  "targeting": "none"
 },
 "rupture": {
  "kind": "power",
  "targeting": "none"
 },
 "rupture+": {
  "kind": "power",
  "targeting": "none"
 },
 "juggernaut": {
  "kind": "power",
  "targeting": "none"
 },
 "juggernaut+": {
  "kind": "power",
  "targeting": "none"
 },
 "evolve": {
  "kind": "power",
  "targeting": "none"
 },
 "evolve+": {
  "kind": "power",
  "targeting": "none"
 },
 "fire_breathing": {
  "kind": "power",
  "targeting": "none"
 },
 "fire_breathing+": {
  "kind": "power",
  "targeting": "none"
 },
 "dark_embrace": {
  "kind": "power",
  "targeting": "none"
 },
 "dark_embrace+": {
  "kind": "power",
  "targeting": "none"
 },
 "feel_no_pain": {
  "kind": "power",
  "targeting": "none"
 },
 "feel_no_pain+": {
  "kind": "power",
  "targeting": "none"
 },
 "heavy_blade": {
  "kind": "attack",
  "targeting": "singleEnemy"
 },
 "heavy_blade+": {
  "kind": "attack",
  "targeting": "singleEnemy"
 },
 "double_tap": {
  "kind": "skill",
  "targeting": "none"
 },
 "double_tap+": {
  "kind": "skill",
  "targeting": "none"
 },
 "exhume": {
  "kind": "skill",
  "targeting": "none"
 },
 "exhume+": {
  "kind": "skill",
  "targeting": "none"
 },
 "feed": {
  "kind": "attack",
  "targeting": "singleEnemy"
 },
 "feed+": {
  "kind": "attack",
  "targeting": "singleEnemy"
 },
 "clash": {
  "kind": "attack",
  "targeting": "singleEnemy"
 },
 "clash+": {
  "kind": "attack",
  "targeting": "singleEnemy"
 },
 "burning_pact": {
  "kind": "skill",
  "targeting": "none"
 },
 "burning_pact+": {
  "kind": "skill",
  "targeting": "none"
 },
 "infernal_blade": {
  "kind": "skill",
  "targeting": "none"
 },
 "infernal_blade+": {
  "kind": "skill",
  "targeting": "none"
 },
 "havoc": {
  "kind": "skill",
  "targeting": "none"
 },
 "havoc+": {
  "kind": "skill",
  "targeting": "none"
 },
 "spot_weakness": {
  "kind": "skill",
  "targeting": "none"
 },
 "spot_weakness+": {
  "kind": "skill",
  "targeting": "none"
 },
 "blood_for_blood": {
  "kind": "attack",
  "targeting": "singleEnemy"
 },
 "blood_for_blood+": {
  "kind": "attack",
  "targeting": "singleEnemy"
 },
 "corruption": {
  "kind": "power",
  "targeting": "none"
 },
 "corruption+": {
  "kind": "power",
  "targeting": "none"
 },
 "trip": {
  "kind": "skill",
  "targeting": "singleEnemy"
 },
 "trip+": {
  "kind": "skill",
  "targeting": "none"
 },
 "panacea": {
  "kind": "skill",
  "targeting": "none"
 },
 "panacea+": {
  "kind": "skill",
  "targeting": "none"
 },
 "finesse": {
  "kind": "skill",
  "targeting": "none"
 },
 "finesse+": {
  "kind": "skill",
  "targeting": "none"
 },
 "flash_of_steel": {
  "kind": "attack",
  "targeting": "singleEnemy"
 },
 "flash_of_steel+": {
  "kind": "attack",
  "targeting": "singleEnemy"
 },
 "good_instincts": {
  "kind": "skill",
  "targeting": "none"
 },
 "good_instincts+": {
  "kind": "skill",
  "targeting": "none"
 },
 "master_of_strategy": {
  "kind": "skill",
  "targeting": "none"
 },
 "master_of_strategy+": {
  "kind": "skill",
  "targeting": "none"
 },
 "dramatic_entrance": {
  "kind": "attack",
  "targeting": "none"
 },
 "dramatic_entrance+": {
  "kind": "attack",
  "targeting": "none"
 },
 "impatience": {
  "kind": "skill",
  "targeting": "none"
 },
 "impatience+": {
  "kind": "skill",
  "targeting": "none"
 },
 "deep_breath": {
  "kind": "skill",
  "targeting": "none"
 },
 "deep_breath+": {
  "kind": "skill",
  "targeting": "none"
 },
 "insight": {
  "kind": "skill",
  "targeting": "none"
 },
 "insight+": {
  "kind": "skill",
  "targeting": "none"
 },
 "miracle": {
  "kind": "skill",
  "targeting": "none"
 },
 "miracle+": {
  "kind": "skill",
  "targeting": "none"
 },
 "mayhem": {
  "kind": "power",
  "targeting": "none"
 },
 "mayhem+": {
  "kind": "power",
  "targeting": "none"
 },
 "magnetism": {
  "kind": "power",
  "targeting": "none"
 },
 "magnetism+": {
  "kind": "power",
  "targeting": "none"
 },
 "chrysalis": {
  "kind": "skill",
  "targeting": "none"
 },
 "chrysalis+": {
  "kind": "skill",
  "targeting": "none"
 },
 "metamorphosis": {
  "kind": "skill",
  "targeting": "none"
 },
 "metamorphosis+": {
  "kind": "skill",
  "targeting": "none"
 },
 "jack_of_all_trades": {
  "kind": "skill",
  "targeting": "none"
 },
 "jack_of_all_trades+": {
  "kind": "skill",
  "targeting": "none"
 },
 "transmutation": {
  "kind": "skill",
  "targeting": "none"
 },
 "transmutation+": {
  "kind": "skill",
  "targeting": "none"
 },
 "secret_technique": {
  "kind": "skill",
  "targeting": "none"
 },
 "secret_technique+": {
  "kind": "skill",
  "targeting": "none"
 },
 "secret_weapon": {
  "kind": "skill",
  "targeting": "none"
 },
 "secret_weapon+": {
  "kind": "skill",
  "targeting": "none"
 },
 "violence": {
  "kind": "skill",
  "targeting": "none"
 },
 "violence+": {
  "kind": "skill",
  "targeting": "none"
 },
 "purity": {
  "kind": "skill",
  "targeting": "none"
 },
 "purity+": {
  "kind": "skill",
  "targeting": "none"
 },
 "apotheosis": {
  "kind": "skill",
  "targeting": "none"
 },
 "apotheosis+": {
  "kind": "skill",
  "targeting": "none"
 },
 "panic_button": {
  "kind": "skill",
  "targeting": "none"
 },
 "panic_button+": {
  "kind": "skill",
  "targeting": "none"
 },
 "thinking_ahead": {
  "kind": "skill",
  "targeting": "none"
 },
 "thinking_ahead+": {
  "kind": "skill",
  "targeting": "none"
 },
 "mind_blast": {
  "kind": "attack",
  "targeting": "singleEnemy"
 },
 "mind_blast+": {
  "kind": "attack",
  "targeting": "singleEnemy"
 },
 "enlightenment": {
  "kind": "skill",
  "targeting": "none"
 },
 "enlightenment+": {
  "kind": "skill",
  "targeting": "none"
 },
 "madness": {
  "kind": "skill",
  "targeting": "none"
 },
 "madness+": {
  "kind": "skill",
  "targeting": "none"
 },
 "omega": {
  "kind": "power",
  "targeting": "none"
 },
 "omega+": {
  "kind": "power",
  "targeting": "none"
 },
 "panache": {
  "kind": "power",
  "targeting": "none"
 },
 "panache+": {
  "kind": "power",
  "targeting": "none"
 },
 "sadistic_nature": {
  "kind": "power",
  "targeting": "none"
 },
 "sadistic_nature+": {
  "kind": "power",
  "targeting": "none"
 },
 "the_bomb": {
  "kind": "skill",
  "targeting": "none"
 },
 "the_bomb+": {
  "kind": "skill",
  "targeting": "none"
 },
 "ritual_dagger": {
  "kind": "attack",
  "targeting": "singleEnemy"
 },
 "ritual_dagger+": {
  "kind": "attack",
  "targeting": "singleEnemy"
 },
 "hand_of_greed": {
  "kind": "attack",
  "targeting": "singleEnemy"
 },
 "hand_of_greed+": {
  "kind": "attack",
  "targeting": "singleEnemy"
 },
 "discovery": {
  "kind": "skill",
  "targeting": "none"
 },
 "discovery+": {
  "kind": "skill",
  "targeting": "none"
 },
 "forethought": {
  "kind": "skill",
  "targeting": "none"
 },
 "forethought+": {
  "kind": "skill",
  "targeting": "none"
 },
 "clumsy": {
  "kind": "curse",
  "targeting": "none"
 },
 "curse_of_the_bell": {
  "kind": "curse",
  "targeting": "none"
 },
 "decay": {
  "kind": "curse",
  "targeting": "none"
 },
 "necronomicurse": {
  "kind": "curse",
  "targeting": "none"
 },
 "normality": {
  "kind": "curse",
  "targeting": "none"
 },
 "pain": {
  "kind": "curse",
  "targeting": "none"
 },
 "parasite": {
  "kind": "curse",
  "targeting": "none"
 },
 "pride": {
  "kind": "curse",
  "targeting": "none"
 },
 "regret": {
  "kind": "curse",
  "targeting": "none"
 },
 "shame": {
  "kind": "curse",
  "targeting": "none"
 },
 "bite": {
  "kind": "attack",
  "targeting": "singleEnemy"
 },
 "bite+": {
  "kind": "attack",
  "targeting": "singleEnemy"
 },
 "expunger": {
  "kind": "attack",
  "targeting": "singleEnemy"
 },
 "expunger+": {
  "kind": "attack",
  "targeting": "singleEnemy"
 },
 "shiv": {
  "kind": "attack",
  "targeting": "singleEnemy"
 },
 "shiv+": {
  "kind": "attack",
  "targeting": "singleEnemy"
 },
 "smite": {
  "kind": "attack",
  "targeting": "singleEnemy"
 },
 "smite+": {
  "kind": "attack",
  "targeting": "singleEnemy"
 },
 "beta": {
  "kind": "skill",
  "targeting": "none"
 },
 "beta+": {
  "kind": "skill",
  "targeting": "none"
 },
 "through_violence": {
  "kind": "attack",
  "targeting": "singleEnemy"
 },
 "through_violence+": {
  "kind": "attack",
  "targeting": "singleEnemy"
 },
 "j.a.x.": {
  "kind": "skill",
  "targeting": "none"
 },
 "j.a.x.+": {
  "kind": "skill",
  "targeting": "none"
 },
 "safety": {
  "kind": "skill",
  "targeting": "none"
 },
 "safety+": {
  "kind": "skill",
  "targeting": "none"
 },
 "become_almighty": {
  "kind": "power",
  "targeting": "none"
 },
 "become_almighty+": {
  "kind": "power",
  "targeting": "none"
 },
 "live_forever": {
  "kind": "power",
  "targeting": "none"
 },
 "live_forever+": {
  "kind": "power",
  "targeting": "none"
 },
 "fame_and_fortune": {
  "kind": "skill",
  "targeting": "none"
 },
 "fame_and_fortune+": {
  "kind": "skill",
  "targeting": "none"
 },
 "wish": {
  "kind": "skill",
  "targeting": "none"
 },
 "wish+": {
  "kind": "skill",
  "targeting": "none"
 },
 "conjure_blade": {
  "kind": "skill",
  "targeting": "none"
 },
 "conjure_blade+": {
  "kind": "skill",
  "targeting": "none"
 },
 "jax": {
  "kind": "skill",
  "targeting": "none"
 },
 "jax+": {
  "kind": "skill",
  "targeting": "none"
 }
};

export default cardMeta;
