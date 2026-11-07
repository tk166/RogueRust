# 覆盖矩阵（**生成物，别手改**）

> 生成：`python -X utf8 native/coverage_matrix.py`；校验：`... --check`（闸门 13 就是它）。
> 手改这一页会让闸门红 —— 这是故意的：一张"人维护的覆盖表"活不过下一次内容变更。

回答一个问题：**每一个实体（怪/动作/卡/状态/遭遇/事件/遗物/药水）被验证到哪里了？**
下面这张 807 行的表靠记性是维护不了的，所以每一列都是派生的（口径见 `native/coverage_matrix.py` 顶部）：

**⚠️ 这七列没有一列声称"行为正确"。** 它们回答的是三个更弱、但可以被机器检查的问题：
*这个实体有没有出处？有没有被任何测试引用？有没有人写下"它和 wiki 不一样"？*

* **Implemented** —— 在内容里且**可达**（`orphan` = 内容长出一条没人引用的行，闸门红）。
  可达性的口径按类别不同（怪=遭遇名单/`spawn`；动作=动作表/AI 规则；状态=程序/触发器/药水原子；
  卡=起始牌组或按稀有度的牌池），逐条写在 `coverage_matrix.py` 的 `build_entities` 里。
* **TestNamed** —— 这个 id 以**字符串字面量**出现在某条内核测试的函数体里（注释里的不算）。
  ⚠️ **它是"被引用"，不是"行为被断言"**：`assert_eq!(id, "spiker")` 与"真打一场 spiker 的战斗"
  在这一列里长得一模一样。§217 之前这一列叫 `RuntimeTested`，那个名字把"引用"读成了"验证"。
  测试名来自递归扫描（`cargo test -- --list` 是它的独立对账：906 条）。
* **HarnessOnly** —— 没有具名引用，但**整表遍历**盖到它了：`ENEMY_DIFF`（跑每一条 `EACT`）、
  `CARD_DIFF`（跑每一张卡）、或内核里"遍历整张表"的测试（`the_potions_are_readable` 之类）。
  这比 `TestNamed` 更弱：它只说明"跑过、程序文本与参考实现一致"。
* **SourceTie** —— `wiki:<dump>`：`native/wiki_asc/`（或 `native/wiki_*.txt`）里有它的 Infobox
  **并且** checker 钉了它的数字；动作那侧的括号 `(via <怪物>)` 是**必须写出来**的 ——
  页面来自所属怪物，不是这条动作自己核过（`maw.nom_nom` 有 wiki 标签、时间变量却错了，就是反例）。
  `spec:<TABLE>`：只对上了 `sts_content_check.py` 里那份**也是人抄的**清单。
  `—`：没有任何独立来源 —— **这一列是本页最大的洞，不粉饰**。
* **DeclaredDeviation** —— 声明过的偏差（`INV_UNWIRED` / `INV_NO_ASC` / `INV_NO_ASC_HP` /
  `docs/sts-wiki-gap.md` §G、§H 两张表，直接解析）。
* **Evidence** —— `§N`（`sts_content_check.py` 引用到的 port-plan 小节）+ 不变量表 + 测试名。

**怎么用**：想找下一件该干的活，按 `SourceTie = —` 或 `TestNamed = —` 排下去就是待办。
**不要**把 `TestNamed` 当成"已经验证过"——要验证语义，得去看那条测试**断言了什么**。


## 汇总（每类实体数 × 证据强度）

| 类别 | 行数 | TestNamed | HarnessOnly | 两层都没有 | SourceTie:wiki | SourceTie:spec | 有偏差声明 | orphan |
|---|---|---|---|---|---|---|---|---|
| 怪物 | 49 | 41 | 0 | 8 | 49 | 0 | 11 | 0 |
| 敌人动作 | 135 | 73 | 62 | 0 | 135 | 0 | 52 | 0 |
| 卡牌 | 293 | 164 | 129 | 0 | 281 | 12 | 18 | 0 |
| 状态 | 126 | 119 | 6 | 1 | 0 | 126 | 1 | 0 |
| 遭遇 | 43 | 32 | 11 | 0 | 0 | 0 | 0 | 0 |
| 事件 | 13 | 13 | 0 | 0 | 0 | 0 | 0 | 0 |
| 遗物 | 115 | 109 | 6 | 0 | 0 | 0 | 0 | 0 |
| 药水 | 33 | 33 | 0 | 0 | 0 | 0 | 0 | 0 |
| **合计** | 807 | 584 | 214 | 9 | 465 | 138 | 82 | 0 |

扫描到的具名测试：**1077** 条；wiki dump：**45** 份（其中 49 只怪有 dump）。

事件：池里有 **16** 个位次、**13** 个不同 id（`golden_idol` / `ancient_forge` / `purification_shrine` 跨幕复用）。

同一页面的早期副本（内容同源，矩阵只用 `wiki_asc/` 那一份）：`wiki_book_of_stabbing.txt`、`wiki_lagavulin.txt`、`wiki_nemesis.txt`、`wiki_reptomancer.txt`、`wiki_slavers.txt`、`wiki_taskmaster.txt`

## 怪物（49）

| Entity | Implemented | TestNamed | HarnessOnly | SourceTie | DeclaredDeviation | Evidence |
|---|---|---|---|---|---|---|
| acid_slime_l | yes | — | — | wiki:wiki_asc/acid_slime.txt | — | §276/INV_ASC_HP+INV_MONSTERS |
| acid_slime_m | yes | a_large_slime_splits_at_half_health_with_its_current_hp, a_split_spawns_two_combatants_when_the_boss_dies …(+2) | — | wiki:wiki_asc/acid_slime.txt | — | §276/INV_ASC_HP+INV_MONSTERS/a_large_slime_splits_at_half_health_with_its_current_hp |
| acid_slime_s | yes | — | — | wiki:wiki_asc/acid_slime.txt | — | §276/INV_ASC_HP+INV_MONSTERS |
| awakened_one | yes | the_awakened_one_survives_its_first_death_and_then_really_dies, the_awakened_one_draws_phase_one_by_weight_and_flips_on_the_guard …(+3) | — | wiki:wiki_asc/awakened_one.txt | gap §H: 二阶段"不能连续三次 Tackle/Sludge"未做（规则预算 8 条已满）；Regenerate/Curiosity 层数不随 A19 变 | §195.8/INV_ASC_HP+INV_MONSTERS/the_awakened_one_survives_its_first_death_and_then_really_dies |
| blue_slaver | yes | the_five_elite_encounters_match_the_wiki_numbers, the_act_one_hard_pool_encounters_match_the_wiki_numbers …(+2) | — | wiki:wiki_asc/slavers.txt | — | INV_ASC_HP+INV_MONSTERS/the_five_elite_encounters_match_the_wiki_numbers |
| book_of_stabbing | yes | the_five_elite_encounters_match_the_wiki_numbers, book_of_stabbing_multistab_starts_at_two_hits | — | wiki:wiki_asc/book_of_stabbing.txt | — | §173/§257/INV_ASC_HP+INV_MONSTERS+INV_SPAWN_COUNTERS/the_five_elite_encounters_match_the_wiki_numbers |
| bronze_automaton | yes | stasis_steals_the_best_card_and_returns_it_when_the_orb_dies, a_96_card_pile_still_reaches_the_best_card_at_the_end …(+5) | — | wiki:wiki_asc/bronze_automaton.txt | gap §H: Orb 的 `Stasis` 用"最高稀有度"（并列随机），与 wiki 一致；"同一招不能三次"已做 | §138/§194/INV_ASC_HP+INV_MONSTERS/stasis_steals_the_best_card_and_returns_it_when_the_orb_dies |
| bronze_orb | yes | a_weighted_boss_never_repeats_the_move_the_wiki_forbids, a_minion_is_not_on_the_field_until_its_summon_lands …(+1) | — | wiki:wiki_asc/bronze_automaton.txt | gap §H: Orb 的 `Stasis` 用"最高稀有度"（并列随机），与 wiki 一致；"同一招不能三次"已做 | §194/§195.6/INV_ASC_HP+INV_MONSTERS/a_weighted_boss_never_repeats_the_move_the_wiki_forbids |
| byrd | yes | flying_halves_attack_damage_and_loses_a_stack_per_hit | — | wiki:wiki_asc/byrd.txt | — | §208/§213/INV_ASC_HP+INV_MONSTERS/flying_halves_attack_damage_and_loses_a_stack_per_hit |
| chosen | yes | hex_shuffles_a_dazed_only_for_non_attack_cards, chosen_swaps_its_opener_at_a17 …(+1) | — | wiki:wiki_asc/chosen.txt | — | §130/§213/INV_ASC_HP+INV_MONSTERS/hex_shuffles_a_dazed_only_for_non_attack_cards |
| cultist | yes | building_a_fight_keeps_the_ascension_but_not_the_last_fights_gold, a_fight_built_from_the_content_deck_can_play_a_strike …(+8) | — | wiki:wiki_asc/cultist.txt | — | §5.2/§195.8/INV_ASC_HP+INV_MONSTERS/building_a_fight_keeps_the_ascension_but_not_the_last_fights_gold |
| dagger | yes | the_five_elite_encounters_match_the_wiki_numbers, reptomancer_switches_to_snake_strike_when_four_daggers_are_out | — | wiki:wiki_asc/dagger.txt | — | §175/INV_ASC_HP+INV_MONSTERS/the_five_elite_encounters_match_the_wiki_numbers |
| darkling | yes | an_encounter_with_two_records_of_the_same_id_builds | — | wiki:wiki_asc/darkling.txt | — | §129/§137/INV_ASC_HP+INV_MONSTERS+INV_ROLLS/an_encounter_with_two_records_of_the_same_id_builds |
| deca | yes | donus_circle_of_power_buffs_the_enemy_team_and_not_the_player | — | wiki:wiki_asc/donu_and_deca.txt | gap §H: Artifact 层数不随 A19 变（`StartingStatuses` 没有升档轴） | §195.8/INV_ASC_HP+INV_MONSTERS/donus_circle_of_power_buffs_the_enemy_team_and_not_the_player |
| donu | yes | donus_circle_of_power_buffs_the_enemy_team_and_not_the_player | — | wiki:wiki_asc/donu_and_deca.txt | gap §H: Artifact 层数不随 A19 变（`StartingStatuses` 没有升档轴） | §195.8/INV_ASC_HP+INV_MONSTERS/donus_circle_of_power_buffs_the_enemy_team_and_not_the_player |
| fat_gremlin | yes | — | — | wiki:wiki_asc/fat_gremlin.txt | — | §138/§214/INV_ASC_HP+INV_MONSTERS |
| fungi_beast | yes | the_act_one_hard_pool_encounters_match_the_wiki_numbers, act_two_fights_act_two_enemies | — | wiki:wiki_asc/fungi_beast.txt | — | §258/INV_ASC_HP+INV_MONSTERS/the_act_one_hard_pool_encounters_match_the_wiki_numbers |
| giant_head | yes | giant_head_counts_down_then_only_its_time, it_is_time_escalates_by_five_and_respects_its_cap | — | wiki:wiki_asc/giant_head.txt | — | §134/§211/INV_ASC_HP+INV_MONSTERS+INV_SPAWN_COUNTERS/giant_head_counts_down_then_only_its_time |
| gremlin_leader | yes | the_summon_cap_is_a_loud_failure | — | wiki:wiki_asc/gremlin_leader.txt | — | §134/§212/INV_ASC_HP+INV_MONSTERS/the_summon_cap_is_a_loud_failure |
| gremlin_nob | yes | — | — | wiki:wiki_asc/gremlin_nob.txt | — | §152/INV_ASC_HP+INV_MONSTERS |
| gremlin_wizard | yes | — | — | wiki:wiki_asc/gremlin_wizard.txt | — | §130/§138/INV_ASC_HP+INV_MONSTERS |
| hexaghost | yes | hexaghost_plays_the_wikis_seven_move_pattern_after_its_two_openers, the_boss_is_offered_at_floor_16_and_clears_the_act | — | wiki:wiki_asc/hexaghost.txt | gap §H: Sear 后续塞的 Burn 不自动升级（wiki："for the rest of combat"）；Divider 读结算时 HP | INV_ASC_HP+INV_MONSTERS/hexaghost_plays_the_wikis_seven_move_pattern_after_its_two_openers |
| jaw_worm | yes | spot_weakness_follows_the_enemy_intent, a_round_one_rule_beats_the_cycle_and_the_cycle_takes_over_after_it …(+2) | — | wiki:wiki_asc/jaw_worm.txt | — | §5.2/INV_ASC_HP+INV_MONSTERS/spot_weakness_follows_the_enemy_intent |
| lagavulin | yes | the_five_elite_encounters_match_the_wiki_numbers, lagavulin_wakes_when_it_loses_health_and_loses_a_turn …(+2) | — | wiki:wiki_asc/lagavulin.txt | — | §173/INV_ASC_HP+INV_MONSTERS/the_five_elite_encounters_match_the_wiki_numbers |
| looter | yes | ascension_two_makes_the_looter_mug_hit_for_eleven, a_looter_steals_thievery_gold_on_every_attack_and_carries_it_away …(+5) | — | wiki:wiki_asc/thieves.txt | — | §175/§201/INV_ASC_HP+INV_MONSTERS/ascension_two_makes_the_looter_mug_hit_for_eleven |
| louse_green | yes | the_act_one_hard_pool_encounters_match_the_wiki_numbers, the_composed_encounters_pick_from_their_candidates …(+2) | — | wiki:wiki_asc/louses.txt | — | §258/§275/INV_ASC_HP+INV_MONSTERS+INV_ROLLS/the_act_one_hard_pool_encounters_match_the_wiki_numbers |
| louse_red | yes | a_spawn_roll_is_drawn_once_per_fight_and_read_by_the_action, an_encounter_without_rolls_draws_nothing …(+5) | — | wiki:wiki_asc/louses.txt | — | §258/§275/INV_ASC_HP+INV_MONSTERS+INV_ROLLS/a_spawn_roll_is_drawn_once_per_fight_and_read_by_the_action |
| maw | yes | nom_nom_hits_five_damage_ceil_round_over_two_times, the_maw_follows_the_wikis_transition_table | — | wiki:wiki_asc/the_maw.txt | 无 AscHP：wiki The Maw: max HP does not change with ascension | §207/§212/INV_MONSTERS+INV_NO_ASC_HP/nom_nom_hits_five_damage_ceil_round_over_two_times |
| nemesis | yes | the_five_elite_encounters_match_the_wiki_numbers, nemesis_never_repeats_burn_or_scythe_and_never_triple_attacks | — | wiki:wiki_asc/nemesis.txt | — | §175/INV_ASC_HP+INV_MONSTERS/the_five_elite_encounters_match_the_wiki_numbers |
| orb_walker | yes | — | — | wiki:wiki_asc/orb_walker.txt | — | §208/§214/INV_ASC_HP+INV_MONSTERS |
| reptomancer | yes | the_five_elite_encounters_match_the_wiki_numbers, reptomancer_switches_to_snake_strike_when_four_daggers_are_out …(+1) | — | wiki:wiki_asc/reptomancer.txt | — | §175/INV_ASC_HP+INV_MONSTERS/the_five_elite_encounters_match_the_wiki_numbers |
| sentry_1 | yes | a_turn_boundary_leaves_no_chain_referenced, dexterity_from_the_content_scales_a_real_defend …(+2) | — | wiki:wiki_asc/sentry.txt | — | §4.2/§134/INV_ASC_HP+INV_MONSTERS/a_turn_boundary_leaves_no_chain_referenced |
| sentry_2 | yes | a_long_fight_never_reports_a_step_problem | — | wiki:wiki_asc/sentry.txt | — | §4.2/§134/INV_ASC_HP+INV_MONSTERS/a_long_fight_never_reports_a_step_problem |
| sentry_3 | yes | a_long_fight_never_reports_a_step_problem | — | wiki:wiki_asc/sentry.txt | — | §134/INV_ASC_HP+INV_MONSTERS/a_long_fight_never_reports_a_step_problem |
| shelled_parasite | yes | act_two_fights_act_two_enemies | — | wiki:wiki_asc/shelled_parasite.txt | — | §130/INV_ASC_HP+INV_MONSTERS/act_two_fights_act_two_enemies |
| slaver_red | yes | the_five_elite_encounters_match_the_wiki_numbers, the_composed_encounters_pick_from_their_candidates …(+1) | — | wiki:wiki_asc/slavers.txt | — | §258/INV_ASC_HP+INV_MONSTERS/the_five_elite_encounters_match_the_wiki_numbers |
| slime_boss | yes | a_phase_split_happens_once_even_under_three_hits, the_boss_is_offered_at_floor_16_and_clears_the_act | — | wiki:wiki_asc/slime_boss.txt | — | §4.3/INV_ASC_HP+INV_MONSTERS/a_phase_split_happens_once_even_under_three_hits |
| sneaky_gremlin | yes | — | — | wiki:wiki_asc/sneaky_gremlin.txt | — | §130/§138/INV_ASC_HP+INV_MONSTERS |
| spike_slime_l | yes | — | — | wiki:wiki_asc/spike_slime.txt | — | §276/INV_ASC_HP+INV_MONSTERS |
| spike_slime_m | yes | a_large_slime_splits_at_half_health_with_its_current_hp, the_composed_encounters_pick_from_their_candidates | — | wiki:wiki_asc/spike_slime.txt | — | INV_ASC_HP+INV_MONSTERS/a_large_slime_splits_at_half_health_with_its_current_hp |
| spike_slime_s | yes | a_minion_flees_when_its_master_falls, the_summon_cap_is_a_loud_failure | — | wiki:wiki_asc/spike_slime.txt | — | §276/INV_ASC_HP+INV_MONSTERS/a_minion_flees_when_its_master_falls |
| spiker | yes | spiker_never_repeats_its_attack_and_buffs_thorns_at_most_six_times, starting_statuses_follow_their_ascension_rows | — | wiki:wiki_asc/shapes.txt | — | §207/§214/INV_ASC_HP+INV_MONSTERS/spiker_never_repeats_its_attack_and_buffs_thorns_at_most_six_times |
| spire_growth | yes | spire_growth_smashes_instead_of_choosing | — | wiki:wiki_asc/spire_growth.txt | — | §148/§214/INV_ASC_HP+INV_MONSTERS/spire_growth_smashes_instead_of_choosing |
| taskmaster | yes | the_five_elite_encounters_match_the_wiki_numbers | — | wiki:wiki_asc/taskmaster.txt | — | INV_ASC_HP+INV_MONSTERS/the_five_elite_encounters_match_the_wiki_numbers |
| the_champ | yes | a_weighted_boss_never_repeats_the_move_the_wiki_forbids, the_champ_taunts_every_fourth_round_and_enters_phase_two_below_half …(+1) | — | wiki:wiki_asc/the_champ.txt | gap §H: A19 的 "Gloat 换成 Defensive Stance" 未实现；Anger 按名清 debuff；第二阶段只做第一次 Execute | §194/INV_ASC_HP+INV_MONSTERS/a_weighted_boss_never_repeats_the_move_the_wiki_forbids |
| the_collector | yes | the_collector_draws_by_weight_and_never_buffs_twice_in_a_row, a_minion_is_not_on_the_field_until_its_summon_lands | — | wiki:wiki_asc/the_collector.txt | gap §H: 25/45/30（0-1 只 Torch Head 时的权重）未分档 | §138/INV_ASC_HP+INV_MONSTERS/the_collector_draws_by_weight_and_never_buffs_twice_in_a_row |
| the_guardian | yes | mode_shift_is_a_budget_drained_by_the_health_actually_lost, building_a_guardian_fight_seeds_its_mode_shift_budget_by_ascension …(+1) | — | wiki:wiki_asc/the_guardian.txt | — | §194/INV_ASC_HP+INV_MONSTERS+INV_SPAWN_COUNTERS/mode_shift_is_a_budget_drained_by_the_health_actually_lost |
| time_eater | yes | a_weighted_boss_never_repeats_the_move_the_wiki_forbids, time_eater_head_slam_reaches_32_at_a4 | — | wiki:wiki_asc/time_eater.txt | gap §H: Haste 不清 debuff（没有"清空状态"节点）；`Draw Reduction` 已实现但 wiki 的"A19 另加 2 Slimed"没做 | §138/§211/INV_ASC_HP+INV_MONSTERS/a_weighted_boss_never_repeats_the_move_the_wiki_forbids |
| torch_head | yes | a_minion_is_not_on_the_field_until_its_summon_lands | — | wiki:wiki_asc/torch_head.txt | gap §H: 25/45/30（0-1 只 Torch Head 时的权重）未分档 | §138/§195.3/INV_ASC_HP+INV_MONSTERS/a_minion_is_not_on_the_field_until_its_summon_lands |

## 敌人动作（135）

| Entity | Implemented | TestNamed | HarnessOnly | SourceTie | DeclaredDeviation | Evidence |
|---|---|---|---|---|---|---|
| acid_slime_l.corrosive_spit | yes | — | ENEMY_DIFF | wiki:wiki_asc/acid_slime.txt (via acid_slime_l) | — | §276/INV_ACTIONS+INV_ASC_VARIANTS |
| acid_slime_l.lick | yes | — | ENEMY_DIFF | wiki:wiki_asc/acid_slime.txt (via acid_slime_l) · 仅基础值 | 无升档：wiki Slimes: A17 moves the weights and the no-repeat rule, not the stacks | §276/INV_ACTIONS+INV_NO_ASC |
| acid_slime_l.tackle | yes | — | ENEMY_DIFF | wiki:wiki_asc/acid_slime.txt (via acid_slime_l) | — | §276/INV_ACTIONS+INV_ASC_VARIANTS |
| acid_slime_m.corrosive_spit | yes | — | ENEMY_DIFF | wiki:wiki_asc/acid_slime.txt (via acid_slime_m) | — | §276/INV_ACTIONS+INV_ASC_VARIANTS |
| acid_slime_m.lick | yes | — | ENEMY_DIFF | wiki:wiki_asc/acid_slime.txt (via acid_slime_m) · 仅基础值 | 无升档：wiki Acid Slime: M Lick is 1 Weak, no A-row | §206/INV_ACTIONS+INV_NO_ASC |
| acid_slime_m.tackle | yes | — | ENEMY_DIFF | wiki:wiki_asc/acid_slime.txt (via acid_slime_m) | — | INV_ACTIONS+INV_ASC_VARIANTS |
| acid_slime_s.lick | yes | — | ENEMY_DIFF | wiki:wiki_asc/acid_slime.txt (via acid_slime_s) · 仅基础值 | 无升档：wiki Acid Slime: S Lick is 1 Weak, no A-row | §206/INV_ACTIONS+INV_NO_ASC |
| acid_slime_s.tackle | yes | — | ENEMY_DIFF | wiki:wiki_asc/acid_slime.txt (via acid_slime_s) | — | INV_ACTIONS+INV_ASC_VARIANTS |
| awakened_one.dark_echo | yes | the_awakened_one_draws_phase_one_by_weight_and_flips_on_the_guard | — | wiki:wiki_asc/awakened_one.txt (via awakened_one) · 仅基础值 | 无升档：wiki Awakened One: no A-row on moves | INV_ACTIONS+INV_NO_ASC/the_awakened_one_draws_phase_one_by_weight_and_flips_on_the_guard |
| awakened_one.rebirth | yes | the_awakened_one_survives_its_first_death_and_then_really_dies, the_awakened_one_draws_phase_one_by_weight_and_flips_on_the_guard | — | wiki:wiki_asc/awakened_one.txt (via awakened_one) · 仅基础值 | 无升档：wiki Awakened One: Rebirth is a rule, no numbers | INV_ACTIONS+INV_NO_ASC/the_awakened_one_survives_its_first_death_and_then_really_dies |
| awakened_one.slash | yes | the_awakened_one_draws_phase_one_by_weight_and_flips_on_the_guard | — | wiki:wiki_asc/awakened_one.txt (via awakened_one) · 仅基础值 | 无升档：wiki Awakened One: no A-row on moves | INV_ACTIONS+INV_NO_ASC/the_awakened_one_draws_phase_one_by_weight_and_flips_on_the_guard |
| awakened_one.sludge | yes | the_awakened_one_draws_phase_one_by_weight_and_flips_on_the_guard | — | wiki:wiki_asc/awakened_one.txt (via awakened_one) · 仅基础值 | 无升档：wiki Awakened One: no A-row on moves | INV_ACTIONS+INV_NO_ASC/the_awakened_one_draws_phase_one_by_weight_and_flips_on_the_guard |
| awakened_one.soul_strike | yes | the_awakened_one_draws_phase_one_by_weight_and_flips_on_the_guard | — | wiki:wiki_asc/awakened_one.txt (via awakened_one) · 仅基础值 | 无升档：wiki Awakened One: no A-row on moves | INV_ACTIONS+INV_NO_ASC/the_awakened_one_draws_phase_one_by_weight_and_flips_on_the_guard |
| awakened_one.tackle | yes | the_awakened_one_draws_phase_one_by_weight_and_flips_on_the_guard | — | wiki:wiki_asc/awakened_one.txt (via awakened_one) · 仅基础值 | 无升档：wiki Awakened One: no A-row on moves | INV_ACTIONS+INV_NO_ASC/the_awakened_one_draws_phase_one_by_weight_and_flips_on_the_guard |
| blue_slaver.rake | yes | blue_slaver_never_rakes_twice_in_a_row_at_a17 | — | wiki:wiki_asc/slavers.txt (via blue_slaver) | — | INV_ACTIONS+INV_ASC_VARIANTS/blue_slaver_never_rakes_twice_in_a_row_at_a17 |
| blue_slaver.stab | yes | blue_slaver_never_rakes_twice_in_a_row_at_a17 | — | wiki:wiki_asc/slavers.txt (via blue_slaver) | — | INV_ACTIONS+INV_ASC_VARIANTS/blue_slaver_never_rakes_twice_in_a_row_at_a17 |
| book_of_stabbing.big_stab | yes | — | ENEMY_DIFF | wiki:wiki_asc/book_of_stabbing.txt (via book_of_stabbing) | — | INV_ACTIONS+INV_ASC_VARIANTS |
| book_of_stabbing.multi_stab | yes | book_of_stabbing_multistab_starts_at_two_hits | — | wiki:wiki_asc/book_of_stabbing.txt (via book_of_stabbing) | — | INV_ACTIONS+INV_ASC_VARIANTS/book_of_stabbing_multistab_starts_at_two_hits |
| bronze_automaton.boost | yes | the_automaton_swaps_stunned_for_boost_only_at_a19 | — | wiki:wiki_asc/bronze_automaton.txt (via bronze_automaton) | — | §195.6/INV_ACTIONS+INV_ASC_VARIANTS/the_automaton_swaps_stunned_for_boost_only_at_a19 |
| bronze_automaton.flail | yes | the_automaton_swaps_stunned_for_boost_only_at_a19 | — | wiki:wiki_asc/bronze_automaton.txt (via bronze_automaton) | — | §195.6/INV_ACTIONS+INV_ASC_VARIANTS/the_automaton_swaps_stunned_for_boost_only_at_a19 |
| bronze_automaton.hyper_beam | yes | — | ENEMY_DIFF | wiki:wiki_asc/bronze_automaton.txt (via bronze_automaton) | — | INV_ACTIONS+INV_ASC_VARIANTS |
| bronze_automaton.spawn_orbs | yes | a_minion_is_not_on_the_field_until_its_summon_lands | — | wiki:wiki_asc/bronze_automaton.txt (via bronze_automaton) · 仅基础值 | 无升档：wiki Bronze Automaton: Spawn Orbs has no numbers | §195.6/INV_ACTIONS+INV_NO_ASC/a_minion_is_not_on_the_field_until_its_summon_lands |
| bronze_automaton.stunned | yes | the_automaton_swaps_stunned_for_boost_only_at_a19 | — | wiki:wiki_asc/bronze_automaton.txt (via bronze_automaton) · 仅基础值 | 无升档：wiki Bronze Automaton: Stunned does nothing | INV_ACTIONS+INV_NO_ASC/the_automaton_swaps_stunned_for_boost_only_at_a19 |
| bronze_orb.beam | yes | a_weighted_boss_never_repeats_the_move_the_wiki_forbids | — | wiki:wiki_asc/bronze_automaton.txt (via bronze_orb) · 仅基础值 | 无升档：wiki Bronze Orb: Beam is 8, no A-row | INV_ACTIONS+INV_NO_ASC/a_weighted_boss_never_repeats_the_move_the_wiki_forbids |
| bronze_orb.stasis | yes | stasis_steals_the_best_card_and_returns_it_when_the_orb_dies, a_96_card_pile_still_reaches_the_best_card_at_the_end …(+2) | — | wiki:wiki_asc/bronze_automaton.txt (via bronze_orb) · 仅基础值 | 无升档：wiki Bronze Orb: Stasis is a rule, no numbers | §195.4/INV_ACTIONS+INV_NO_ASC/stasis_steals_the_best_card_and_returns_it_when_the_orb_dies |
| bronze_orb.support_beam | yes | a_weighted_boss_never_repeats_the_move_the_wiki_forbids | — | wiki:wiki_asc/bronze_automaton.txt (via bronze_orb) · 仅基础值 | 无升档：wiki Bronze Orb: Support Beam is 12 Block, no A-row | INV_ACTIONS+INV_NO_ASC/a_weighted_boss_never_repeats_the_move_the_wiki_forbids |
| byrd.peck | yes | — | ENEMY_DIFF | wiki:wiki_asc/byrd.txt (via byrd) | — | §213/INV_ACTIONS+INV_ASC_VARIANTS |
| byrd.swoop | yes | — | ENEMY_DIFF | wiki:wiki_asc/byrd.txt (via byrd) | — | §213/INV_ACTIONS+INV_ASC_VARIANTS |
| chosen.debilitate | yes | — | ENEMY_DIFF | wiki:wiki_asc/chosen.txt (via chosen) | — | §213/INV_ACTIONS+INV_ASC_VARIANTS |
| chosen.drain | yes | — | ENEMY_DIFF | wiki:wiki_asc/chosen.txt (via chosen) · 仅基础值 | 无升档：wiki Chosen: Drain is 3 Weak + 3 Strength, no A-row | §212/§213/INV_ACTIONS+INV_NO_ASC |
| chosen.hex | yes | chosen_swaps_its_opener_at_a17 | — | wiki:wiki_asc/chosen.txt (via chosen) · 仅基础值 | 无升档：wiki Chosen: Hex applies the Hex debuff, no A-row | §212/§213/INV_ACTIONS+INV_NO_ASC/chosen_swaps_its_opener_at_a17 |
| chosen.poke | yes | chosen_swaps_its_opener_at_a17 | — | wiki:wiki_asc/chosen.txt (via chosen) | — | §213/INV_ACTIONS+INV_ASC_VARIANTS/chosen_swaps_its_opener_at_a17 |
| chosen.zap | yes | — | ENEMY_DIFF | wiki:wiki_asc/chosen.txt (via chosen) | — | §213/INV_ACTIONS+INV_ASC_VARIANTS |
| cultist.dark_strike | yes | — | ENEMY_DIFF | wiki:wiki_asc/cultist.txt (via cultist) · 仅基础值 | 无升档：wiki Cultist: 6 damage, no A-row | INV_ACTIONS+INV_NO_ASC |
| cultist.incantation | yes | — | ENEMY_DIFF | wiki:wiki_asc/cultist.txt (via cultist) | — | INV_ACTIONS+INV_ASC_VARIANTS |
| dagger.explode | yes | a_dagger_that_explodes_removes_itself_and_hands_the_seat_on | — | wiki:wiki_asc/dagger.txt (via dagger) · 仅基础值 | 无升档：wiki Reptomancer: Explode 25, no A-row | §200/INV_ACTIONS+INV_NO_ASC/a_dagger_that_explodes_removes_itself_and_hands_the_seat_on |
| dagger.wound | yes | — | ENEMY_DIFF | wiki:wiki_asc/dagger.txt (via dagger) · 仅基础值 | 无升档：wiki Reptomancer: dagger moves have no A-row | INV_ACTIONS+INV_NO_ASC |
| darkling.chomp | yes | — | ENEMY_DIFF | wiki:wiki_asc/darkling.txt (via darkling) | — | §137/§193/INV_ACTIONS+INV_ASC_VARIANTS |
| darkling.nip | yes | — | ENEMY_DIFF | wiki:wiki_asc/darkling.txt (via darkling) · 仅基础值 | 无升档：wiki Darkling: Nip is rolled at spawn (A2 changes the roll, §193) | §137/§193/INV_ACTIONS+INV_NO_ASC |
| deca.beam | yes | — | ENEMY_DIFF | wiki:wiki_asc/donu_and_deca.txt (via deca) | — | INV_ACTIONS+INV_ASC_VARIANTS |
| deca.square_of_protection | yes | — | ENEMY_DIFF | wiki:wiki_asc/donu_and_deca.txt (via deca) | — | INV_ACTIONS+INV_ASC_VARIANTS |
| donu.beam | yes | — | ENEMY_DIFF | wiki:wiki_asc/donu_and_deca.txt (via donu) | — | INV_ACTIONS+INV_ASC_VARIANTS |
| donu.circle_of_power | yes | donus_circle_of_power_buffs_the_enemy_team_and_not_the_player | — | wiki:wiki_asc/donu_and_deca.txt (via donu) · 仅基础值 | 无升档：wiki Donu and Deca: Circle of Power has no A-row | INV_ACTIONS+INV_NO_ASC/donus_circle_of_power_buffs_the_enemy_team_and_not_the_player |
| fat_gremlin.smash | yes | — | ENEMY_DIFF | wiki:wiki_asc/fat_gremlin.txt (via fat_gremlin) | — | §214/INV_ACTIONS+INV_ASC_VARIANTS |
| fungi_beast.bite | yes | — | ENEMY_DIFF | wiki:wiki_asc/fungi_beast.txt (via fungi_beast) · 仅基础值 | 无升档：wiki Fungi Beast: Bite has no A-row | §258/INV_ACTIONS+INV_NO_ASC |
| fungi_beast.grow | yes | — | ENEMY_DIFF | wiki:wiki_asc/fungi_beast.txt (via fungi_beast) | — | §258/INV_ACTIONS+INV_ASC_VARIANTS |
| giant_head.count | yes | giant_head_counts_down_then_only_its_time | — | wiki:wiki_asc/giant_head.txt (via giant_head) · 仅基础值 | 无升档：wiki Giant Head: Count is flat 13, no A-row；ours 12 伤害 + Weak / 26 伤害 / wiki Weak 1（无伤害）/ 13 —— 本项目是 320 HP 的简化版（§130），招式表跟着简化 | §130/§211/INV_ACTIONS+INV_NO_ASC/giant_head_counts_down_then_only_its_time |
| giant_head.glare | yes | giant_head_counts_down_then_only_its_time | — | wiki:wiki_asc/giant_head.txt (via giant_head) · 仅基础值 | 无升档：wiki Giant Head: Glare applies 1 Weak, no A-row；ours 12 伤害 + Weak / 26 伤害 / wiki Weak 1（无伤害）/ 13 —— 本项目是 320 HP 的简化版（§130），招式表跟着简化 | §130/§211/INV_ACTIONS+INV_NO_ASC/giant_head_counts_down_then_only_its_time |
| giant_head.it_is_time | yes | an_ascension_variant_is_picked_on_the_threshold_and_only_changes_its_number, giant_head_counts_down_then_only_its_time …(+1) | — | wiki:wiki_asc/giant_head.txt (via giant_head) | — | §211/INV_ACTIONS+INV_ASC_VARIANTS/an_ascension_variant_is_picked_on_the_threshold_and_only_changes_its_number |
| gremlin_leader.rally | yes | — | ENEMY_DIFF | wiki:wiki_asc/gremlin_leader.txt (via gremlin_leader) · 仅基础值 | 无升档：wiki rows describe "all enemies" wording; this content is the §130 simplification | §130/§134/INV_ACTIONS+INV_NO_ASC |
| gremlin_leader.slash | yes | — | ENEMY_DIFF | wiki:wiki_asc/gremlin_leader.txt (via gremlin_leader) · 仅基础值 | 无升档：wiki Gremlin Leader: Slash is 6x3, no A-row | §130/§134/INV_ACTIONS+INV_NO_ASC |
| gremlin_leader.summon | yes | the_summon_cap_is_a_loud_failure | — | wiki:wiki_asc/gremlin_leader.txt (via gremlin_leader) · 仅基础值 | 无升档：wiki Gremlin Leader: Summon has no numbers | §134/INV_ACTIONS+INV_NO_ASC/the_summon_cap_is_a_loud_failure |
| gremlin_nob.bellow | yes | — | ENEMY_DIFF | wiki:wiki_asc/gremlin_nob.txt (via gremlin_nob) | — | §186/INV_ACTIONS+INV_ASC_VARIANTS |
| gremlin_nob.rush | yes | — | ENEMY_DIFF | wiki:wiki_asc/gremlin_nob.txt (via gremlin_nob) | — | §186/INV_ACTIONS+INV_ASC_VARIANTS |
| gremlin_nob.skull_bash | yes | — | ENEMY_DIFF | wiki:wiki_asc/gremlin_nob.txt (via gremlin_nob) | — | INV_ACTIONS+INV_ASC_VARIANTS |
| gremlin_wizard.charging | yes | — | ENEMY_DIFF | wiki:wiki_asc/gremlin_wizard.txt (via gremlin_wizard) · 仅基础值 | 无升档：wiki Gremlin Wizard: Charging has no numbers | §0/INV_ACTIONS+INV_NO_ASC |
| gremlin_wizard.ultimate_blast | yes | — | ENEMY_DIFF | wiki:wiki_asc/gremlin_wizard.txt (via gremlin_wizard) | — | INV_ACTIONS+INV_ASC_VARIANTS |
| hexaghost.activate | yes | hexaghost_plays_the_wikis_seven_move_pattern_after_its_two_openers | — | wiki:wiki_asc/hexaghost.txt (via hexaghost) · 仅基础值 | 无升档：wiki Hexaghost: Activate has no numbers | INV_ACTIONS+INV_NO_ASC/hexaghost_plays_the_wikis_seven_move_pattern_after_its_two_openers |
| hexaghost.divider | yes | hexaghosts_divider_repeats_ceil_of_hp_over_twelve_plus_one, hexaghost_plays_the_wikis_seven_move_pattern_after_its_two_openers | — | wiki:wiki_asc/hexaghost.txt (via hexaghost) · 仅基础值 | 无升档：wiki Hexaghost: Divider has no A-row | INV_ACTIONS+INV_NO_ASC/hexaghosts_divider_repeats_ceil_of_hp_over_twelve_plus_one |
| hexaghost.inferno | yes | upgrading_burns_walks_every_pile_and_skips_cards_without_an_upgrade, hexaghost_plays_the_wikis_seven_move_pattern_after_its_two_openers | — | wiki:wiki_asc/hexaghost.txt (via hexaghost) | — | §195.7/INV_ACTIONS+INV_ASC_VARIANTS/upgrading_burns_walks_every_pile_and_skips_cards_without_an_upgrade |
| hexaghost.inflame | yes | hexaghost_plays_the_wikis_seven_move_pattern_after_its_two_openers | — | wiki:wiki_asc/hexaghost.txt (via hexaghost) | — | INV_ACTIONS+INV_ASC_VARIANTS/hexaghost_plays_the_wikis_seven_move_pattern_after_its_two_openers |
| hexaghost.sear | yes | hexaghost_plays_the_wikis_seven_move_pattern_after_its_two_openers | — | wiki:wiki_asc/hexaghost.txt (via hexaghost) | — | INV_ACTIONS+INV_ASC_VARIANTS/hexaghost_plays_the_wikis_seven_move_pattern_after_its_two_openers |
| hexaghost.tackle | yes | hexaghost_plays_the_wikis_seven_move_pattern_after_its_two_openers | — | wiki:wiki_asc/hexaghost.txt (via hexaghost) | — | INV_ACTIONS+INV_ASC_VARIANTS/hexaghost_plays_the_wikis_seven_move_pattern_after_its_two_openers |
| jaw_worm.bellow | yes | one_action_can_carry_two_ascension_tiers, a_round_one_rule_beats_the_cycle_and_the_cycle_takes_over_after_it | — | wiki:wiki_asc/jaw_worm.txt (via jaw_worm) | — | INV_ACTIONS+INV_ASC_VARIANTS/one_action_can_carry_two_ascension_tiers |
| jaw_worm.chomp | yes | a_round_one_rule_beats_the_cycle_and_the_cycle_takes_over_after_it | — | wiki:wiki_asc/jaw_worm.txt (via jaw_worm) | — | INV_ACTIONS+INV_ASC_VARIANTS/a_round_one_rule_beats_the_cycle_and_the_cycle_takes_over_after_it |
| jaw_worm.thrash | yes | a_round_one_rule_beats_the_cycle_and_the_cycle_takes_over_after_it | — | wiki:wiki_asc/jaw_worm.txt (via jaw_worm) · 仅基础值 | 无升档：wiki Jaw Worm: Thrash has no A-row | INV_ACTIONS+INV_NO_ASC/a_round_one_rule_beats_the_cycle_and_the_cycle_takes_over_after_it |
| lagavulin.attack | yes | an_ascension_variant_replaces_the_program_at_its_threshold, lagavulin_wakes_when_it_loses_health_and_loses_a_turn …(+1) | — | wiki:wiki_asc/lagavulin.txt (via lagavulin) | — | §173/§257/INV_ACTIONS+INV_ASC_VARIANTS/an_ascension_variant_replaces_the_program_at_its_threshold |
| lagavulin.siphon_soul | yes | an_ascension_variant_is_picked_on_the_threshold_and_only_changes_its_number, lagavulin_wakes_on_its_own_unstunned_and_cycles_attack_attack_siphon | — | wiki:wiki_asc/lagavulin.txt (via lagavulin) | — | §174/§204/INV_ACTIONS+INV_ASC_VARIANTS/an_ascension_variant_is_picked_on_the_threshold_and_only_changes_its_number |
| lagavulin.sleep | yes | lagavulin_wakes_when_it_loses_health_and_loses_a_turn, lagavulin_wakes_on_its_own_unstunned_and_cycles_attack_attack_siphon | — | wiki:wiki_asc/lagavulin.txt (via lagavulin) · 仅基础值 | 无升档：wiki Lagavulin: Sleep does nothing | §173/§193/INV_ACTIONS+INV_NO_ASC/lagavulin_wakes_when_it_loses_health_and_loses_a_turn |
| lagavulin.stunned | yes | lagavulin_wakes_when_it_loses_health_and_loses_a_turn | — | wiki:wiki_asc/lagavulin.txt (via lagavulin) · 仅基础值 | 无升档：wiki Lagavulin: Stunned does nothing (a lost turn, no numbers) | §173/§257/INV_ACTIONS+INV_NO_ASC/lagavulin_wakes_when_it_loses_health_and_loses_a_turn |
| looter.escape | yes | a_looter_steals_thievery_gold_on_every_attack_and_carries_it_away, escaping_moves_the_counter_instead_of_copying_it …(+1) | — | wiki:wiki_asc/thieves.txt (via looter) · 仅基础值 | 无升档：wiki Thieves: Escape has no numbers | §201/INV_ACTIONS+INV_NO_ASC/a_looter_steals_thievery_gold_on_every_attack_and_carries_it_away |
| looter.lunge | yes | an_ascension_variant_is_picked_on_the_threshold_and_only_changes_its_number, the_looter_mugs_twice_then_bombs_then_escapes | — | wiki:wiki_asc/thieves.txt (via looter) | — | §201/INV_ACTIONS+INV_ASC_VARIANTS/an_ascension_variant_is_picked_on_the_threshold_and_only_changes_its_number |
| looter.mug | yes | ascension_two_makes_the_looter_mug_hit_for_eleven, a_looter_steals_thievery_gold_on_every_attack_and_carries_it_away …(+3) | — | wiki:wiki_asc/thieves.txt (via looter) | — | §201/§205/INV_ACTIONS+INV_ASC_VARIANTS/ascension_two_makes_the_looter_mug_hit_for_eleven |
| looter.smoke_bomb | yes | the_looter_mugs_twice_then_bombs_then_escapes | — | wiki:wiki_asc/thieves.txt (via looter) · 仅基础值 | 无升档：wiki Thieves: 6 Block, no A-row | §201/INV_ACTIONS+INV_NO_ASC/the_looter_mugs_twice_then_bombs_then_escapes |
| louse_green.bite | yes | louse_bites_are_rolled_at_spawn_and_the_green_one_reads_its_roll, the_two_louses_have_the_moves_the_wiki_gives_them | — | wiki:wiki_asc/louses.txt (via louse_green) · 仅基础值 | 无升档：wiki Louses: Bite is rolled at spawn (A2 changes the roll, §193) | §193/§258/INV_ACTIONS+INV_NO_ASC/louse_bites_are_rolled_at_spawn_and_the_green_one_reads_its_roll |
| louse_green.spit_web | yes | the_two_louses_have_the_moves_the_wiki_gives_them | — | wiki:wiki_asc/louses.txt (via louse_green) · 仅基础值 | 无升档：wiki Green Louse: Spit Web is 2 Weak, no A-row | §193/§258/INV_ACTIONS+INV_NO_ASC/the_two_louses_have_the_moves_the_wiki_gives_them |
| louse_red.bite | yes | a_spawn_roll_is_drawn_once_per_fight_and_read_by_the_action, the_two_louses_have_the_moves_the_wiki_gives_them | — | wiki:wiki_asc/louses.txt (via louse_red) · 仅基础值 | 无升档：wiki Louses: Bite is rolled at spawn (A2 changes the roll, §193) | §193/§258/INV_ACTIONS+INV_NO_ASC/a_spawn_roll_is_drawn_once_per_fight_and_read_by_the_action |
| louse_red.grow | yes | the_two_louses_have_the_moves_the_wiki_gives_them | — | wiki:wiki_asc/louses.txt (via louse_red) | — | §193/§258/INV_ACTIONS+INV_ASC_VARIANTS/the_two_louses_have_the_moves_the_wiki_gives_them |
| maw.drool | yes | the_maw_follows_the_wikis_transition_table | — | wiki:wiki_asc/the_maw.txt (via maw) | — | §137/§212/INV_ACTIONS+INV_ASC_VARIANTS/the_maw_follows_the_wikis_transition_table |
| maw.nom_nom | yes | nom_nom_hits_five_damage_ceil_round_over_two_times, the_maw_follows_the_wikis_transition_table | — | wiki:wiki_asc/the_maw.txt (via maw) · 仅基础值 | 无升档：wiki The Maw: Nom Nom is 5 x ceil(turn/2), no A-row | §137/§212/INV_ACTIONS+INV_NO_ASC/nom_nom_hits_five_damage_ceil_round_over_two_times |
| maw.roar | yes | the_maw_follows_the_wikis_transition_table | — | wiki:wiki_asc/the_maw.txt (via maw) | — | §137/§212/INV_ACTIONS+INV_ASC_VARIANTS/the_maw_follows_the_wikis_transition_table |
| maw.slam | yes | the_maw_follows_the_wikis_transition_table | — | wiki:wiki_asc/the_maw.txt (via maw) | — | §137/§212/INV_ACTIONS+INV_ASC_VARIANTS/the_maw_follows_the_wikis_transition_table |
| nemesis.scythe | yes | nemesis_never_repeats_burn_or_scythe_and_never_triple_attacks | — | wiki:wiki_asc/nemesis.txt (via nemesis) · 仅基础值 | 无升档：wiki Nemesis: Scythe has no A-row | §175/INV_ACTIONS+INV_NO_ASC/nemesis_never_repeats_burn_or_scythe_and_never_triple_attacks |
| nemesis.tri_attack | yes | nemesis_never_repeats_burn_or_scythe_and_never_triple_attacks | — | wiki:wiki_asc/nemesis.txt (via nemesis) | — | §175/§257/INV_ACTIONS+INV_ASC_VARIANTS/nemesis_never_repeats_burn_or_scythe_and_never_triple_attacks |
| nemesis.tri_burn | yes | nemesis_never_repeats_burn_or_scythe_and_never_triple_attacks | — | wiki:wiki_asc/nemesis.txt (via nemesis) | — | §175/INV_ACTIONS+INV_ASC_VARIANTS/nemesis_never_repeats_burn_or_scythe_and_never_triple_attacks |
| orb_walker.claw | yes | — | ENEMY_DIFF | wiki:wiki_asc/orb_walker.txt (via orb_walker) | — | §214/INV_ACTIONS+INV_ASC_VARIANTS |
| orb_walker.laser | yes | — | ENEMY_DIFF | wiki:wiki_asc/orb_walker.txt (via orb_walker) | — | §214/INV_ACTIONS+INV_ASC_VARIANTS |
| reptomancer.big_bite | yes | — | ENEMY_DIFF | wiki:wiki_asc/reptomancer.txt (via reptomancer) | — | §175/INV_ACTIONS+INV_ASC_VARIANTS |
| reptomancer.snake_strike | yes | reptomancer_switches_to_snake_strike_when_four_daggers_are_out | — | wiki:wiki_asc/reptomancer.txt (via reptomancer) | — | §175/INV_ACTIONS+INV_ASC_VARIANTS/reptomancer_switches_to_snake_strike_when_four_daggers_are_out |
| reptomancer.spawn_dagger | yes | reptomancer_switches_to_snake_strike_when_four_daggers_are_out, reptomancer_spawns_two_daggers_at_a18_only | — | wiki:wiki_asc/reptomancer.txt (via reptomancer) | — | §175/INV_ACTIONS+INV_ASC_VARIANTS/reptomancer_switches_to_snake_strike_when_four_daggers_are_out |
| sentry.beam | yes | — | ENEMY_DIFF | wiki:wiki_asc/sentry.txt (via sentry_1) | — | §4.2/INV_ACTIONS+INV_ASC_VARIANTS |
| sentry.bolt | yes | — | ENEMY_DIFF | wiki:wiki_asc/sentry.txt (via sentry_1) | — | §4.2/INV_ACTIONS+INV_ASC_VARIANTS |
| shelled_parasite.double_strike | yes | — | ENEMY_DIFF | wiki:wiki_asc/shelled_parasite.txt (via shelled_parasite) | — | §130/INV_ACTIONS+INV_ASC_VARIANTS |
| shelled_parasite.suck | yes | — | ENEMY_DIFF | wiki:wiki_asc/shelled_parasite.txt (via shelled_parasite) | — | §130/INV_ACTIONS+INV_ASC_VARIANTS |
| slaver_red.entangle | yes | — | ENEMY_DIFF | wiki:wiki_asc/slavers.txt (via slaver_red) · 仅基础值 | 无升档：wiki Slavers: Entangle applies a status, no A-row | §196/INV_ACTIONS+INV_NO_ASC |
| slaver_red.scrape | yes | slaver_red_scrape_applies_two_vulnerable_from_a17 | — | wiki:wiki_asc/slavers.txt (via slaver_red) | — | §186/§187/INV_ACTIONS+INV_ASC_VARIANTS/slaver_red_scrape_applies_two_vulnerable_from_a17 |
| slaver_red.stab | yes | — | ENEMY_DIFF | wiki:wiki_asc/slavers.txt (via slaver_red) | — | §196/INV_ACTIONS+INV_ASC_VARIANTS |
| slime_boss.goop_spray | yes | — | ENEMY_DIFF | wiki:wiki_asc/slime_boss.txt (via slime_boss) | — | §4.3/INV_ACTIONS+INV_ASC_VARIANTS |
| slime_boss.preparing | yes | — | ENEMY_DIFF | wiki:wiki_asc/slime_boss.txt (via slime_boss) · 仅基础值 | 无升档：wiki Slime Boss: Preparing has no numbers | §4.3/INV_ACTIONS+INV_NO_ASC |
| slime_boss.slam | yes | a_combinator_rule_switches_the_boss_move | — | wiki:wiki_asc/slime_boss.txt (via slime_boss) | — | §4.3/INV_ACTIONS+INV_ASC_VARIANTS/a_combinator_rule_switches_the_boss_move |
| sneaky_gremlin.puncture | yes | — | ENEMY_DIFF | wiki:wiki_asc/sneaky_gremlin.txt (via sneaky_gremlin) | — | INV_ACTIONS+INV_ASC_VARIANTS |
| spike_slime_l.flame_tackle | yes | — | ENEMY_DIFF | wiki:wiki_asc/spike_slime.txt (via spike_slime_l) | — | §192/§276/INV_ACTIONS+INV_ASC_VARIANTS |
| spike_slime_l.lick | yes | — | ENEMY_DIFF | wiki:wiki_asc/spike_slime.txt (via spike_slime_l) | — | §276/INV_ACTIONS+INV_ASC_VARIANTS |
| spike_slime_m.flame_tackle | yes | — | ENEMY_DIFF | wiki:wiki_asc/spike_slime.txt (via spike_slime_m) | — | INV_ACTIONS+INV_ASC_VARIANTS |
| spike_slime_m.lick | yes | — | ENEMY_DIFF | wiki:wiki_asc/spike_slime.txt (via spike_slime_m) · 仅基础值 | 无升档：wiki Spike Slime: M Lick is 1 Frail, no A-row (only L has A17) | INV_ACTIONS+INV_NO_ASC |
| spike_slime_s.tackle | yes | — | ENEMY_DIFF | wiki:wiki_asc/spike_slime.txt (via spike_slime_s) | — | INV_ACTIONS+INV_ASC_VARIANTS |
| spiker.cut | yes | spiker_never_repeats_its_attack_and_buffs_thorns_at_most_six_times | — | wiki:wiki_asc/shapes.txt (via spiker) | — | §214/INV_ACTIONS+INV_ASC_VARIANTS/spiker_never_repeats_its_attack_and_buffs_thorns_at_most_six_times |
| spiker.spike | yes | spiker_never_repeats_its_attack_and_buffs_thorns_at_most_six_times | — | wiki:wiki_asc/shapes.txt (via spiker) · 仅基础值 | 无升档：wiki Shapes#Spiker: Buff Thorns is always +2 Thorns, no A-row | §214/INV_ACTIONS+INV_NO_ASC/spiker_never_repeats_its_attack_and_buffs_thorns_at_most_six_times |
| spire_growth.aggressive | yes | — | ENEMY_DIFF | wiki:wiki_asc/spire_growth.txt (via spire_growth) | — | §147/§214/INV_ACTIONS+INV_ASC_VARIANTS |
| spire_growth.aggressive_heavy | yes | spire_growth_smashes_instead_of_choosing | — | wiki:wiki_asc/spire_growth.txt (via spire_growth) | — | §147/§214/INV_ACTIONS+INV_ASC_VARIANTS/spire_growth_smashes_instead_of_choosing |
| spire_growth.strategic | yes | — | ENEMY_DIFF | wiki:wiki_asc/spire_growth.txt (via spire_growth) | — | §147/§214/INV_ACTIONS+INV_ASC_VARIANTS |
| taskmaster.scouring_whip | yes | — | ENEMY_DIFF | wiki:wiki_asc/taskmaster.txt (via taskmaster) | — | INV_ACTIONS+INV_ASC_VARIANTS |
| the_champ.anger | yes | the_champ_taunts_every_fourth_round_and_enters_phase_two_below_half | — | wiki:wiki_asc/the_champ.txt (via the_champ) | — | INV_ACTIONS+INV_ASC_VARIANTS/the_champ_taunts_every_fourth_round_and_enters_phase_two_below_half |
| the_champ.defensive_stance | yes | the_champ_swaps_gloat_for_defensive_stance_at_a19 | — | wiki:wiki_asc/the_champ.txt (via the_champ) | — | §194/INV_ACTIONS+INV_ASC_VARIANTS/the_champ_swaps_gloat_for_defensive_stance_at_a19 |
| the_champ.execute | yes | the_champ_taunts_every_fourth_round_and_enters_phase_two_below_half | — | wiki:wiki_asc/the_champ.txt (via the_champ) · 仅基础值 | 无升档：wiki The Champ: Execute is 10x2, no A-row | §194/INV_ACTIONS+INV_NO_ASC/the_champ_taunts_every_fourth_round_and_enters_phase_two_below_half |
| the_champ.face_slap | yes | — | ENEMY_DIFF | wiki:wiki_asc/the_champ.txt (via the_champ) | — | INV_ACTIONS+INV_ASC_VARIANTS |
| the_champ.gloat | yes | the_champ_swaps_gloat_for_defensive_stance_at_a19 | — | wiki:wiki_asc/the_champ.txt (via the_champ) | — | INV_ACTIONS+INV_ASC_VARIANTS/the_champ_swaps_gloat_for_defensive_stance_at_a19 |
| the_champ.heavy_slash | yes | a_weighted_boss_never_repeats_the_move_the_wiki_forbids, the_champ_taunts_every_fourth_round_and_enters_phase_two_below_half | — | wiki:wiki_asc/the_champ.txt (via the_champ) | — | INV_ACTIONS+INV_ASC_VARIANTS/a_weighted_boss_never_repeats_the_move_the_wiki_forbids |
| the_champ.taunt | yes | the_champ_taunts_every_fourth_round_and_enters_phase_two_below_half | — | wiki:wiki_asc/the_champ.txt (via the_champ) · 仅基础值 | 无升档：wiki The Champ: Taunt has no A-row | INV_ACTIONS+INV_NO_ASC/the_champ_taunts_every_fourth_round_and_enters_phase_two_below_half |
| the_collector.buff | yes | the_collector_draws_by_weight_and_never_buffs_twice_in_a_row | — | wiki:wiki_asc/the_collector.txt (via the_collector) | — | INV_ACTIONS+INV_ASC_VARIANTS/the_collector_draws_by_weight_and_never_buffs_twice_in_a_row |
| the_collector.fireball | yes | the_collector_draws_by_weight_and_never_buffs_twice_in_a_row | — | wiki:wiki_asc/the_collector.txt (via the_collector) | — | §195.3/INV_ACTIONS+INV_ASC_VARIANTS/the_collector_draws_by_weight_and_never_buffs_twice_in_a_row |
| the_collector.mega_debuff | yes | — | ENEMY_DIFF | wiki:wiki_asc/the_collector.txt (via the_collector) | — | INV_ACTIONS+INV_ASC_VARIANTS |
| the_collector.spawn | yes | a_minion_is_not_on_the_field_until_its_summon_lands | — | wiki:wiki_asc/the_collector.txt (via the_collector) · 仅基础值 | 无升档：wiki The Collector: Spawn has no numbers | §195.3/INV_ACTIONS+INV_NO_ASC/a_minion_is_not_on_the_field_until_its_summon_lands |
| the_guardian.charging_up | yes | — | ENEMY_DIFF | wiki:wiki_asc/the_guardian.txt (via the_guardian) · 仅基础值 | 无升档：wiki The Guardian: Mode Shift moves, no A-row on the move itself | §194/INV_ACTIONS+INV_NO_ASC |
| the_guardian.defensive_mode | yes | mode_shift_is_a_budget_drained_by_the_health_actually_lost | — | wiki:wiki_asc/the_guardian.txt (via the_guardian) | — | §195.1/INV_ACTIONS+INV_ASC_VARIANTS/mode_shift_is_a_budget_drained_by_the_health_actually_lost |
| the_guardian.fierce_bash | yes | — | ENEMY_DIFF | wiki:wiki_asc/the_guardian.txt (via the_guardian) | — | §194/INV_ACTIONS+INV_ASC_VARIANTS |
| the_guardian.roll_attack | yes | — | ENEMY_DIFF | wiki:wiki_asc/the_guardian.txt (via the_guardian) | — | §194/INV_ACTIONS+INV_ASC_VARIANTS |
| the_guardian.twin_slam | yes | sharp_hide_hurts_the_player_for_attacks_and_only_attacks | — | wiki:wiki_asc/the_guardian.txt (via the_guardian) · 仅基础值 | 无升档：wiki The Guardian: no A-row | INV_ACTIONS+INV_NO_ASC/sharp_hide_hurts_the_player_for_attacks_and_only_attacks |
| the_guardian.vent_steam | yes | — | ENEMY_DIFF | wiki:wiki_asc/the_guardian.txt (via the_guardian) · 仅基础值 | 无升档：wiki The Guardian: Vent Steam has no A-row | §194/INV_ACTIONS+INV_NO_ASC |
| the_guardian.whirlwind | yes | — | ENEMY_DIFF | wiki:wiki_asc/the_guardian.txt (via the_guardian) · 仅基础值 | 无升档：wiki The Guardian: no A-row | §194/INV_ACTIONS+INV_NO_ASC |
| time_eater.haste | yes | — | ENEMY_DIFF | wiki:wiki_asc/time_eater.txt (via time_eater) | — | §194/INV_ACTIONS+INV_ASC_VARIANTS |
| time_eater.head_slam | yes | a_weighted_boss_never_repeats_the_move_the_wiki_forbids, time_eater_head_slam_reaches_32_at_a4 | — | wiki:wiki_asc/time_eater.txt (via time_eater) | — | §195.7/INV_ACTIONS+INV_ASC_VARIANTS/a_weighted_boss_never_repeats_the_move_the_wiki_forbids |
| time_eater.reverberate | yes | a_weighted_boss_never_repeats_the_move_the_wiki_forbids | — | wiki:wiki_asc/time_eater.txt (via time_eater) | — | §194/INV_ACTIONS+INV_ASC_VARIANTS/a_weighted_boss_never_repeats_the_move_the_wiki_forbids |
| time_eater.ripple | yes | a_weighted_boss_never_repeats_the_move_the_wiki_forbids | — | wiki:wiki_asc/time_eater.txt (via time_eater) | — | §195.7/INV_ACTIONS+INV_ASC_VARIANTS/a_weighted_boss_never_repeats_the_move_the_wiki_forbids |
| torch_head.tackle | yes | — | ENEMY_DIFF | wiki:wiki_asc/torch_head.txt (via torch_head) · 仅基础值 | 无升档：wiki Torch Head: Tackle is 7, no A-row | INV_ACTIONS+INV_NO_ASC |

## 卡牌（293）

| Entity | Implemented | TestNamed | HarnessOnly | SourceTie | DeclaredDeviation | Evidence |
|---|---|---|---|---|---|---|
| anger | yes | warcry_draws_one_then_puts_the_chosen_card_on_top, perfected_strike_counts_the_tagged_cards_in_hand …(+11) | — | wiki:wiki_cards/anger.txt | — | CARD_WIKI+INV_CARDS/warcry_draws_one_then_puts_the_chosen_card_on_top |
| anger+ | yes | the_upgrade_eggs_upgrade_two_of_their_own_kind | — | wiki:wiki_cards/anger.txt (via anger) | — | INV_CARDS/the_upgrade_eggs_upgrade_two_of_their_own_kind |
| apotheosis | yes | — | CARD_DIFF | wiki:wiki_cards/apotheosis.txt | — | §245/CARD_WIKI+INV_CARDS |
| apotheosis+ | yes | — | CARD_DIFF | wiki:wiki_cards/apotheosis.txt (via apotheosis) | — | INV_CARDS |
| apparition | yes | a_special_card_is_known_and_never_put_in_a_reward | — | wiki:wiki_cards/apparition.txt | — | §149/§223/CARD_WIKI+INV_CARDS/a_special_card_is_known_and_never_put_in_a_reward |
| apparition+ | yes | — | CARD_DIFF | wiki:wiki_cards/apparition.txt (via apparition) | — | INV_CARDS |
| armaments | yes | armaments_gains_block_then_upgrades_the_chosen_card, an_armaments_question_makes_the_page_layer_modal | — | wiki:wiki_cards/armaments.txt | — | §227/CARD_WIKI+INV_CARDS/armaments_gains_block_then_upgrades_the_chosen_card |
| armaments+ | yes | armaments_gains_block_then_upgrades_the_chosen_card | — | wiki:wiki_cards/armaments.txt (via armaments) | — | INV_CARDS/armaments_gains_block_then_upgrades_the_chosen_card |
| ascenders_bane | yes | — | CARD_DIFF | wiki:wiki_cards/ascenders_bane.txt | — | §183/§189/CARD_WIKI+INV_CARDS |
| bandage_up | yes | exhaust_on_play_is_a_zone_and_the_cards_that_use_it_are_playable | — | wiki:wiki_cards/bandage_up.txt | wiki 偏差：wiki 升级版治疗 6；内容没有 `bandage_up+` 这一行。（`Exhaust` 本身不是偏差：§219 起它由落区 `PlayedCardDestinationZone` 表达。） | §191/CARD_WIKI+INV_CARDS/exhaust_on_play_is_a_zone_and_the_cards_that_use_it_are_playable |
| barricade | yes | — | CARD_DIFF | wiki:wiki_cards/barricade.txt | — | CARD_WIKI+INV_CARDS |
| barricade+ | yes | — | CARD_DIFF | wiki:wiki_cards/barricade.txt (via barricade) | — | INV_CARDS |
| bash | yes | card_rarity_is_readable_and_the_schema_moved_the_version, warcry_draws_one_then_puts_the_chosen_card_on_top …(+19) | — | wiki:wiki_cards/bash.txt | — | §2/§2.1/CARD_WIKI+INV_CARDS/card_rarity_is_readable_and_the_schema_moved_the_version |
| bash+ | yes | the_upgrade_eggs_upgrade_two_of_their_own_kind, pandoras_box_transforms_every_staple_and_nothing_else …(+2) | — | wiki:wiki_cards/bash.txt (via bash) | — | INV_CARDS/the_upgrade_eggs_upgrade_two_of_their_own_kind |
| battle_trance | yes | battle_trance_blocks_further_draws_only_this_turn, the_ten_cards_added_in_221_do_what_the_wiki_says | — | wiki:wiki_cards/battle_trance.txt | — | CARD_WIKI+INV_CARDS/battle_trance_blocks_further_draws_only_this_turn |
| battle_trance+ | yes | — | CARD_DIFF | wiki:wiki_cards/battle_trance.txt (via battle_trance) | — | INV_CARDS |
| become_almighty | yes | the_wish_options_are_unplayable_by_hand, play_card_from_program_respects_unplayable_unless_told_otherwise …(+1) | — | wiki:wiki_cards/become_almighty.txt | — | §254/§255/CARD_WIKI+INV_CARDS/the_wish_options_are_unplayable_by_hand |
| become_almighty+ | yes | wish_plus_offers_the_upgraded_options | — | wiki:wiki_cards/become_almighty.txt (via become_almighty) | — | INV_CARDS/wish_plus_offers_the_upgraded_options |
| berserk | yes | — | CARD_DIFF | wiki:wiki_cards/berserk.txt | — | §197/§199/CARD_WIKI+INV_CARDS |
| berserk+ | yes | — | CARD_DIFF | wiki:wiki_cards/berserk.txt (via berserk) | — | INV_CARDS |
| beta | yes | — | CARD_DIFF | wiki:wiki_cards/beta.txt | — | CARD_WIKI+INV_CARDS |
| beta+ | yes | beta_shuffles_an_omega_into_the_draw_pile | — | wiki:wiki_cards/beta.txt (via beta) | — | INV_CARDS/beta_shuffles_an_omega_into_the_draw_pile |
| bite | yes | bite_deals_its_damage_and_heals_a_fixed_amount, louse_bites_are_rolled_at_spawn_and_the_green_one_reads_its_roll | — | wiki:wiki_cards/bite.txt | — | §251/CARD_WIKI+INV_CARDS/bite_deals_its_damage_and_heals_a_fixed_amount |
| bite+ | yes | bite_deals_its_damage_and_heals_a_fixed_amount | — | wiki:wiki_cards/bite.txt (via bite) | — | INV_CARDS/bite_deals_its_damage_and_heals_a_fixed_amount |
| blind | yes | — | CARD_DIFF | wiki:wiki_cards/blind.txt | — | CARD_WIKI+INV_CARDS |
| blood_for_blood | yes | blood_for_blood_gets_cheaper_each_time_you_lose_hp | — | wiki:wiki_cards/blood_for_blood.txt | — | CARD_WIKI+INV_CARDS/blood_for_blood_gets_cheaper_each_time_you_lose_hp |
| blood_for_blood+ | yes | — | CARD_DIFF | wiki:wiki_cards/blood_for_blood.txt (via blood_for_blood) | — | INV_CARDS |
| bloodletting | yes | blood_for_blood_gets_cheaper_each_time_you_lose_hp, losing_hp_is_not_damage_but_it_is_hp_loss …(+2) | — | wiki:wiki_cards/bloodletting.txt | — | §236/CARD_WIKI+INV_CARDS/blood_for_blood_gets_cheaper_each_time_you_lose_hp |
| bloodletting+ | yes | the_lose_hp_cards_do_what_their_pages_say | — | wiki:wiki_cards/bloodletting.txt (via bloodletting) | — | INV_CARDS/the_lose_hp_cards_do_what_their_pages_say |
| bludgeon | yes | enlightenment_caps_hand_costs_at_one, the_ten_cards_added_in_221_do_what_the_wiki_says …(+1) | — | wiki:wiki_cards/bludgeon.txt | — | CARD_WIKI+INV_CARDS/enlightenment_caps_hand_costs_at_one |
| bludgeon+ | yes | — | CARD_DIFF | wiki:wiki_cards/bludgeon.txt (via bludgeon) | — | INV_CARDS |
| blur | yes | blur_gives_five_or_eight_block_and_the_status, a_special_card_is_known_and_never_put_in_a_reward | — | wiki:wiki_cards/blur.txt | — | §218/CARD_WIKI+INV_CARDS/blur_gives_five_or_eight_block_and_the_status |
| blur+ | yes | blur_gives_five_or_eight_block_and_the_status | — | wiki:wiki_cards/blur.txt (via blur) | — | INV_CARDS/blur_gives_five_or_eight_block_and_the_status |
| body_slam | yes | body_slam_deals_damage_equal_to_the_block_it_has_when_played | — | wiki:wiki_cards/body_slam.txt | — | CARD_WIKI+INV_CARDS/body_slam_deals_damage_equal_to_the_block_it_has_when_played |
| body_slam+ | yes | — | CARD_DIFF | wiki:wiki_cards/body_slam.txt (via body_slam) | — | INV_CARDS |
| brutality | yes | the_lose_hp_cards_do_what_their_pages_say | — | wiki:wiki_cards/brutality.txt | wiki 偏差：wiki 的 Innate 在 `(基础;升级)` 括号里 ⇒ 只有 brutality+ 是 Innate。 | CARD_WIKI+INV_CARDS/the_lose_hp_cards_do_what_their_pages_say |
| brutality+ | yes | — | CARD_DIFF | wiki:wiki_cards/brutality.txt (via brutality) | wiki 偏差：wiki 的 Innate 在 `(基础;升级)` 括号里 ⇒ 只有 brutality+ 是 Innate。 | INV_CARDS |
| buffer | yes | — | CARD_DIFF | wiki:wiki_cards/buffer.txt | — | §223/CARD_WIKI+INV_CARDS |
| buffer+ | yes | — | CARD_DIFF | wiki:wiki_cards/buffer.txt (via buffer) | — | INV_CARDS |
| burn | yes | upgrading_burns_walks_every_pile_and_skips_cards_without_an_upgrade, the_new_red_attacks_do_what_their_pages_say | — | wiki:wiki_cards/burn.txt | wiki 偏差：wiki 升级版是"回合末受 4 点伤害"，内容只有基础版（`burn+` 那一行没有生命周期）。 | §175/CARD_WIKI+INV_CARDS/upgrading_burns_walks_every_pile_and_skips_cards_without_an_upgrade |
| burn+ | yes | upgrading_burns_walks_every_pile_and_skips_cards_without_an_upgrade | — | wiki:wiki_cards/burn.txt (via burn) | wiki 偏差：wiki 升级版是"回合末受 4 点伤害"，内容只有基础版（`burn+` 那一行没有生命周期）。 | INV_CARDS/upgrading_burns_walks_every_pile_and_skips_cards_without_an_upgrade |
| burning_pact | yes | burning_pact_exhausts_a_card_and_draws | — | wiki:wiki_cards/burning_pact.txt | wiki 偏差：wiki 的 {{KW\|Exhaust}} 是动词（消耗选中的一张牌），不是本牌的关键字；牌本身打完进弃牌堆。 | §239/CARD_WIKI+INV_CARDS/burning_pact_exhausts_a_card_and_draws |
| burning_pact+ | yes | — | CARD_DIFF | wiki:wiki_cards/burning_pact.txt (via burning_pact) | wiki 偏差：wiki 的 {{KW\|Exhaust}} 是动词（消耗选中的一张牌），不是本牌的关键字；牌本身打完进弃牌堆。 | INV_CARDS |
| carnage | yes | the_new_red_attacks_do_what_their_pages_say, exhausting_a_card_feeds_feel_no_pain_and_dark_embrace | — | wiki:wiki_cards/carnage.txt | — | §235/CARD_WIKI+INV_CARDS/the_new_red_attacks_do_what_their_pages_say |
| carnage+ | yes | the_new_red_attacks_do_what_their_pages_say | — | wiki:wiki_cards/carnage.txt (via carnage) | — | INV_CARDS/the_new_red_attacks_do_what_their_pages_say |
| chrysalis | yes | — | CARD_DIFF | wiki:wiki_cards/chrysalis.txt | — | CARD_WIKI+INV_CARDS |
| chrysalis+ | yes | — | CARD_DIFF | wiki:wiki_cards/chrysalis.txt (via chrysalis) | — | INV_CARDS |
| clash | yes | clash_refuses_unless_every_card_in_hand_is_an_attack, the_upgrade_eggs_upgrade_two_of_their_own_kind …(+3) | — | wiki:wiki_cards/clash.txt | — | §239/CARD_WIKI+INV_CARDS/clash_refuses_unless_every_card_in_hand_is_an_attack |
| clash+ | yes | clash_refuses_unless_every_card_in_hand_is_an_attack, the_upgrade_eggs_upgrade_two_of_their_own_kind | — | wiki:wiki_cards/clash.txt (via clash) | — | INV_CARDS/clash_refuses_unless_every_card_in_hand_is_an_attack |
| cleave | yes | the_ten_cards_added_in_221_do_what_the_wiki_says | — | wiki:wiki_cards/cleave.txt | — | §221/CARD_WIKI+INV_CARDS/the_ten_cards_added_in_221_do_what_the_wiki_says |
| cleave+ | yes | — | CARD_DIFF | wiki:wiki_cards/cleave.txt (via cleave) | — | INV_CARDS |
| clothesline | yes | — | CARD_DIFF | wiki:wiki_cards/clothesline.txt | — | CARD_WIKI+INV_CARDS |
| clothesline+ | yes | — | CARD_DIFF | wiki:wiki_cards/clothesline.txt (via clothesline) | — | INV_CARDS |
| clumsy | yes | — | CARD_DIFF | wiki:wiki_cards/clumsy.txt | — | CARD_WIKI+INV_CARDS |
| combust | yes | — | CARD_DIFF | wiki:wiki_cards/combust.txt | — | CARD_WIKI+INV_CARDS |
| combust+ | yes | — | CARD_DIFF | wiki:wiki_cards/combust.txt (via combust) | — | INV_CARDS |
| conjure_blade | yes | conjure_blade_stores_the_energy_as_the_expungers_x, conjure_blade_with_no_energy_makes_a_zero_x_expunger | — | wiki:wiki_cards/conjure_blade.txt | — | §3.1/§255/CARD_WIKI+INV_CARDS/conjure_blade_stores_the_energy_as_the_expungers_x |
| conjure_blade+ | yes | conjure_blade_stores_the_energy_as_the_expungers_x | — | wiki:wiki_cards/conjure_blade.txt (via conjure_blade) | — | INV_CARDS/conjure_blade_stores_the_energy_as_the_expungers_x |
| corruption | yes | — | CARD_DIFF | wiki:wiki_cards/corruption.txt | wiki 偏差：wiki 的 Exhaust 指的是**被打出的那个技能**（"Exhaust it"），Corruption 自己进弃牌堆。 | CARD_WIKI+INV_CARDS |
| corruption+ | yes | — | CARD_DIFF | wiki:wiki_cards/corruption.txt (via corruption) | wiki 偏差：wiki 的 Exhaust 指的是**被打出的那个技能**（"Exhaust it"），Corruption 自己进弃牌堆。 | INV_CARDS |
| curse_of_the_bell | yes | — | CARD_DIFF | wiki:wiki_cards/curse_of_the_bell.txt | — | CARD_WIKI+INV_CARDS |
| dark_embrace | yes | — | CARD_DIFF | wiki:wiki_cards/dark_embrace.txt | — | §237/CARD_WIKI+INV_CARDS |
| dark_embrace+ | yes | — | CARD_DIFF | wiki:wiki_cards/dark_embrace.txt (via dark_embrace) | — | INV_CARDS |
| dark_shackles | yes | exhaust_on_play_is_a_zone_and_the_cards_that_use_it_are_playable | — | wiki:wiki_cards/dark_shackles.txt | wiki 偏差：wiki 升级版是 15 层；内容没有 `dark_shackles+` 这一行。（`Exhaust` 同 `bandage_up`：由落区表达，不是偏差。） | §219/CARD_WIKI+INV_CARDS/exhaust_on_play_is_a_zone_and_the_cards_that_use_it_are_playable |
| dazed | yes | upgrading_burns_walks_every_pile_and_skips_cards_without_an_upgrade, armaments_gains_block_then_upgrades_the_chosen_card …(+2) | — | wiki:wiki_cards/dazed.txt | — | §189/§191/CARD_WIKI+INV_CARDS/upgrading_burns_walks_every_pile_and_skips_cards_without_an_upgrade |
| decay | yes | the_turn_end_curses_do_their_own_thing | — | wiki:wiki_cards/decay.txt | — | CARD_WIKI+INV_CARDS/the_turn_end_curses_do_their_own_thing |
| deep_breath | yes | deep_breath_shuffles_the_discard_pile_back_first | — | wiki:wiki_cards/deep_breath.txt | — | CARD_WIKI+INV_CARDS/deep_breath_shuffles_the_discard_pile_back_first |
| deep_breath+ | yes | — | CARD_DIFF | wiki:wiki_cards/deep_breath.txt (via deep_breath) | — | INV_CARDS |
| defend | yes | dexterity_from_the_content_scales_a_real_defend, card_tags_are_readable_and_a_junk_card_is_not_a_reward …(+55) | — | wiki:wiki_cards/defend.txt | — | §2.1/§6.5/CARD_WIKI+INV_CARDS/dexterity_from_the_content_scales_a_real_defend |
| defend+ | yes | armaments_gains_block_then_upgrades_the_chosen_card, the_upgrade_eggs_upgrade_two_of_their_own_kind …(+2) | — | wiki:wiki_cards/defend.txt (via defend) | — | INV_CARDS/armaments_gains_block_then_upgrades_the_chosen_card |
| demon_form | yes | demon_form_grows_strength_at_every_turn_start | — | wiki:wiki_cards/demon_form.txt | — | CARD_WIKI+INV_CARDS/demon_form_grows_strength_at_every_turn_start |
| demon_form+ | yes | demon_form_grows_strength_at_every_turn_start | — | wiki:wiki_cards/demon_form.txt (via demon_form) | — | INV_CARDS/demon_form_grows_strength_at_every_turn_start |
| disarm | yes | the_new_red_skills_do_what_their_pages_say | — | wiki:wiki_cards/disarm.txt | — | CARD_WIKI+INV_CARDS/the_new_red_skills_do_what_their_pages_say |
| disarm+ | yes | the_new_red_skills_do_what_their_pages_say | — | wiki:wiki_cards/disarm.txt (via disarm) | — | INV_CARDS/the_new_red_skills_do_what_their_pages_say |
| discovery | yes | discovery_offers_three_distinct_class_cards_and_the_pick_is_free | — | spec:INV_CARDS | — | INV_CARDS/discovery_offers_three_distinct_class_cards_and_the_pick_is_free |
| discovery+ | yes | — | CARD_DIFF | spec:INV_CARDS | — | INV_CARDS |
| double_tap | yes | — | CARD_DIFF | wiki:wiki_cards/double_tap.txt | — | §238/CARD_WIKI+INV_CARDS |
| double_tap+ | yes | — | CARD_DIFF | wiki:wiki_cards/double_tap.txt (via double_tap) | — | INV_CARDS |
| doubt | yes | e2e_7e_a_block_gain_spec_in_the_image_truncates_the_block_like_frail, e2e_8_strong_binder_gains_seven_block_then_applies_one_doubt …(+30) | — | wiki:wiki_cards/doubt.txt | ours 回合末给 1 层 Weak，但它在同一回合末就被自己的衰减吃掉 / wiki 原版里 Doubt 的 Weak 会留到下一回合 —— 我们的 `standard.weak` 衰减是一条 `TurnEnded` 触发器（第 ③ 步），而卡牌生命周期节目在第 ① 步 —— 同一次回合末里刚上的 Weak 当场被扣。参考把衰减放在 `decrease_timed_statuses`，与卡程序的关系不同。要修得动回合末的处理器顺序（影响 Burn 等所有生命周期节目），留作单独一节 | §220/§221/CARD_WIKI+INV_CARDS/e2e_7e_a_block_gain_spec_in_the_image_truncates_the_block_like_frail |
| dramatic_entrance | yes | — | CARD_DIFF | wiki:wiki_cards/dramatic_entrance.txt | — | CARD_WIKI+INV_CARDS |
| dramatic_entrance+ | yes | the_zero_cost_utility_batch_matches_its_pages | — | wiki:wiki_cards/dramatic_entrance.txt (via dramatic_entrance) | — | INV_CARDS/the_zero_cost_utility_batch_matches_its_pages |
| dropkick | yes | the_new_red_attacks_do_what_their_pages_say | — | wiki:wiki_cards/dropkick.txt | — | CARD_WIKI+INV_CARDS/the_new_red_attacks_do_what_their_pages_say |
| dropkick+ | yes | — | CARD_DIFF | wiki:wiki_cards/dropkick.txt (via dropkick) | — | INV_CARDS |
| dual_wield | yes | dual_wield_asks_for_an_attack_and_copies_it, a_dual_wield_question_reads_the_same_three_numbers_in_the_page_layer | — | wiki:wiki_cards/dual_wield.txt | — | §226/§227/CARD_WIKI+INV_CARDS/dual_wield_asks_for_an_attack_and_copies_it |
| dual_wield+ | yes | — | CARD_DIFF | wiki:wiki_cards/dual_wield.txt (via dual_wield) | — | INV_CARDS |
| enlightenment | yes | enlightenment_caps_hand_costs_at_one | — | wiki:wiki_cards/enlightenment.txt | — | §248/CARD_WIKI+INV_CARDS/enlightenment_caps_hand_costs_at_one |
| enlightenment+ | yes | — | CARD_DIFF | wiki:wiki_cards/enlightenment.txt (via enlightenment) | — | INV_CARDS |
| entrench | yes | entrench_doubles_the_block_it_already_has | — | wiki:wiki_cards/entrench.txt | — | §233/CARD_WIKI+INV_CARDS/entrench_doubles_the_block_it_already_has |
| entrench+ | yes | — | CARD_DIFF | wiki:wiki_cards/entrench.txt (via entrench) | — | INV_CARDS |
| evolve | yes | — | CARD_DIFF | wiki:wiki_cards/evolve.txt | — | CARD_WIKI+INV_CARDS |
| evolve+ | yes | — | CARD_DIFF | wiki:wiki_cards/evolve.txt (via evolve) | — | INV_CARDS |
| exhume | yes | exhume_pulls_a_card_out_of_the_exhaust_pile | — | wiki:wiki_cards/exhume.txt | — | CARD_WIKI+INV_CARDS/exhume_pulls_a_card_out_of_the_exhaust_pile |
| exhume+ | yes | — | CARD_DIFF | wiki:wiki_cards/exhume.txt (via exhume) | — | INV_CARDS |
| expunger | yes | expunger_repeats_by_its_per_copy_x, conjure_blade_stores_the_energy_as_the_expungers_x | — | wiki:wiki_cards/expunger.txt | — | §251/§255/CARD_WIKI+INV_CARDS/expunger_repeats_by_its_per_copy_x |
| expunger+ | yes | — | CARD_DIFF | wiki:wiki_cards/expunger.txt (via expunger) | — | INV_CARDS |
| fame_and_fortune | yes | the_wish_options_are_unplayable_by_hand, wish_offers_three_cards_and_plays_the_pick_at_once | — | wiki:wiki_cards/fame_and_fortune.txt | — | §254/§255/CARD_WIKI+INV_CARDS/the_wish_options_are_unplayable_by_hand |
| fame_and_fortune+ | yes | wish_plus_offers_the_upgraded_options | — | wiki:wiki_cards/fame_and_fortune.txt (via fame_and_fortune) | — | INV_CARDS/wish_plus_offers_the_upgraded_options |
| feed | yes | feed_only_raises_max_hp_on_a_fatal_blow | — | wiki:wiki_cards/feed.txt | — | CARD_WIKI+INV_CARDS/feed_only_raises_max_hp_on_a_fatal_blow |
| feed+ | yes | — | CARD_DIFF | wiki:wiki_cards/feed.txt (via feed) | — | INV_CARDS |
| feel_no_pain | yes | — | CARD_DIFF | wiki:wiki_cards/feel_no_pain.txt | — | CARD_WIKI+INV_CARDS |
| feel_no_pain+ | yes | — | CARD_DIFF | wiki:wiki_cards/feel_no_pain.txt (via feel_no_pain) | — | INV_CARDS |
| fiend_fire | yes | the_hand_exhausting_cards_do_what_their_pages_say | — | wiki:wiki_cards/fiend_fire.txt | — | CARD_WIKI+INV_CARDS/the_hand_exhausting_cards_do_what_their_pages_say |
| fiend_fire+ | yes | — | CARD_DIFF | wiki:wiki_cards/fiend_fire.txt (via fiend_fire) | — | INV_CARDS |
| finesse | yes | the_zero_cost_utility_batch_matches_its_pages | — | wiki:wiki_cards/finesse.txt | — | CARD_WIKI+INV_CARDS/the_zero_cost_utility_batch_matches_its_pages |
| finesse+ | yes | the_zero_cost_utility_batch_matches_its_pages | — | wiki:wiki_cards/finesse.txt (via finesse) | — | INV_CARDS/the_zero_cost_utility_batch_matches_its_pages |
| fire_breathing | yes | — | CARD_DIFF | wiki:wiki_cards/fire_breathing.txt | — | CARD_WIKI+INV_CARDS |
| fire_breathing+ | yes | — | CARD_DIFF | wiki:wiki_cards/fire_breathing.txt (via fire_breathing) | — | INV_CARDS |
| flame_barrier | yes | the_new_red_skills_do_what_their_pages_say | — | wiki:wiki_cards/flame_barrier.txt | — | CARD_WIKI+INV_CARDS/the_new_red_skills_do_what_their_pages_say |
| flame_barrier+ | yes | — | CARD_DIFF | wiki:wiki_cards/flame_barrier.txt (via flame_barrier) | — | INV_CARDS |
| flash_of_steel | yes | the_zero_cost_utility_batch_matches_its_pages | — | wiki:wiki_cards/flash_of_steel.txt | — | CARD_WIKI+INV_CARDS/the_zero_cost_utility_batch_matches_its_pages |
| flash_of_steel+ | yes | — | CARD_DIFF | wiki:wiki_cards/flash_of_steel.txt (via flash_of_steel) | — | INV_CARDS |
| flex | yes | flex_gains_strength_that_the_turn_end_takes_back, enlightenment_caps_hand_costs_at_one …(+4) | — | wiki:wiki_cards/flex.txt | — | §230/CARD_WIKI+INV_CARDS/flex_gains_strength_that_the_turn_end_takes_back |
| flex+ | yes | flex_gains_strength_that_the_turn_end_takes_back, the_upgrade_eggs_upgrade_two_of_their_own_kind …(+1) | — | wiki:wiki_cards/flex.txt (via flex) | — | INV_CARDS/flex_gains_strength_that_the_turn_end_takes_back |
| forethought | yes | forethought_puts_the_pick_on_the_bottom_of_the_draw_pile | — | wiki:wiki_cards/forethought.txt | — | CARD_WIKI+INV_CARDS/forethought_puts_the_pick_on_the_bottom_of_the_draw_pile |
| forethought+ | yes | — | CARD_DIFF | wiki:wiki_cards/forethought.txt (via forethought) | — | INV_CARDS |
| ghostly_armor | yes | the_ten_cards_added_in_221_do_what_the_wiki_says | — | wiki:wiki_cards/ghostly_armor.txt | — | CARD_WIKI+INV_CARDS/the_ten_cards_added_in_221_do_what_the_wiki_says |
| ghostly_armor+ | yes | — | CARD_DIFF | wiki:wiki_cards/ghostly_armor.txt (via ghostly_armor) | — | INV_CARDS |
| good_instincts | yes | the_zero_cost_utility_batch_matches_its_pages | — | wiki:wiki_cards/good_instincts.txt | — | CARD_WIKI+INV_CARDS/the_zero_cost_utility_batch_matches_its_pages |
| good_instincts+ | yes | the_zero_cost_utility_batch_matches_its_pages | — | wiki:wiki_cards/good_instincts.txt (via good_instincts) | — | INV_CARDS/the_zero_cost_utility_batch_matches_its_pages |
| hand_of_greed | yes | hand_of_greed_pays_only_on_a_fatal_blow | — | wiki:wiki_cards/hand_of_greed.txt | — | §250/CARD_WIKI+INV_CARDS/hand_of_greed_pays_only_on_a_fatal_blow |
| hand_of_greed+ | yes | — | CARD_DIFF | wiki:wiki_cards/hand_of_greed.txt (via hand_of_greed) | — | INV_CARDS |
| havoc | yes | havoc_plays_the_top_card_for_free_into_the_exhaust_pile | — | wiki:wiki_cards/havoc.txt | wiki 偏差：wiki 的 Exhaust 指的是被打出的那张牌（"and Exhaust **it**"），Havoc 自己进弃牌堆。 | §241/CARD_WIKI+INV_CARDS/havoc_plays_the_top_card_for_free_into_the_exhaust_pile |
| havoc+ | yes | havoc_plays_the_top_card_for_free_into_the_exhaust_pile | — | wiki:wiki_cards/havoc.txt (via havoc) | wiki 偏差：wiki 的 Exhaust 指的是被打出的那张牌（"and Exhaust **it**"），Havoc 自己进弃牌堆。 | INV_CARDS/havoc_plays_the_top_card_for_free_into_the_exhaust_pile |
| headbutt | yes | the_new_red_attacks_do_what_their_pages_say | — | wiki:wiki_cards/headbutt.txt | — | CARD_WIKI+INV_CARDS/the_new_red_attacks_do_what_their_pages_say |
| headbutt+ | yes | — | CARD_DIFF | wiki:wiki_cards/headbutt.txt (via headbutt) | — | INV_CARDS |
| heavy_blade | yes | heavy_blade_multiplies_strength_three_or_five_times | — | wiki:wiki_cards/heavy_blade.txt | — | CARD_WIKI+INV_CARDS/heavy_blade_multiplies_strength_three_or_five_times |
| heavy_blade+ | yes | heavy_blade_multiplies_strength_three_or_five_times | — | wiki:wiki_cards/heavy_blade.txt (via heavy_blade) | — | INV_CARDS/heavy_blade_multiplies_strength_three_or_five_times |
| hemokinesis | yes | losing_hp_is_not_damage_but_it_is_hp_loss | — | wiki:wiki_cards/hemokinesis.txt | — | CARD_WIKI+INV_CARDS/losing_hp_is_not_damage_but_it_is_hp_loss |
| hemokinesis+ | yes | — | CARD_DIFF | wiki:wiki_cards/hemokinesis.txt (via hemokinesis) | — | INV_CARDS |
| immolate | yes | the_new_red_attacks_do_what_their_pages_say | — | wiki:wiki_cards/immolate.txt | — | CARD_WIKI+INV_CARDS/the_new_red_attacks_do_what_their_pages_say |
| immolate+ | yes | — | CARD_DIFF | wiki:wiki_cards/immolate.txt (via immolate) | — | INV_CARDS |
| impatience | yes | impatience_only_draws_when_the_hand_has_no_attack | — | wiki:wiki_cards/impatience.txt | — | CARD_WIKI+INV_CARDS/impatience_only_draws_when_the_hand_has_no_attack |
| impatience+ | yes | — | CARD_DIFF | wiki:wiki_cards/impatience.txt (via impatience) | — | INV_CARDS |
| impervious | yes | the_ten_cards_added_in_221_do_what_the_wiki_says | — | wiki:wiki_cards/impervious.txt | — | CARD_WIKI+INV_CARDS/the_ten_cards_added_in_221_do_what_the_wiki_says |
| impervious+ | yes | — | CARD_DIFF | wiki:wiki_cards/impervious.txt (via impervious) | — | INV_CARDS |
| infernal_blade | yes | infernal_blade_adds_a_random_attack_that_really_costs_zero | — | wiki:wiki_cards/infernal_blade.txt | — | §240/CARD_WIKI+INV_CARDS/infernal_blade_adds_a_random_attack_that_really_costs_zero |
| infernal_blade+ | yes | infernal_blade_adds_a_random_attack_that_really_costs_zero | — | wiki:wiki_cards/infernal_blade.txt (via infernal_blade) | — | INV_CARDS/infernal_blade_adds_a_random_attack_that_really_costs_zero |
| inflame | yes | the_zero_infrastructure_tail_lights_up_the_existing_channels | — | wiki:wiki_cards/inflame.txt | — | CARD_WIKI+INV_CARDS/the_zero_infrastructure_tail_lights_up_the_existing_channels |
| inflame+ | yes | — | CARD_DIFF | wiki:wiki_cards/inflame.txt (via inflame) | — | INV_CARDS |
| injury | yes | evolve_and_fire_breathing_only_answer_to_the_right_tags, every_kind_answers_both_sides …(+4) | — | wiki:wiki_cards/injury.txt | — | §143/CARD_WIKI+INV_CARDS/evolve_and_fire_breathing_only_answer_to_the_right_tags |
| insight | yes | the_zero_cost_utility_batch_matches_its_pages | — | wiki:wiki_cards/insight.txt | — | CARD_WIKI+INV_CARDS/the_zero_cost_utility_batch_matches_its_pages |
| insight+ | yes | the_zero_cost_utility_batch_matches_its_pages | — | wiki:wiki_cards/insight.txt (via insight) | — | INV_CARDS/the_zero_cost_utility_batch_matches_its_pages |
| intimidate | yes | — | CARD_DIFF | wiki:wiki_cards/intimidate.txt | — | CARD_WIKI+INV_CARDS |
| intimidate+ | yes | the_new_red_skills_do_what_their_pages_say | — | wiki:wiki_cards/intimidate.txt (via intimidate) | — | INV_CARDS/the_new_red_skills_do_what_their_pages_say |
| iron_wave | yes | stasis_steals_the_best_card_and_returns_it_when_the_orb_dies, tied_rarities_are_broken_by_the_combat_rng | — | wiki:wiki_cards/iron_wave.txt | — | §72.5/CARD_WIKI+INV_CARDS/stasis_steals_the_best_card_and_returns_it_when_the_orb_dies |
| iron_wave+ | yes | — | CARD_DIFF | wiki:wiki_cards/iron_wave.txt (via iron_wave) | — | INV_CARDS |
| j.a.x. | yes | jax_trades_three_hp_for_strength_and_stays_in_play | — | wiki:wiki_cards/j.a.x..txt | — | CARD_WIKI+INV_CARDS/jax_trades_three_hp_for_strength_and_stays_in_play |
| j.a.x.+ | yes | — | CARD_DIFF | wiki:wiki_cards/j.a.x..txt (via j.a.x.) | — | INV_CARDS |
| jack_of_all_trades | yes | — | CARD_DIFF | wiki:wiki_cards/jack_of_all_trades.txt | — | CARD_WIKI+INV_CARDS |
| jack_of_all_trades+ | yes | — | CARD_DIFF | wiki:wiki_cards/jack_of_all_trades.txt (via jack_of_all_trades) | — | INV_CARDS |
| juggernaut | yes | — | CARD_DIFF | wiki:wiki_cards/juggernaut.txt | — | CARD_WIKI+INV_CARDS |
| juggernaut+ | yes | — | CARD_DIFF | wiki:wiki_cards/juggernaut.txt (via juggernaut) | — | INV_CARDS |
| limit_break | yes | limit_break_doubles_strength_and_only_the_base_copy_exhausts | — | wiki:wiki_cards/limit_break.txt | — | CARD_WIKI+INV_CARDS/limit_break_doubles_strength_and_only_the_base_copy_exhausts |
| limit_break+ | yes | limit_break_doubles_strength_and_only_the_base_copy_exhausts | — | wiki:wiki_cards/limit_break.txt (via limit_break) | — | INV_CARDS/limit_break_doubles_strength_and_only_the_base_copy_exhausts |
| live_forever | yes | the_wish_options_are_unplayable_by_hand, wish_offers_three_cards_and_plays_the_pick_at_once | — | wiki:wiki_cards/live_forever.txt | — | §254/§255/CARD_WIKI+INV_CARDS/the_wish_options_are_unplayable_by_hand |
| live_forever+ | yes | wish_plus_offers_the_upgraded_options | — | wiki:wiki_cards/live_forever.txt (via live_forever) | — | INV_CARDS/wish_plus_offers_the_upgraded_options |
| madness | yes | madness_frees_exactly_one_random_hand_card | — | wiki:wiki_cards/madness.txt | — | CARD_WIKI+INV_CARDS/madness_frees_exactly_one_random_hand_card |
| madness+ | yes | — | CARD_DIFF | wiki:wiki_cards/madness.txt (via madness) | — | INV_CARDS |
| magnetism | yes | — | CARD_DIFF | wiki:wiki_cards/magnetism.txt | — | CARD_WIKI+INV_CARDS |
| magnetism+ | yes | — | CARD_DIFF | wiki:wiki_cards/magnetism.txt (via magnetism) | — | INV_CARDS |
| malaise | yes | malaise_spends_the_energy_on_strength_loss_and_weak | — | wiki:wiki_cards/malaise.txt | — | CARD_WIKI+INV_CARDS/malaise_spends_the_energy_on_strength_loss_and_weak |
| malaise+ | yes | malaise_spends_the_energy_on_strength_loss_and_weak | — | wiki:wiki_cards/malaise.txt (via malaise) | — | INV_CARDS/malaise_spends_the_energy_on_strength_loss_and_weak |
| master_of_strategy | yes | the_zero_cost_utility_batch_matches_its_pages | — | wiki:wiki_cards/master_of_strategy.txt | — | CARD_WIKI+INV_CARDS/the_zero_cost_utility_batch_matches_its_pages |
| master_of_strategy+ | yes | the_zero_cost_utility_batch_matches_its_pages | — | wiki:wiki_cards/master_of_strategy.txt (via master_of_strategy) | — | INV_CARDS/the_zero_cost_utility_batch_matches_its_pages |
| mayhem | yes | — | CARD_DIFF | wiki:wiki_cards/mayhem.txt | — | §244/CARD_WIKI+INV_CARDS |
| mayhem+ | yes | — | CARD_DIFF | wiki:wiki_cards/mayhem.txt (via mayhem) | — | INV_CARDS |
| metallicize | yes | decay_predicate_splits_the_two_groups, the_prototype_namespace_supplies_metallicize_and_ritual | — | wiki:wiki_cards/metallicize.txt | — | CARD_WIKI+INV_CARDS/decay_predicate_splits_the_two_groups |
| metallicize+ | yes | — | CARD_DIFF | wiki:wiki_cards/metallicize.txt (via metallicize) | — | INV_CARDS |
| metamorphosis | yes | — | CARD_DIFF | wiki:wiki_cards/metamorphosis.txt | — | CARD_WIKI+INV_CARDS |
| metamorphosis+ | yes | — | CARD_DIFF | wiki:wiki_cards/metamorphosis.txt (via metamorphosis) | — | INV_CARDS |
| mind_blast | yes | mind_blast_scales_with_the_draw_pile | — | wiki:wiki_cards/mind_blast.txt | — | §247/CARD_WIKI+INV_CARDS/mind_blast_scales_with_the_draw_pile |
| mind_blast+ | yes | — | CARD_DIFF | wiki:wiki_cards/mind_blast.txt (via mind_blast) | — | INV_CARDS |
| miracle | yes | the_zero_cost_utility_batch_matches_its_pages | — | wiki:wiki_cards/miracle.txt | — | CARD_WIKI+INV_CARDS/the_zero_cost_utility_batch_matches_its_pages |
| miracle+ | yes | the_zero_cost_utility_batch_matches_its_pages | — | wiki:wiki_cards/miracle.txt (via miracle) | — | INV_CARDS/the_zero_cost_utility_batch_matches_its_pages |
| necronomicurse | yes | necronomicurse_returns_to_hand_when_exhausted | — | wiki:wiki_cards/necronomicurse.txt | — | CARD_WIKI+INV_CARDS/necronomicurse_returns_to_hand_when_exhausted |
| nightmare | yes | nightmare_copies_into_the_aside_pile_and_next_turn_they_arrive | — | wiki:wiki_cards/nightmare.txt | — | CARD_WIKI+INV_CARDS/nightmare_copies_into_the_aside_pile_and_next_turn_they_arrive |
| nightmare+ | yes | — | CARD_DIFF | wiki:wiki_cards/nightmare.txt (via nightmare) | — | INV_CARDS |
| normality | yes | normality_caps_the_cards_played_this_turn | — | wiki:wiki_cards/normality.txt | — | CARD_WIKI+INV_CARDS/normality_caps_the_cards_played_this_turn |
| offering | yes | exhausting_a_card_feeds_feel_no_pain_and_dark_embrace, losing_hp_is_not_damage_but_it_is_hp_loss …(+2) | — | wiki:wiki_cards/offering.txt | — | CARD_WIKI+INV_CARDS/exhausting_a_card_feeds_feel_no_pain_and_dark_embrace |
| offering+ | yes | the_lose_hp_cards_do_what_their_pages_say | — | wiki:wiki_cards/offering.txt (via offering) | — | INV_CARDS/the_lose_hp_cards_do_what_their_pages_say |
| omega | yes | beta_shuffles_an_omega_into_the_draw_pile | — | wiki:wiki_cards/omega.txt | — | §249/CARD_WIKI+INV_CARDS/beta_shuffles_an_omega_into_the_draw_pile |
| omega+ | yes | — | CARD_DIFF | wiki:wiki_cards/omega.txt (via omega) | — | INV_CARDS |
| pain | yes | pain_costs_a_hit_point_per_card_played_while_held | — | wiki:wiki_cards/pain.txt | — | CARD_WIKI+INV_CARDS/pain_costs_a_hit_point_per_card_played_while_held |
| panacea | yes | the_zero_cost_utility_batch_matches_its_pages | — | wiki:wiki_cards/panacea.txt | — | CARD_WIKI+INV_CARDS/the_zero_cost_utility_batch_matches_its_pages |
| panacea+ | yes | the_zero_cost_utility_batch_matches_its_pages | — | wiki:wiki_cards/panacea.txt (via panacea) | — | INV_CARDS/the_zero_cost_utility_batch_matches_its_pages |
| panache | yes | — | CARD_DIFF | wiki:wiki_cards/panache.txt | — | CARD_WIKI+INV_CARDS |
| panache+ | yes | — | CARD_DIFF | wiki:wiki_cards/panache.txt (via panache) | — | INV_CARDS |
| panic_button | yes | — | CARD_DIFF | wiki:wiki_cards/panic_button.txt | — | CARD_WIKI+INV_CARDS |
| panic_button+ | yes | — | CARD_DIFF | wiki:wiki_cards/panic_button.txt (via panic_button) | — | INV_CARDS |
| parasite | yes | — | CARD_DIFF | wiki:wiki_cards/parasite.txt | — | CARD_WIKI+INV_CARDS |
| patient_guard | yes | the_keyword_cells_are_in_the_image | — | spec:INV_CARDS | — | INV_CARDS/the_keyword_cells_are_in_the_image |
| patient_guard+ | yes | — | CARD_DIFF | spec:INV_CARDS | — | INV_CARDS |
| perfected_strike | yes | perfected_strike_counts_the_tagged_cards_in_hand | — | wiki:wiki_cards/perfected_strike.txt | — | CARD_WIKI+INV_CARDS/perfected_strike_counts_the_tagged_cards_in_hand |
| perfected_strike+ | yes | — | CARD_DIFF | wiki:wiki_cards/perfected_strike.txt (via perfected_strike) | — | INV_CARDS |
| pommel_strike | yes | evolve_and_fire_breathing_only_answer_to_the_right_tags, the_ten_cards_added_in_221_do_what_the_wiki_says | — | wiki:wiki_cards/pommel_strike.txt | — | §221/CARD_WIKI+INV_CARDS/evolve_and_fire_breathing_only_answer_to_the_right_tags |
| pommel_strike+ | yes | — | CARD_DIFF | wiki:wiki_cards/pommel_strike.txt (via pommel_strike) | — | INV_CARDS |
| power_through | yes | the_new_red_skills_do_what_their_pages_say | — | wiki:wiki_cards/power_through.txt | — | CARD_WIKI+INV_CARDS/the_new_red_skills_do_what_their_pages_say |
| power_through+ | yes | the_new_red_skills_do_what_their_pages_say | — | wiki:wiki_cards/power_through.txt (via power_through) | — | INV_CARDS/the_new_red_skills_do_what_their_pages_say |
| pride | yes | pride_copies_itself_onto_the_top_of_the_draw_pile | — | wiki:wiki_cards/pride.txt | — | CARD_WIKI+INV_CARDS/pride_copies_itself_onto_the_top_of_the_draw_pile |
| pummel | yes | the_ten_cards_added_in_221_do_what_the_wiki_says | — | wiki:wiki_cards/pummel.txt | — | CARD_WIKI+INV_CARDS/the_ten_cards_added_in_221_do_what_the_wiki_says |
| pummel+ | yes | — | CARD_DIFF | wiki:wiki_cards/pummel.txt (via pummel) | — | INV_CARDS |
| purity | yes | — | CARD_DIFF | wiki:wiki_cards/purity.txt | — | CARD_WIKI+INV_CARDS |
| purity+ | yes | — | CARD_DIFF | wiki:wiki_cards/purity.txt (via purity) | — | INV_CARDS |
| rage | yes | the_new_red_skills_do_what_their_pages_say | — | wiki:wiki_cards/rage.txt | — | CARD_WIKI+INV_CARDS/the_new_red_skills_do_what_their_pages_say |
| rage+ | yes | — | CARD_DIFF | wiki:wiki_cards/rage.txt (via rage) | — | INV_CARDS |
| rampage | yes | rampage_grows_this_copy_and_only_this_copy | — | wiki:wiki_cards/rampage.txt | — | CARD_WIKI+INV_CARDS/rampage_grows_this_copy_and_only_this_copy |
| rampage+ | yes | rampage_grows_this_copy_and_only_this_copy | — | wiki:wiki_cards/rampage.txt (via rampage) | — | INV_CARDS/rampage_grows_this_copy_and_only_this_copy |
| reaper | yes | reaper_heals_only_the_unblocked_damage | — | wiki:wiki_cards/reaper.txt | — | CARD_WIKI+INV_CARDS/reaper_heals_only_the_unblocked_damage |
| reaper+ | yes | — | CARD_DIFF | wiki:wiki_cards/reaper.txt (via reaper) | — | INV_CARDS |
| reckless_charge | yes | the_new_red_attacks_do_what_their_pages_say | — | wiki:wiki_cards/reckless_charge.txt | — | CARD_WIKI+INV_CARDS/the_new_red_attacks_do_what_their_pages_say |
| reckless_charge+ | yes | — | CARD_DIFF | wiki:wiki_cards/reckless_charge.txt (via reckless_charge) | — | INV_CARDS |
| regret | yes | the_turn_end_curses_do_their_own_thing, every_kind_answers_both_sides …(+1) | — | wiki:wiki_cards/regret.txt | — | CARD_WIKI+INV_CARDS/the_turn_end_curses_do_their_own_thing |
| rip_and_tear | yes | rip_and_tear_hits_twice_for_seven | — | wiki:wiki_cards/rip_and_tear.txt | — | §228/§229/CARD_WIKI+INV_CARDS/rip_and_tear_hits_twice_for_seven |
| rip_and_tear+ | yes | rip_and_tear_hits_twice_for_seven | — | wiki:wiki_cards/rip_and_tear.txt (via rip_and_tear) | — | INV_CARDS/rip_and_tear_hits_twice_for_seven |
| ritual_dagger | yes | ritual_dagger_only_grows_when_it_kills, ritual_dagger_growth_survives_the_fight | — | wiki:wiki_cards/ritual_dagger.txt | — | §250/CARD_WIKI+INV_CARDS/ritual_dagger_only_grows_when_it_kills |
| ritual_dagger+ | yes | — | CARD_DIFF | wiki:wiki_cards/ritual_dagger.txt (via ritual_dagger) | — | INV_CARDS |
| rupture | yes | — | CARD_DIFF | wiki:wiki_cards/rupture.txt | — | CARD_WIKI+INV_CARDS |
| rupture+ | yes | the_lose_hp_cards_do_what_their_pages_say | — | wiki:wiki_cards/rupture.txt (via rupture) | — | INV_CARDS/the_lose_hp_cards_do_what_their_pages_say |
| sadistic_nature | yes | — | CARD_DIFF | wiki:wiki_cards/sadistic_nature.txt | — | CARD_WIKI+INV_CARDS |
| sadistic_nature+ | yes | — | CARD_DIFF | wiki:wiki_cards/sadistic_nature.txt (via sadistic_nature) | — | INV_CARDS |
| safety | yes | through_violence_and_safety_differ_only_in_what_they_produce | — | wiki:wiki_cards/safety.txt | — | CARD_WIKI+INV_CARDS/through_violence_and_safety_differ_only_in_what_they_produce |
| safety+ | yes | — | CARD_DIFF | wiki:wiki_cards/safety.txt (via safety) | — | INV_CARDS |
| searing_blow | yes | searing_blow_upgrades_more_than_once_but_strike_does_not | — | wiki:wiki_cards/searing_blow.txt | — | §229/CARD_WIKI+INV_CARDS/searing_blow_upgrades_more_than_once_but_strike_does_not |
| searing_blow+ | yes | searing_blow_upgrades_more_than_once_but_strike_does_not | — | wiki:wiki_cards/searing_blow.txt (via searing_blow) | — | INV_CARDS/searing_blow_upgrades_more_than_once_but_strike_does_not |
| searing_blow++ | yes | searing_blow_upgrades_more_than_once_but_strike_does_not | — | spec:INV_CARDS | — | INV_CARDS/searing_blow_upgrades_more_than_once_but_strike_does_not |
| searing_blow+++ | yes | searing_blow_upgrades_more_than_once_but_strike_does_not | — | spec:INV_CARDS | — | INV_CARDS/searing_blow_upgrades_more_than_once_but_strike_does_not |
| searing_blow++++ | yes | — | CARD_DIFF | spec:INV_CARDS | — | INV_CARDS |
| searing_blow+++++ | yes | — | CARD_DIFF | spec:INV_CARDS | — | INV_CARDS |
| searing_blow++++++ | yes | — | CARD_DIFF | spec:INV_CARDS | — | INV_CARDS |
| searing_blow+++++++ | yes | — | CARD_DIFF | spec:INV_CARDS | — | INV_CARDS |
| second_wind | yes | the_hand_exhausting_cards_do_what_their_pages_say | — | wiki:wiki_cards/second_wind.txt | — | §10/§225/CARD_WIKI+INV_CARDS/the_hand_exhausting_cards_do_what_their_pages_say |
| second_wind+ | yes | — | CARD_DIFF | wiki:wiki_cards/second_wind.txt (via second_wind) | — | INV_CARDS |
| secret_technique | yes | — | CARD_DIFF | wiki:wiki_cards/secret_technique.txt | — | CARD_WIKI+INV_CARDS |
| secret_technique+ | yes | — | CARD_DIFF | wiki:wiki_cards/secret_technique.txt (via secret_technique) | — | INV_CARDS |
| secret_weapon | yes | — | CARD_DIFF | wiki:wiki_cards/secret_weapon.txt | — | CARD_WIKI+INV_CARDS |
| secret_weapon+ | yes | — | CARD_DIFF | wiki:wiki_cards/secret_weapon.txt (via secret_weapon) | — | INV_CARDS |
| seeing_red | yes | the_new_red_skills_do_what_their_pages_say | — | wiki:wiki_cards/seeing_red.txt | — | CARD_WIKI+INV_CARDS/the_new_red_skills_do_what_their_pages_say |
| seeing_red+ | yes | — | CARD_DIFF | wiki:wiki_cards/seeing_red.txt (via seeing_red) | — | INV_CARDS |
| sentinel | yes | the_keyword_cells_are_in_the_image, every_way_into_the_exhaust_pile_runs_the_exhausted_program …(+2) | — | wiki:wiki_cards/sentinel.txt | wiki 偏差：wiki 没有 Ethereal（旧版有），内容带 `ethereal`。§220 起"被 Exhaust 时给 2(3) 能量"**已经实现**（`LifecyclePrograms[Exhausted]`），所以这条偏差只剩 Ethereal 标签本身。 | §220/CARD_WIKI+INV_CARDS/the_keyword_cells_are_in_the_image |
| sentinel+ | yes | a_sentinel_that_gets_exhausted_pays_two_energy | — | wiki:wiki_cards/sentinel.txt (via sentinel) | wiki 偏差：wiki 没有 Ethereal（旧版有），内容带 `ethereal`。§220 起"被 Exhaust 时给 2(3) 能量"**已经实现**（`LifecyclePrograms[Exhausted]`），所以这条偏差只剩 Ethereal 标签本身。 | INV_CARDS/a_sentinel_that_gets_exhausted_pays_two_energy |
| sever_soul | yes | the_new_red_attacks_do_what_their_pages_say | — | wiki:wiki_cards/sever_soul.txt | wiki 偏差：wiki 的 {{KW\|Exhaust}} 是动词（消耗手里的非攻击牌），不是本牌的关键字；牌本身打完进弃牌堆。 | CARD_WIKI+INV_CARDS/the_new_red_attacks_do_what_their_pages_say |
| sever_soul+ | yes | — | CARD_DIFF | wiki:wiki_cards/sever_soul.txt (via sever_soul) | wiki 偏差：wiki 的 {{KW\|Exhaust}} 是动词（消耗手里的非攻击牌），不是本牌的关键字；牌本身打完进弃牌堆。 | INV_CARDS |
| shame | yes | the_turn_end_curses_do_their_own_thing | — | wiki:wiki_cards/shame.txt | — | CARD_WIKI+INV_CARDS/the_turn_end_curses_do_their_own_thing |
| shiv | yes | shiv_and_smite_differ_in_retain_not_only_in_damage, play_card_from_program_is_a_quiet_no_op_when_it_cannot_play | — | wiki:wiki_cards/shiv.txt | — | CARD_WIKI+INV_CARDS/shiv_and_smite_differ_in_retain_not_only_in_damage |
| shiv+ | yes | — | CARD_DIFF | wiki:wiki_cards/shiv.txt (via shiv) | — | INV_CARDS |
| shockwave | yes | the_new_red_skills_do_what_their_pages_say | — | wiki:wiki_cards/shockwave.txt | — | CARD_WIKI+INV_CARDS/the_new_red_skills_do_what_their_pages_say |
| shockwave+ | yes | the_new_red_skills_do_what_their_pages_say | — | wiki:wiki_cards/shockwave.txt (via shockwave) | — | INV_CARDS/the_new_red_skills_do_what_their_pages_say |
| shrug_it_off | yes | the_ten_cards_added_in_221_do_what_the_wiki_says | — | wiki:wiki_cards/shrug_it_off.txt | — | CARD_WIKI+INV_CARDS/the_ten_cards_added_in_221_do_what_the_wiki_says |
| shrug_it_off+ | yes | — | CARD_DIFF | wiki:wiki_cards/shrug_it_off.txt (via shrug_it_off) | — | INV_CARDS |
| skewer | yes | skewer_hits_once_per_energy_spent | — | wiki:wiki_cards/skewer.txt | — | §232/CARD_WIKI+INV_CARDS/skewer_hits_once_per_energy_spent |
| skewer+ | yes | — | CARD_DIFF | wiki:wiki_cards/skewer.txt (via skewer) | — | INV_CARDS |
| slimed | yes | card_tags_are_readable_and_a_junk_card_is_not_a_reward, card_rarity_is_readable_and_the_schema_moved_the_version …(+2) | — | wiki:wiki_cards/slimed.txt | — | §219/§276/CARD_WIKI+INV_CARDS/card_tags_are_readable_and_a_junk_card_is_not_a_reward |
| smite | yes | shiv_and_smite_differ_in_retain_not_only_in_damage | — | wiki:wiki_cards/smite.txt | — | CARD_WIKI+INV_CARDS/shiv_and_smite_differ_in_retain_not_only_in_damage |
| smite+ | yes | — | CARD_DIFF | wiki:wiki_cards/smite.txt (via smite) | — | INV_CARDS |
| spot_weakness | yes | spot_weakness_follows_the_enemy_intent | — | wiki:wiki_cards/spot_weakness.txt | — | §242/CARD_WIKI+INV_CARDS/spot_weakness_follows_the_enemy_intent |
| spot_weakness+ | yes | — | CARD_DIFF | wiki:wiki_cards/spot_weakness.txt (via spot_weakness) | — | INV_CARDS |
| strike | yes | an_innate_card_is_pulled_to_the_top_of_the_draw_pile, a_card_play_leaves_no_chain_referenced …(+125) | — | wiki:wiki_cards/strike.txt | — | §72.5/§221/CARD_WIKI+INV_CARDS/an_innate_card_is_pulled_to_the_top_of_the_draw_pile |
| strike+ | yes | card_tags_are_readable_and_a_junk_card_is_not_a_reward, armaments_gains_block_then_upgrades_the_chosen_card …(+11) | — | wiki:wiki_cards/strike.txt (via strike) | — | INV_CARDS/card_tags_are_readable_and_a_junk_card_is_not_a_reward |
| swift_strike | yes | an_innate_card_is_pulled_to_the_top_of_the_draw_pile, the_keyword_cells_are_in_the_image | — | spec:INV_CARDS | — | INV_CARDS/an_innate_card_is_pulled_to_the_top_of_the_draw_pile |
| swift_strike+ | yes | — | CARD_DIFF | spec:INV_CARDS | — | INV_CARDS |
| sword_boomerang | yes | sword_boomerang_rerolls_a_target_for_each_hit | — | wiki:wiki_cards/sword_boomerang.txt | — | §228/CARD_WIKI+INV_CARDS/sword_boomerang_rerolls_a_target_for_each_hit |
| sword_boomerang+ | yes | sword_boomerang_rerolls_a_target_for_each_hit | — | wiki:wiki_cards/sword_boomerang.txt (via sword_boomerang) | — | INV_CARDS/sword_boomerang_rerolls_a_target_for_each_hit |
| the_bomb | yes | — | CARD_DIFF | wiki:wiki_cards/the_bomb.txt | — | CARD_WIKI+INV_CARDS |
| the_bomb+ | yes | — | CARD_DIFF | wiki:wiki_cards/the_bomb.txt (via the_bomb) | — | INV_CARDS |
| thinking_ahead | yes | — | CARD_DIFF | wiki:wiki_cards/thinking_ahead.txt | — | §246/CARD_WIKI+INV_CARDS |
| thinking_ahead+ | yes | — | CARD_DIFF | wiki:wiki_cards/thinking_ahead.txt (via thinking_ahead) | — | INV_CARDS |
| through_violence | yes | through_violence_and_safety_differ_only_in_what_they_produce | — | wiki:wiki_cards/through_violence.txt | — | §252/§254/CARD_WIKI+INV_CARDS/through_violence_and_safety_differ_only_in_what_they_produce |
| through_violence+ | yes | — | CARD_DIFF | wiki:wiki_cards/through_violence.txt (via through_violence) | — | INV_CARDS |
| thunderclap | yes | the_ten_cards_added_in_221_do_what_the_wiki_says | — | wiki:wiki_cards/thunderclap.txt | — | CARD_WIKI+INV_CARDS/the_ten_cards_added_in_221_do_what_the_wiki_says |
| thunderclap+ | yes | — | CARD_DIFF | wiki:wiki_cards/thunderclap.txt (via thunderclap) | — | INV_CARDS |
| transmutation | yes | — | CARD_DIFF | wiki:wiki_cards/transmutation.txt | — | CARD_WIKI+INV_CARDS |
| transmutation+ | yes | — | CARD_DIFF | wiki:wiki_cards/transmutation.txt (via transmutation) | — | INV_CARDS |
| trip | yes | the_zero_cost_utility_batch_matches_its_pages | — | wiki:wiki_cards/trip.txt | — | §243/CARD_WIKI+INV_CARDS/the_zero_cost_utility_batch_matches_its_pages |
| trip+ | yes | the_zero_cost_utility_batch_matches_its_pages | — | wiki:wiki_cards/trip.txt (via trip) | — | INV_CARDS/the_zero_cost_utility_batch_matches_its_pages |
| true_grit | yes | true_grit_gains_block_and_exhausts_exactly_one_card | — | wiki:wiki_cards/true_grit.txt | — | §195.4/§231/CARD_WIKI+INV_CARDS/true_grit_gains_block_and_exhausts_exactly_one_card |
| true_grit+ | yes | true_grit_gains_block_and_exhausts_exactly_one_card | — | wiki:wiki_cards/true_grit.txt (via true_grit) | — | INV_CARDS/true_grit_gains_block_and_exhausts_exactly_one_card |
| twin_strike | yes | a_full_deck_archive_is_bigger_than_the_generic_scratch | — | wiki:wiki_cards/twin_strike.txt | — | §72.5/CARD_WIKI+INV_CARDS/a_full_deck_archive_is_bigger_than_the_generic_scratch |
| twin_strike+ | yes | — | CARD_DIFF | wiki:wiki_cards/twin_strike.txt (via twin_strike) | — | INV_CARDS |
| uppercut | yes | stasis_steals_the_best_card_and_returns_it_when_the_orb_dies, a_96_card_pile_still_reaches_the_best_card_at_the_end …(+3) | — | wiki:wiki_cards/uppercut.txt | — | CARD_WIKI+INV_CARDS/stasis_steals_the_best_card_and_returns_it_when_the_orb_dies |
| uppercut+ | yes | — | CARD_DIFF | wiki:wiki_cards/uppercut.txt (via uppercut) | — | INV_CARDS |
| violence | yes | — | CARD_DIFF | wiki:wiki_cards/violence.txt | — | CARD_WIKI+INV_CARDS |
| violence+ | yes | — | CARD_DIFF | wiki:wiki_cards/violence.txt (via violence) | — | INV_CARDS |
| void | yes | a_void_drawn_from_the_pile_costs_one_energy | — | wiki:wiki_cards/void.txt | wiki 偏差：wiki: 抽到时失去 1 点能量。内容缺这条触发器（`OnDrawn` 对牌还没有载体），所以 Void 目前只是"不可出的虚无牌"。 | §220/CARD_WIKI+INV_CARDS/a_void_drawn_from_the_pile_costs_one_energy |
| warcry | yes | warcry_draws_one_then_puts_the_chosen_card_on_top | — | wiki:wiki_cards/warcry.txt | — | CARD_WIKI+INV_CARDS/warcry_draws_one_then_puts_the_chosen_card_on_top |
| warcry+ | yes | — | CARD_DIFF | wiki:wiki_cards/warcry.txt (via warcry) | — | INV_CARDS |
| whirlwind | yes | an_upgraded_card_row_is_buildable, the_keyword_cells_are_in_the_image …(+5) | — | wiki:wiki_cards/whirlwind.txt | — | CARD_WIKI+INV_CARDS/an_upgraded_card_row_is_buildable |
| whirlwind+ | yes | an_upgraded_card_row_is_buildable | — | wiki:wiki_cards/whirlwind.txt (via whirlwind) | — | INV_CARDS/an_upgraded_card_row_is_buildable |
| wild_strike | yes | the_ten_cards_added_in_221_do_what_the_wiki_says | — | wiki:wiki_cards/wild_strike.txt | — | CARD_WIKI+INV_CARDS/the_ten_cards_added_in_221_do_what_the_wiki_says |
| wild_strike+ | yes | — | CARD_DIFF | wiki:wiki_cards/wild_strike.txt (via wild_strike) | — | INV_CARDS |
| wish | yes | wish_offers_three_cards_and_plays_the_pick_at_once | — | wiki:wiki_cards/wish.txt | — | §254/§255/CARD_WIKI+INV_CARDS/wish_offers_three_cards_and_plays_the_pick_at_once |
| wish+ | yes | wish_plus_offers_the_upgraded_options | — | wiki:wiki_cards/wish.txt (via wish) | — | INV_CARDS/wish_plus_offers_the_upgraded_options |
| wound | yes | the_new_red_skills_do_what_their_pages_say, painful_stabs_shuffles_a_wound_only_on_unblocked_damage …(+2) | — | wiki:wiki_cards/wound.txt | — | §173/CARD_WIKI+INV_CARDS/the_new_red_skills_do_what_their_pages_say |
| writhe | yes | the_two_event_curses_behave_as_their_pages_say | — | wiki:wiki_cards/writhe.txt | — | §220/§221/CARD_WIKI+INV_CARDS/the_two_event_curses_behave_as_their_pages_say |

## 状态（126）

| Entity | Implemented | TestNamed | HarnessOnly | SourceTie | DeclaredDeviation | Evidence |
|---|---|---|---|---|---|---|
| ritual | yes | ritual_grants_strength_at_the_end_of_the_turn, decay_predicate_splits_the_two_groups …(+1) | — | spec:INV_STATUSES | — | INV_STATUSES/ritual_grants_strength_at_the_end_of_the_turn |
| standard.akabeko | yes (test-only) | the_zero_infrastructure_batch_wires_the_right_carrier, the_reaction_relics_fire_the_right_number_of_times | — | spec:INV_STATUSES | — | §266/§267/INV_STATUSES/the_zero_infrastructure_batch_wires_the_right_carrier |
| standard.ancient_tea_set | yes (test-only) | the_node_relics_pay_on_the_right_kind_of_room, the_tea_set_charge_is_spent_by_the_next_fight | — | spec:INV_STATUSES | — | §269/§271/INV_STATUSES/the_node_relics_pay_on_the_right_kind_of_room |
| standard.art_of_war | yes (test-only) | the_zero_infrastructure_batch_wires_the_right_carrier, the_turn_axis_relics_move_draw_energy_and_periods | — | spec:INV_STATUSES | — | §267/INV_STATUSES/the_zero_infrastructure_batch_wires_the_right_carrier |
| standard.artifact | yes | artifact_turns_a_debuff_into_a_prevented_beat_naming_the_blocked_status, artifact_eats_one_debuff_and_nothing_else …(+9) | — | spec:INV_STATUSES | — | §116/§117/INV_STATUSES/artifact_turns_a_debuff_into_a_prevented_beat_naming_the_blocked_status |
| standard.bag_of_preparation | yes (test-only) | the_five_combat_start_relics_wire_their_own_carrier, the_combat_start_relics_change_the_right_step_of_the_turn | — | spec:INV_STATUSES | — | §261/INV_STATUSES/the_five_combat_start_relics_wire_their_own_carrier |
| standard.barricade | yes | barricade_keeps_block_forever_and_blur_only_for_one_turn | — | spec:INV_STATUSES | — | §197/INV_STATUSES/barricade_keeps_block_forever_and_blur_only_for_one_turn |
| standard.berserk | yes | berserk_adds_one_energy_per_stack_at_turn_start | — | spec:INV_STATUSES | — | §199/§210/INV_STATUSES/berserk_adds_one_energy_per_stack_at_turn_start |
| standard.bird_faced_urn | yes (test-only) | the_zero_infrastructure_tail_wires_its_carriers, the_zero_infrastructure_tail_lights_up_the_existing_channels | — | spec:INV_STATUSES | — | §268/INV_STATUSES/the_zero_infrastructure_tail_wires_its_carriers |
| standard.blur | yes | blur_gives_five_or_eight_block_and_the_status, barricade_keeps_block_forever_and_blur_only_for_one_turn | — | spec:INV_STATUSES | — | §197/§218/INV_STATUSES/blur_gives_five_or_eight_block_and_the_status |
| standard.brimstone | yes (test-only) | the_zero_infrastructure_batch_wires_the_right_carrier, the_reaction_relics_fire_the_right_number_of_times | — | spec:INV_STATUSES | — | §267/INV_STATUSES/the_zero_infrastructure_batch_wires_the_right_carrier |
| standard.brutality | yes | losing_hp_is_not_damage_but_it_is_hp_loss, the_lose_hp_cards_do_what_their_pages_say | — | spec:INV_STATUSES | — | §235/§236/INV_STATUSES/losing_hp_is_not_damage_but_it_is_hp_loss |
| standard.buffer | yes | the_damage_pipeline_honours_intangible_buffer_and_plated_armor, the_zero_infrastructure_batch_wires_the_right_carrier …(+1) | — | spec:INV_STATUSES | — | §149/§223/INV_STATUSES/the_damage_pipeline_honours_intangible_buffer_and_plated_armor |
| standard.busted_crown | yes (test-only) | the_reward_layer_relics_change_the_payout | — | spec:INV_STATUSES | — | §268/§269/INV_STATUSES/the_reward_layer_relics_change_the_payout |
| standard.calipers | yes (test-only) | the_five_combat_start_relics_wire_their_own_carrier, the_combat_start_relics_change_the_right_step_of_the_turn | — | spec:INV_STATUSES | — | §261/INV_STATUSES/the_five_combat_start_relics_wire_their_own_carrier |
| standard.cap_cost_at | yes | — | CARD_DIFF | spec:INV_STATUSES | — | §245/§248/INV_STATUSES |
| standard.captains_wheel | yes (test-only) | the_eight_turn_shaped_relics_wire_their_own_status, the_turn_shaped_relic_statuses_fire_on_the_turn_the_wiki_names | — | spec:INV_STATUSES | — | §260/INV_STATUSES/the_eight_turn_shaped_relics_wire_their_own_status |
| standard.centennial_puzzle | yes (test-only) | the_zero_infrastructure_batch_wires_the_right_carrier, the_reaction_relics_fire_the_right_number_of_times | — | spec:INV_STATUSES | — | §267/INV_STATUSES/the_zero_infrastructure_batch_wires_the_right_carrier |
| standard.champion_belt | yes (test-only) | the_status_parameter_relics_wire_their_own_carrier, the_status_parameter_infrastructure_changes_the_right_number | — | spec:INV_STATUSES | — | §264/§271/INV_STATUSES/the_status_parameter_relics_wire_their_own_carrier |
| standard.charons_ashes | yes (test-only) | the_zero_infrastructure_batch_wires_the_right_carrier, the_reaction_relics_fire_the_right_number_of_times | — | spec:INV_STATUSES | — | §267/INV_STATUSES/the_zero_infrastructure_batch_wires_the_right_carrier |
| standard.cloak_clasp | yes (test-only) | the_eight_turn_shaped_relics_wire_their_own_status, the_turn_shaped_relic_statuses_fire_on_the_turn_the_wiki_names | — | spec:INV_STATUSES | — | §260/INV_STATUSES/the_eight_turn_shaped_relics_wire_their_own_status |
| standard.combust | yes | flame_barrier_hits_back_and_combust_burns_everyone | — | spec:INV_STATUSES | — | §119/INV_STATUSES/flame_barrier_hits_back_and_combust_burns_everyone |
| standard.constricted | yes | constricted_loses_its_stacks_of_hp_through_block_at_turn_end, statuses_outside_the_five_axes_are_readable_by_name …(+1) | — | spec:INV_STATUSES | — | §175/§214/INV_STATUSES/constricted_loses_its_stacks_of_hp_through_block_at_turn_end |
| standard.corruption | yes | corruption_makes_skills_free_and_exhausts_them | — | spec:INV_STATUSES | — | §238/§242/INV_STATUSES/corruption_makes_skills_free_and_exhausts_them |
| standard.curiosity | yes | the_awakened_one_survives_its_first_death_and_then_really_dies | — | spec:INV_STATUSES | — | §194/INV_STATUSES/the_awakened_one_survives_its_first_death_and_then_really_dies |
| standard.curl_up | yes | curl_up_pays_out_once_and_only_for_a_hit_that_draws_blood | — | spec:INV_STATUSES | — | §208/§209/INV_STATUSES/curl_up_pays_out_once_and_only_for_a_hit_that_draws_blood |
| standard.dark_embrace | yes | exhausting_a_card_feeds_feel_no_pain_and_dark_embrace | — | spec:INV_STATUSES | — | §237/§276/INV_STATUSES/exhausting_a_card_feeds_feel_no_pain_and_dark_embrace |
| standard.demon_form | yes | — | CARD_DIFF | spec:INV_STATUSES | — | §231/§235/INV_STATUSES |
| standard.dexterity | yes | dexterity_from_the_content_scales_a_real_defend, global_status_lines_use_the_gs_prefix_and_list_order …(+8) | — | spec:INV_STATUSES | — | §174/§204/INV_STATUSES/dexterity_from_the_content_scales_a_real_defend |
| standard.double_damage | yes (test-only) | the_status_parameter_infrastructure_changes_the_right_number, the_every_nth_card_relics_count_the_right_kind_of_card | — | spec:INV_STATUSES | — | §264/§267/INV_STATUSES/the_status_parameter_infrastructure_changes_the_right_number |
| standard.double_tap | yes | double_tap_only_covers_the_next_attack | — | spec:INV_STATUSES | — | §231/§238/INV_STATUSES/double_tap_only_covers_the_next_attack |
| standard.draw_reduction | yes | draw_reduction_costs_exactly_one_turns_draw_and_then_expires | — | spec:INV_STATUSES | — | §10/§195.7/INV_STATUSES/draw_reduction_costs_exactly_one_turns_draw_and_then_expires |
| standard.duality | yes (test-only) | the_zero_infrastructure_batch_wires_the_right_carrier, the_reaction_relics_fire_the_right_number_of_times | — | spec:INV_STATUSES | — | §267/INV_STATUSES/the_zero_infrastructure_batch_wires_the_right_carrier |
| standard.duplication | yes | duplication_plays_the_program_twice_but_pays_and_counts_once | — | spec:INV_STATUSES | — | §181/INV_STATUSES/duplication_plays_the_program_twice_but_pays_and_counts_once |
| standard.ectoplasm | yes (test-only) | the_gold_and_shop_relics_change_only_their_own_number | — | spec:INV_STATUSES | — | §269/§270/INV_STATUSES/the_gold_and_shop_relics_change_only_their_own_number |
| standard.enrage | yes | a_card_play_leaves_no_chain_referenced, enrage_answers_only_a_skill | — | spec:INV_STATUSES | — | §117/INV_STATUSES/a_card_play_leaves_no_chain_referenced |
| standard.entangle_ready | yes | — | ENEMY_DIFF | spec:INV_STATUSES | — | §196/INV_STATUSES |
| standard.entangled | yes | entangled_refuses_attacks_but_not_skills_and_expires_at_turn_end | — | spec:INV_STATUSES | — | §196/§263/INV_STATUSES/entangled_refuses_attacks_but_not_skills_and_expires_at_turn_end |
| standard.evolve | yes | evolve_and_fire_breathing_only_answer_to_the_right_tags | — | spec:INV_STATUSES | — | §263/§276/INV_STATUSES/evolve_and_fire_breathing_only_answer_to_the_right_tags |
| standard.fairy_in_a_bottle | yes | the_charm_catches_one_killing_blow_and_is_spent | — | spec:INV_STATUSES | — | §180/INV_STATUSES/the_charm_catches_one_killing_blow_and_is_spent |
| standard.feel_no_pain | yes | exhausting_a_card_feeds_feel_no_pain_and_dark_embrace | — | spec:INV_STATUSES | — | §237/§276/INV_STATUSES/exhausting_a_card_feeds_feel_no_pain_and_dark_embrace |
| standard.fire_breathing | yes | evolve_and_fire_breathing_only_answer_to_the_right_tags | — | spec:INV_STATUSES | — | §237/§276/INV_STATUSES/evolve_and_fire_breathing_only_answer_to_the_right_tags |
| standard.flame_barrier | yes | flame_barrier_hits_back_and_combust_burns_everyone, the_new_red_skills_do_what_their_pages_say | — | spec:INV_STATUSES | — | §119/INV_STATUSES/flame_barrier_hits_back_and_combust_burns_everyone |
| standard.flying | yes | flying_halves_attack_damage_and_loses_a_stack_per_hit | — | spec:INV_STATUSES | — | §208/§216/INV_STATUSES/flying_halves_attack_damage_and_loses_a_stack_per_hit |
| standard.frail | yes | entrench_doubles_the_block_it_already_has, the_turn_end_curses_do_their_own_thing …(+7) | — | spec:INV_STATUSES | — | §265/§276/INV_STATUSES/entrench_doubles_the_block_it_already_has |
| standard.ginger | yes (test-only) | the_status_application_relics_wire_their_own_carrier, the_status_application_relics_change_what_lands_on_the_target | — | spec:INV_STATUSES | — | §265/INV_STATUSES/the_status_application_relics_wire_their_own_carrier |
| standard.gremlin_horn | yes (test-only) | the_enemy_death_and_damage_rewrite_relics_wire_their_own_carrier, the_enemy_death_and_damage_rewrite_relics_change_the_right_number | — | spec:INV_STATUSES | — | §263/§264/INV_STATUSES/the_enemy_death_and_damage_rewrite_relics_wire_their_own_carrier |
| standard.happy_flower | yes (test-only) | the_zero_infrastructure_batch_wires_the_right_carrier, the_turn_axis_relics_move_draw_energy_and_periods | — | spec:INV_STATUSES | — | §267/INV_STATUSES/the_zero_infrastructure_batch_wires_the_right_carrier |
| standard.hex | yes | hex_shuffles_a_dazed_only_for_non_attack_cards | — | spec:INV_STATUSES | — | §210/§213/INV_STATUSES/hex_shuffles_a_dazed_only_for_non_attack_cards |
| standard.horn_cleat | yes (test-only) | the_eight_turn_shaped_relics_wire_their_own_status, the_turn_shaped_relic_statuses_fire_on_the_turn_the_wiki_names | — | spec:INV_STATUSES | — | §256/§260/INV_STATUSES/the_eight_turn_shaped_relics_wire_their_own_status |
| standard.ice_cream | yes (test-only) | the_five_combat_start_relics_wire_their_own_carrier, the_combat_start_relics_change_the_right_step_of_the_turn | — | spec:INV_STATUSES | — | §261/INV_STATUSES/the_five_combat_start_relics_wire_their_own_carrier |
| standard.incense_burner | yes (test-only) | the_eight_turn_shaped_relics_wire_their_own_status, the_turn_shaped_relic_statuses_fire_on_the_turn_the_wiki_names | — | spec:INV_STATUSES | — | §260/INV_STATUSES/the_eight_turn_shaped_relics_wire_their_own_status |
| standard.ink_bottle | yes (test-only) | the_every_nth_card_relics_wire_their_own_carrier, the_every_nth_card_relics_count_the_right_kind_of_card | — | spec:INV_STATUSES | — | §262/INV_STATUSES/the_every_nth_card_relics_wire_their_own_carrier |
| standard.intangible | yes | the_damage_pipeline_honours_intangible_buffer_and_plated_armor, the_turn_shaped_relic_statuses_fire_on_the_turn_the_wiki_names | — | spec:INV_STATUSES | — | §210/§223/INV_STATUSES/the_damage_pipeline_honours_intangible_buffer_and_plated_armor |
| standard.juggernaut | yes | juggernaut_punishes_every_block_gain | — | spec:INV_STATUSES | — | §263/§276/INV_STATUSES/juggernaut_punishes_every_block_gain |
| standard.kunai | yes (test-only) | the_every_nth_card_relics_wire_their_own_carrier, the_every_nth_card_relics_count_the_right_kind_of_card | — | spec:INV_STATUSES | — | §261/§262/INV_STATUSES/the_every_nth_card_relics_wire_their_own_carrier |
| standard.lagavulin_asleep | yes | lagavulin_wakes_when_it_loses_health_and_loses_a_turn | — | spec:INV_STATUSES | — | §256/§257/INV_STATUSES/lagavulin_wakes_when_it_loses_health_and_loses_a_turn |
| standard.lantern | yes (test-only) | the_five_combat_start_relics_wire_their_own_carrier, the_combat_start_relics_change_the_right_step_of_the_turn | — | spec:INV_STATUSES | — | §261/INV_STATUSES/the_five_combat_start_relics_wire_their_own_carrier |
| standard.letter_opener | yes (test-only) | the_every_nth_card_relics_wire_their_own_carrier, the_every_nth_card_relics_count_the_right_kind_of_card | — | spec:INV_STATUSES | — | §262/INV_STATUSES/the_every_nth_card_relics_wire_their_own_carrier |
| standard.lizard_tail | yes (test-only) | the_zero_infrastructure_tail_wires_its_carriers, the_zero_infrastructure_tail_lights_up_the_existing_channels | — | spec:INV_STATUSES | — | §268/INV_STATUSES/the_zero_infrastructure_tail_wires_its_carriers |
| standard.lose_dexterity | yes | the_reaction_relics_fire_the_right_number_of_times | — | spec:INV_STATUSES | — | §158/INV_STATUSES/the_reaction_relics_fire_the_right_number_of_times |
| standard.lose_strength | yes | flex_potion_gives_strength_and_takes_it_back | — | spec:INV_STATUSES | — | §158/§230/INV_STATUSES/flex_potion_gives_strength_and_takes_it_back |
| standard.magnetism | yes | — | CARD_DIFF | spec:INV_STATUSES | — | §242/§244/INV_STATUSES |
| standard.mark_of_pain | yes (test-only) | the_zero_infrastructure_batch_wires_the_right_carrier | — | spec:INV_STATUSES | — | §267/INV_STATUSES/the_zero_infrastructure_batch_wires_the_right_carrier |
| standard.mayhem | yes | — | CARD_DIFF | spec:INV_STATUSES | — | §242/§244/INV_STATUSES |
| standard.mercury_hourglass | yes (test-only) | the_eight_turn_shaped_relics_wire_their_own_status, the_turn_shaped_relic_statuses_fire_on_the_turn_the_wiki_names | — | spec:INV_STATUSES | — | §257/§260/INV_STATUSES/the_eight_turn_shaped_relics_wire_their_own_status |
| standard.metallicize | yes | metallicize_grants_block_at_the_end_of_the_turn, plated_armor_and_metallicize_both_pay_block_at_turn_end …(+1) | — | spec:INV_STATUSES | — | §107/§194/INV_STATUSES/metallicize_grants_block_at_the_end_of_the_turn |
| standard.mode_shift | yes | mode_shift_is_a_budget_drained_by_the_health_actually_lost | — | spec:INV_STATUSES | — | §195.1/INV_STATUSES/mode_shift_is_a_budget_drained_by_the_health_actually_lost |
| standard.mutagenic_strength | yes (test-only) | the_zero_infrastructure_batch_wires_the_right_carrier, the_combat_start_carriers_land_the_right_status | — | spec:INV_STATUSES | — | §267/INV_STATUSES/the_zero_infrastructure_batch_wires_the_right_carrier |
| standard.nightmare_pending | yes | nightmare_copies_into_the_aside_pile_and_next_turn_they_arrive | — | spec:INV_STATUSES | — | §213/§227/INV_STATUSES/nightmare_copies_into_the_aside_pile_and_next_turn_they_arrive |
| standard.no_block_from_cards | yes | — | CARD_DIFF | spec:INV_STATUSES | — | §244/§245/INV_STATUSES |
| standard.no_draw | yes | battle_trance_blocks_further_draws_only_this_turn, the_ten_cards_added_in_221_do_what_the_wiki_says | — | spec:INV_STATUSES | — | §227/§231/INV_STATUSES/battle_trance_blocks_further_draws_only_this_turn |
| standard.nunchaku | yes (test-only) | the_every_nth_card_relics_wire_their_own_carrier, the_every_nth_card_relics_count_the_right_kind_of_card | — | spec:INV_STATUSES | — | §262/INV_STATUSES/the_every_nth_card_relics_wire_their_own_carrier |
| standard.odd_mushroom | yes (test-only) | the_conditional_modifier_relics_wire_their_own_carrier, the_conditional_and_self_scoped_modifiers_change_the_right_number | — | spec:INV_STATUSES | — | §266/INV_STATUSES/the_conditional_modifier_relics_wire_their_own_carrier |
| standard.omega | yes | omega_hits_every_enemy_at_the_end_of_the_turn | — | spec:INV_STATUSES | — | §244/§249/INV_STATUSES/omega_hits_every_enemy_at_the_end_of_the_turn |
| standard.orichalcum | yes (test-only) | the_eight_turn_shaped_relics_wire_their_own_status, the_turn_shaped_relic_statuses_fire_on_the_turn_the_wiki_names | — | spec:INV_STATUSES | — | §257/§260/INV_STATUSES/the_eight_turn_shaped_relics_wire_their_own_status |
| standard.ornamental_fan | yes (test-only) | the_every_nth_card_relics_wire_their_own_carrier, the_every_nth_card_relics_count_the_right_kind_of_card | — | spec:INV_STATUSES | — | §261/§262/INV_STATUSES/the_every_nth_card_relics_wire_their_own_carrier |
| standard.painful_stabs | yes | painful_stabs_shuffles_a_wound_only_on_unblocked_damage | — | spec:INV_STATUSES | — | §248/§256/INV_STATUSES/painful_stabs_shuffles_a_wound_only_on_unblocked_damage |
| standard.panache | yes | panache_fires_on_every_fifth_card_of_the_turn | — | spec:INV_STATUSES | — | §244/§249/INV_STATUSES/panache_fires_on_every_fifth_card_of_the_turn |
| standard.paper_krane | yes (test-only) | the_status_parameter_relics_wire_their_own_carrier, the_status_parameter_infrastructure_changes_the_right_number | — | spec:INV_STATUSES | — | §264/INV_STATUSES/the_status_parameter_relics_wire_their_own_carrier |
| standard.paper_phrog | yes (test-only) | the_status_parameter_relics_wire_their_own_carrier, the_status_parameter_infrastructure_changes_the_right_number | — | spec:INV_STATUSES | — | §264/INV_STATUSES/the_status_parameter_relics_wire_their_own_carrier |
| standard.pen_nib | yes (test-only) | the_every_nth_card_relics_wire_their_own_carrier, the_every_nth_card_relics_count_the_right_kind_of_card | — | spec:INV_STATUSES | — | §262/INV_STATUSES/the_every_nth_card_relics_wire_their_own_carrier |
| standard.phantom_veil | yes | — | — | spec:INV_STATUSES | — | §175/§181/INV_STATUSES |
| standard.phase_split | yes | the_boss_phase_splits_once_at_low_health, a_phase_split_happens_once_even_under_three_hits | — | spec:INV_STATUSES | — | §121/§122/INV_STATUSES/the_boss_phase_splits_once_at_low_health |
| standard.philosophers_stone | yes (test-only) | the_zero_infrastructure_batch_wires_the_right_carrier, the_turn_axis_relics_move_draw_energy_and_periods | — | spec:INV_STATUSES | — | §267/INV_STATUSES/the_zero_infrastructure_batch_wires_the_right_carrier |
| standard.plated_armor | yes | a_long_fight_never_reports_a_step_problem, plated_armor_wears_down_to_nothing_without_an_error …(+6) | — | spec:INV_STATUSES | — | §209/§210/INV_STATUSES/a_long_fight_never_reports_a_step_problem |
| standard.pocketwatch | yes (test-only) | the_eight_turn_shaped_relics_wire_their_own_status, the_turn_shaped_relic_statuses_fire_on_the_turn_the_wiki_names | — | spec:INV_STATUSES | — | §260/INV_STATUSES/the_eight_turn_shaped_relics_wire_their_own_status |
| standard.poison | yes (test-only) | modifier_rows_match_exactly_and_through_the_documented_namespace_bridge, combatant_status_lines_keep_instance_order_and_include_pending …(+16) | — | spec:INV_STATUSES | — | §263/§265/INV_STATUSES/modifier_rows_match_exactly_and_through_the_documented_namespace_bridge |
| standard.rage | yes | rage_gives_block_only_for_an_attack, the_new_red_skills_do_what_their_pages_say …(+3) | — | spec:INV_STATUSES | — | §119/INV_STATUSES/rage_gives_block_only_for_an_attack |
| standard.red_skull | yes (test-only) | the_conditional_modifier_relics_wire_their_own_carrier, the_conditional_and_self_scoped_modifiers_change_the_right_number | — | spec:INV_STATUSES | — | §266/INV_STATUSES/the_conditional_modifier_relics_wire_their_own_carrier |
| standard.regain_strength | yes | exhaust_on_play_is_a_zone_and_the_cards_that_use_it_are_playable | — | spec:INV_STATUSES | — | §219/INV_STATUSES/exhaust_on_play_is_a_zone_and_the_cards_that_use_it_are_playable |
| standard.regen | yes | the_awakened_one_survives_its_first_death_and_then_really_dies, regen_heals_at_the_end_of_the_turn …(+1) | — | spec:INV_STATUSES | — | §119/INV_STATUSES/the_awakened_one_survives_its_first_death_and_then_really_dies |
| standard.ring_of_the_serpent | yes (test-only) | the_zero_infrastructure_batch_wires_the_right_carrier, the_turn_axis_relics_move_draw_energy_and_periods | — | spec:INV_STATUSES | — | §264/§267/INV_STATUSES/the_zero_infrastructure_batch_wires_the_right_carrier |
| standard.ring_of_the_snake | yes (test-only) | the_zero_infrastructure_batch_wires_the_right_carrier, the_turn_axis_relics_move_draw_energy_and_periods | — | spec:INV_STATUSES | — | §264/§267/INV_STATUSES/the_zero_infrastructure_batch_wires_the_right_carrier |
| standard.runic_cube | yes (test-only) | the_zero_infrastructure_batch_wires_the_right_carrier, the_reaction_relics_fire_the_right_number_of_times | — | spec:INV_STATUSES | — | §267/INV_STATUSES/the_zero_infrastructure_batch_wires_the_right_carrier |
| standard.runic_pyramid | yes (test-only) | the_zero_infrastructure_tail_wires_its_carriers, the_zero_infrastructure_tail_lights_up_the_existing_channels | — | spec:INV_STATUSES | — | §268/INV_STATUSES/the_zero_infrastructure_tail_wires_its_carriers |
| standard.rupture | yes | losing_hp_is_not_damage_but_it_is_hp_loss, the_lose_hp_cards_do_what_their_pages_say | — | spec:INV_STATUSES | — | §235/§236/INV_STATUSES/losing_hp_is_not_damage_but_it_is_hp_loss |
| standard.sadistic_nature | yes | sadistic_nature_needs_a_debuff_on_someone_else | — | spec:INV_STATUSES | — | §244/§249/INV_STATUSES/sadistic_nature_needs_a_debuff_on_someone_else |
| standard.self_forming_clay | yes (test-only) | the_zero_infrastructure_tail_wires_its_carriers, the_zero_infrastructure_tail_lights_up_the_existing_channels | — | spec:INV_STATUSES | — | §268/INV_STATUSES/the_zero_infrastructure_tail_wires_its_carriers |
| standard.sharp_hide | yes | sharp_hide_hurts_the_player_for_attacks_and_only_attacks, mode_shift_is_a_budget_drained_by_the_health_actually_lost | — | spec:INV_STATUSES | — | §194/§195.1/INV_STATUSES/sharp_hide_hurts_the_player_for_attacks_and_only_attacks |
| standard.shuriken | yes (test-only) | the_every_nth_card_relics_wire_their_own_carrier, the_every_nth_card_relics_count_the_right_kind_of_card | — | spec:INV_STATUSES | — | §261/§262/INV_STATUSES/the_every_nth_card_relics_wire_their_own_carrier |
| standard.slavers_collar | yes (test-only) | the_kind_gated_relics_only_fire_in_their_own_kinds | — | spec:INV_STATUSES | — | §268/§269/INV_STATUSES/the_kind_gated_relics_only_fire_in_their_own_kinds |
| standard.slow | yes | a_card_play_leaves_no_chain_referenced, a_slow_spec_on_a_pipeline_without_a_card_count_is_refused …(+1) | — | spec:INV_STATUSES | ours 放大任何直接伤害（`RestrictDamageKind: Direct`） / wiki 只放大"打出攻击牌造成的伤害" —— 要精确到卡牌标签需要 `RestrictSourceCardTag` 进镜像格式（`status_bind` 目前对非空值响亮拒绝），留作格式升级。基线（本回合牌数、每回合归零、不复合）已与 wiki 一致（§216） | §216/INV_STATUSES/a_card_play_leaves_no_chain_referenced |
| standard.snecko_skull | yes (test-only) | the_status_application_relics_wire_their_own_carrier, the_status_application_relics_change_what_lands_on_the_target | — | spec:INV_STATUSES | — | §265/INV_STATUSES/the_status_application_relics_wire_their_own_carrier |
| standard.sozu | yes (test-only) | sozu_refuses_potions_at_both_doors | — | spec:INV_STATUSES | — | §270/§271/INV_STATUSES/sozu_refuses_potions_at_both_doors |
| standard.split | yes | a_spawned_enemy_joins_the_turn_order_after_the_current_actor, a_phase_split_happens_once_even_under_three_hits …(+1) | — | spec:INV_STATUSES | — | §121/INV_STATUSES/a_spawned_enemy_joins_the_turn_order_after_the_current_actor |
| standard.split_acid_l | yes | a_large_slime_splits_at_half_health_with_its_current_hp | — | spec:INV_STATUSES | — | §269/§276/INV_STATUSES/a_large_slime_splits_at_half_health_with_its_current_hp |
| standard.split_spike_l | yes | a_large_slime_splits_at_half_health_with_its_current_hp, a_large_slime_above_half_health_does_not_split | — | spec:INV_STATUSES | — | §269/§276/INV_STATUSES/a_large_slime_splits_at_half_health_with_its_current_hp |
| standard.spore_cloud | yes | spore_cloud_weakens_the_killer_on_death | — | spec:INV_STATUSES | — | §117/§249/INV_STATUSES/spore_cloud_weakens_the_killer_on_death |
| standard.stasis | yes | stasis_steals_the_best_card_and_returns_it_when_the_orb_dies, a_96_card_pile_still_reaches_the_best_card_at_the_end …(+2) | — | spec:INV_STATUSES | — | §195.1/§195.4/INV_STATUSES/stasis_steals_the_best_card_and_returns_it_when_the_orb_dies |
| standard.stasis_ready | yes | stasis_steals_the_best_card_and_returns_it_when_the_orb_dies, a_96_card_pile_still_reaches_the_best_card_at_the_end …(+2) | — | spec:INV_STATUSES | — | §195.4/INV_STATUSES/stasis_steals_the_best_card_and_returns_it_when_the_orb_dies |
| standard.stone_calendar | yes (test-only) | the_eight_turn_shaped_relics_wire_their_own_status, the_turn_shaped_relic_statuses_fire_on_the_turn_the_wiki_names | — | spec:INV_STATUSES | — | §260/INV_STATUSES/the_eight_turn_shaped_relics_wire_their_own_status |
| standard.strength | yes | dot_slips_past_the_standard_pack_rows_that_direct_hits_do_not, modifier_rows_match_exactly_and_through_the_documented_namespace_bridge …(+69) | — | spec:INV_STATUSES | — | §242/§252/INV_STATUSES/dot_slips_past_the_standard_pack_rows_that_direct_hits_do_not |
| standard.the_bomb | yes | the_bomb_explodes_on_the_third_turn_end_only | — | spec:INV_STATUSES | — | §244/§249/INV_STATUSES/the_bomb_explodes_on_the_third_turn_end_only |
| standard.the_bomb_damage | yes | the_bomb_explodes_on_the_third_turn_end_only | — | spec:INV_STATUSES | — | INV_STATUSES/the_bomb_explodes_on_the_third_turn_end_only |
| standard.the_boot | yes (test-only) | the_enemy_death_and_damage_rewrite_relics_wire_their_own_carrier, the_enemy_death_and_damage_rewrite_relics_change_the_right_number | — | spec:INV_STATUSES | — | §263/INV_STATUSES/the_enemy_death_and_damage_rewrite_relics_wire_their_own_carrier |
| standard.the_specimen | yes (test-only) | the_enemy_death_and_damage_rewrite_relics_wire_their_own_carrier, the_enemy_death_and_damage_rewrite_relics_change_the_right_number | — | spec:INV_STATUSES | — | §263/INV_STATUSES/the_enemy_death_and_damage_rewrite_relics_wire_their_own_carrier |
| standard.thorns | yes | thorns_hurts_whoever_hits_its_owner, standard_status_ids_are_byte_ordered_not_registration_ordered …(+4) | — | spec:INV_STATUSES | — | §214/§249/INV_STATUSES/thorns_hurts_whoever_hits_its_owner |
| standard.time_warp | yes | the_twelfth_card_asks_for_the_turn_to_end | — | spec:INV_STATUSES | — | §122/§125/INV_STATUSES/the_twelfth_card_asks_for_the_turn_to_end |
| standard.torii | yes (test-only) | the_enemy_death_and_damage_rewrite_relics_wire_their_own_carrier, the_enemy_death_and_damage_rewrite_relics_change_the_right_number | — | spec:INV_STATUSES | — | §263/INV_STATUSES/the_enemy_death_and_damage_rewrite_relics_wire_their_own_carrier |
| standard.tungsten_rod | yes (test-only) | the_enemy_death_and_damage_rewrite_relics_wire_their_own_carrier, the_enemy_death_and_damage_rewrite_relics_change_the_right_number | — | spec:INV_STATUSES | — | §263/INV_STATUSES/the_enemy_death_and_damage_rewrite_relics_wire_their_own_carrier |
| standard.turnip | yes (test-only) | the_status_application_relics_wire_their_own_carrier, the_status_application_relics_change_what_lands_on_the_target | — | spec:INV_STATUSES | — | §265/INV_STATUSES/the_status_application_relics_wire_their_own_carrier |
| standard.unawakened | yes | the_awakened_one_survives_its_first_death_and_then_really_dies, the_awakened_one_draws_phase_one_by_weight_and_flips_on_the_guard | — | spec:INV_STATUSES | — | §180/§195.2/INV_STATUSES/the_awakened_one_survives_its_first_death_and_then_really_dies |
| standard.unceasing_top | yes (test-only) | the_zero_infrastructure_tail_wires_its_carriers, the_zero_infrastructure_tail_lights_up_the_existing_channels | — | spec:INV_STATUSES | — | §268/INV_STATUSES/the_zero_infrastructure_tail_wires_its_carriers |
| standard.vulnerable | yes | the_def_table_is_a_side_table_not_a_copy_per_beat, clear_wipes_the_names_too …(+25) | — | spec:INV_STATUSES | — | §263/§266/INV_STATUSES/the_def_table_is_a_side_table_not_a_copy_per_beat |
| standard.weak | yes | the_def_table_is_a_side_table_not_a_copy_per_beat, clear_wipes_the_names_too …(+33) | — | spec:INV_STATUSES | — | §263/§265/INV_STATUSES/the_def_table_is_a_side_table_not_a_copy_per_beat |

## 遭遇（43）

| Entity | Implemented | TestNamed | HarnessOnly | SourceTie | DeclaredDeviation | Evidence |
|---|---|---|---|---|---|---|
| enc_acid_slime_l | yes | — | entity_tables_decode_row_by_row …(+11) | — | — | §276 |
| enc_awakened_one | yes | every_act_has_three_bosses_and_each_one_is_a_buildable_encounter, the_awakened_one_draws_phase_one_by_weight_and_flips_on_the_guard …(+3) | — | — | — | §194/§195.8/every_act_has_three_bosses_and_each_one_is_a_buildable_encounter |
| enc_blue_slaver | yes | the_act_one_hard_pool_encounters_match_the_wiki_numbers | — | — | — | §258/§275/the_act_one_hard_pool_encounters_match_the_wiki_numbers |
| enc_book_of_stabbing | yes | the_five_elite_encounters_match_the_wiki_numbers, book_of_stabbing_multistab_starts_at_two_hits | — | — | — | §173/the_five_elite_encounters_match_the_wiki_numbers |
| enc_bronze_automaton | yes | every_act_has_three_bosses_and_each_one_is_a_buildable_encounter, the_automaton_swaps_stunned_for_boost_only_at_a19 …(+3) | — | — | — | §138/§194/every_act_has_three_bosses_and_each_one_is_a_buildable_encounter |
| enc_byrds | yes | flying_halves_attack_damage_and_loses_a_stack_per_hit | — | — | — | §138/§277/flying_halves_attack_damage_and_loses_a_stack_per_hit |
| enc_chosen | yes | hex_shuffles_a_dazed_only_for_non_attack_cards, chosen_swaps_its_opener_at_a17 | — | — | — | §276/§277/hex_shuffles_a_dazed_only_for_non_attack_cards |
| enc_cultist | yes | an_encounter_without_rolls_draws_nothing, building_a_louse_fight_draws_its_bite_and_a_cultist_fight_does_not …(+10) | — | — | — | §5.2/§130/an_encounter_without_rolls_draws_nothing |
| enc_darklings | yes | an_encounter_with_two_records_of_the_same_id_builds | — | — | — | §277/an_encounter_with_two_records_of_the_same_id_builds |
| enc_donu_and_deca | yes | every_act_has_three_bosses_and_each_one_is_a_buildable_encounter | — | — | — | §194/§195.8/every_act_has_three_bosses_and_each_one_is_a_buildable_encounter |
| enc_exordium_thugs | yes | the_composed_encounters_pick_from_their_candidates | — | — | — | §276/§277/the_composed_encounters_pick_from_their_candidates |
| enc_exordium_wildlife | yes | — | entity_tables_decode_row_by_row …(+11) | — | — | §276/§277 |
| enc_fungi_beast | yes | — | entity_tables_decode_row_by_row …(+11) | — | — | §130/§258 |
| enc_giant_head | yes | a_summoned_minion_resolves_through_the_image_not_the_encounter, giant_head_counts_down_then_only_its_time …(+1) | — | — | — | §134/a_summoned_minion_resolves_through_the_image_not_the_encounter |
| enc_gremlin_gang | yes | — | entity_tables_decode_row_by_row …(+11) | — | — | §138/§153 |
| enc_gremlin_leader | yes | — | entity_tables_decode_row_by_row …(+11) | — | — | §5.3/§134 |
| enc_gremlin_nob | yes | an_ascension_health_row_applies_at_its_own_level_and_not_below, the_every_nth_card_relics_count_the_right_kind_of_card | — | — | — | §152/an_ascension_health_row_applies_at_its_own_level_and_not_below |
| enc_hexaghost | yes | every_act_has_three_bosses_and_each_one_is_a_buildable_encounter, hexaghost_plays_the_wikis_seven_move_pattern_after_its_two_openers | — | — | — | §194/every_act_has_three_bosses_and_each_one_is_a_buildable_encounter |
| enc_jaw_worm | yes | a_round_one_rule_beats_the_cycle_and_the_cycle_takes_over_after_it, uppercut_hurts_the_enemy_and_not_the_hero …(+3) | — | — | — | §5.2/§130/a_round_one_rule_beats_the_cycle_and_the_cycle_takes_over_after_it |
| enc_lagavulin | yes | the_five_elite_encounters_match_the_wiki_numbers, lagavulin_wakes_when_it_loses_health_and_loses_a_turn …(+2) | — | — | — | §173/the_five_elite_encounters_match_the_wiki_numbers |
| enc_looter | yes | an_ascension_health_row_applies_at_its_own_level_and_not_below, the_looter_mugs_twice_then_bombs_then_escapes | — | — | — | §175/§201/an_ascension_health_row_applies_at_its_own_level_and_not_below |
| enc_louse | yes | a_spawn_roll_is_drawn_once_per_fight_and_read_by_the_action, an_encounter_without_rolls_draws_nothing …(+2) | — | — | — | §130/§152/a_spawn_roll_is_drawn_once_per_fight_and_read_by_the_action |
| enc_maw | yes | nom_nom_hits_five_damage_ceil_round_over_two_times, the_maw_follows_the_wikis_transition_table | — | — | — | §147/§277/nom_nom_hits_five_damage_ceil_round_over_two_times |
| enc_nemesis | yes | the_five_elite_encounters_match_the_wiki_numbers, nemesis_never_repeats_burn_or_scythe_and_never_triple_attacks | — | — | — | §175/the_five_elite_encounters_match_the_wiki_numbers |
| enc_orb_walker | yes | — | entity_tables_decode_row_by_row …(+11) | — | — | §138/§277 |
| enc_reptomancer | yes | the_five_elite_encounters_match_the_wiki_numbers, reptomancer_switches_to_snake_strike_when_four_daggers_are_out …(+2) | — | — | — | §175/the_five_elite_encounters_match_the_wiki_numbers |
| enc_shelled_parasite | yes | — | entity_tables_decode_row_by_row …(+11) | — | — | §276/§277 |
| enc_slaver_red | yes | — | entity_tables_decode_row_by_row …(+11) | — | — | §130/§258 |
| enc_slavers | yes | the_five_elite_encounters_match_the_wiki_numbers, blue_slaver_never_rakes_twice_in_a_row_at_a17 …(+1) | — | — | — | the_five_elite_encounters_match_the_wiki_numbers |
| enc_slime_boss | yes | every_act_has_three_bosses_and_each_one_is_a_buildable_encounter, a_combinator_rule_switches_the_boss_move …(+1) | — | — | — | §194/every_act_has_three_bosses_and_each_one_is_a_buildable_encounter |
| enc_small_slimes | yes | a_spawned_combatant_still_resolves_to_its_enemy_record | — | — | — | §130/a_spawned_combatant_still_resolves_to_its_enemy_record |
| enc_spike_slime_l | yes | — | entity_tables_decode_row_by_row …(+11) | — | — | §276 |
| enc_spiker | yes | spiker_never_repeats_its_attack_and_buffs_thorns_at_most_six_times, starting_statuses_follow_their_ascension_rows | — | — | — | §138/§277/spiker_never_repeats_its_attack_and_buffs_thorns_at_most_six_times |
| enc_spire_growth | yes | spire_growth_smashes_instead_of_choosing | — | — | — | §147/§277/spire_growth_smashes_instead_of_choosing |
| enc_swarm_of_slimes | yes | — | entity_tables_decode_row_by_row …(+11) | — | — | §275/§276 |
| enc_the_champ | yes | an_ascension_health_row_applies_at_its_own_level_and_not_below, every_act_has_three_bosses_and_each_one_is_a_buildable_encounter …(+4) | — | — | — | §194/an_ascension_health_row_applies_at_its_own_level_and_not_below |
| enc_the_collector | yes | the_collector_draws_by_weight_and_never_buffs_twice_in_a_row, every_act_has_three_bosses_and_each_one_is_a_buildable_encounter …(+1) | — | — | — | §138/§194/the_collector_draws_by_weight_and_never_buffs_twice_in_a_row |
| enc_the_guardian | yes | mode_shift_is_a_budget_drained_by_the_health_actually_lost, every_act_has_three_bosses_and_each_one_is_a_buildable_encounter …(+1) | — | — | — | §194/mode_shift_is_a_budget_drained_by_the_health_actually_lost |
| enc_three_louses | yes | the_act_one_hard_pool_encounters_match_the_wiki_numbers | — | — | — | §258/§275/the_act_one_hard_pool_encounters_match_the_wiki_numbers |
| enc_three_sentries | yes | — | entity_tables_decode_row_by_row …(+11) | — | — | §134 |
| enc_time_eater | yes | every_act_has_three_bosses_and_each_one_is_a_buildable_encounter, a_weighted_boss_never_repeats_the_move_the_wiki_forbids …(+2) | — | — | — | §138/§194/every_act_has_three_bosses_and_each_one_is_a_buildable_encounter |
| enc_two_fungi_beasts | yes | the_act_one_hard_pool_encounters_match_the_wiki_numbers | — | — | — | §258/§275/the_act_one_hard_pool_encounters_match_the_wiki_numbers |
| enc_two_louses | yes | louse_bites_are_rolled_at_spawn_and_the_green_one_reads_its_roll, the_two_louses_have_the_moves_the_wiki_gives_them …(+1) | — | — | — | §201/§258/louse_bites_are_rolled_at_spawn_and_the_green_one_reads_its_roll |

## 事件（13）

| Entity | Implemented | TestNamed | HarnessOnly | SourceTie | DeclaredDeviation | Evidence |
|---|---|---|---|---|---|---|
| ancient_forge | yes | the_unknown_room_events_are_readable, an_event_that_edits_the_deck_owes_a_pick_first …(+3) | — | — | — | the_unknown_room_events_are_readable |
| ancient_writing | yes | the_unknown_room_events_are_readable, an_event_choice_that_edits_the_deck_owes_a_pick | — | — | — | the_unknown_room_events_are_readable |
| forgotten_altar | yes | the_unknown_room_events_are_readable, an_event_choice_that_edits_the_deck_owes_a_pick | — | — | — | the_unknown_room_events_are_readable |
| golden_idol | yes | the_unknown_room_events_are_readable, every_kind_answers_both_sides …(+14) | — | — | — | §156/§157/the_unknown_room_events_are_readable |
| old_shrine | yes | the_unknown_room_events_are_readable, an_event_can_give_a_relic_only_if_the_kernel_can_run_it | — | — | — | the_unknown_room_events_are_readable |
| purification_shrine | yes | the_unknown_room_events_are_readable | — | — | — | the_unknown_room_events_are_readable |
| scrap_pile | yes | the_unknown_room_events_are_readable | — | — | — | the_unknown_room_events_are_readable |
| shining_light | yes | the_unknown_room_events_are_readable | — | — | — | the_unknown_room_events_are_readable |
| the_cleric | yes | the_unknown_room_events_are_readable, paying_more_gold_than_you_have_is_refused_not_clamped …(+1) | — | — | — | the_unknown_room_events_are_readable |
| the_mausoleum | yes | the_unknown_room_events_are_readable | — | — | — | the_unknown_room_events_are_readable |
| the_moai_head | yes | the_unknown_room_events_are_readable, heal_full_reaches_the_current_maximum …(+1) | — | — | — | the_unknown_room_events_are_readable |
| the_ssssserpent | yes | the_unknown_room_events_are_readable | — | — | — | the_unknown_room_events_are_readable |
| wandering_merchant | yes | the_unknown_room_events_are_readable | — | — | — | the_unknown_room_events_are_readable |

## 遗物（115）

| Entity | Implemented | TestNamed | HarnessOnly | SourceTie | DeclaredDeviation | Evidence |
|---|---|---|---|---|---|---|
| akabeko | yes | the_zero_infrastructure_batch_wires_the_right_carrier | — | — | — | §266/§267/the_zero_infrastructure_batch_wires_the_right_carrier |
| anchor | yes | the_same_state_hashes_the_same_and_a_change_moves_it, every_invariant_names_itself_when_violated …(+7) | — | — | — | the_same_state_hashes_the_same_and_a_change_moves_it |
| ancient_tea_set | yes | the_node_relics_pay_on_the_right_kind_of_room, the_tea_set_charge_is_spent_by_the_next_fight | — | — | — | §271/the_node_relics_pay_on_the_right_kind_of_room |
| art_of_war | yes | the_zero_infrastructure_batch_wires_the_right_carrier | — | — | — | §266/§267/the_zero_infrastructure_batch_wires_the_right_carrier |
| astrolabe | yes | the_pickup_picks_do_not_take_over_the_screen | — | — | — | §273/§274/the_pickup_picks_do_not_take_over_the_screen |
| bag_of_marbles | yes | the_two_combat_start_carriers_land_on_the_right_side | — | — | — | §221/§224/the_two_combat_start_carriers_land_on_the_right_side |
| bag_of_preparation | yes | the_five_combat_start_relics_wire_their_own_carrier | — | — | — | §261/the_five_combat_start_relics_wire_their_own_carrier |
| bird_faced_urn | yes | the_zero_infrastructure_tail_wires_its_carriers | — | — | — | §267/§268/the_zero_infrastructure_tail_wires_its_carriers |
| black_blood | yes | the_zero_infrastructure_tail_wires_its_carriers | — | — | — | §267/§268/the_zero_infrastructure_tail_wires_its_carriers |
| black_star | yes | — | an_id_that_is_a_card_and_a_relic_is_not_an_encounter …(+5) | — | — | §269 |
| blood_vial | yes | the_relic_pool_fires_at_the_three_hooks_it_has | — | — | — | the_relic_pool_fires_at_the_three_hooks_it_has |
| bloody_idol | yes | every_kind_answers_both_sides, the_gold_and_shop_relics_change_only_their_own_number …(+1) | — | — | — | §270/every_kind_answers_both_sides |
| brimstone | yes | the_zero_infrastructure_batch_wires_the_right_carrier | — | — | — | §266/§267/the_zero_infrastructure_batch_wires_the_right_carrier |
| bronze_scales | yes | — | an_id_that_is_a_card_and_a_relic_is_not_an_encounter …(+5) | — | — | §156 |
| burning_blood | yes | capacity_is_an_error_not_a_truncation, burning_blood_heals_six_at_the_end_of_a_fight …(+8) | — | — | — | capacity_is_an_error_not_a_truncation |
| busted_crown | yes | the_reward_layer_relics_change_the_payout | — | — | — | §269/the_reward_layer_relics_change_the_payout |
| calipers | yes | the_five_combat_start_relics_wire_their_own_carrier | — | — | — | §261/the_five_combat_start_relics_wire_their_own_carrier |
| captains_wheel | yes | the_eight_turn_shaped_relics_wire_their_own_status | — | — | — | §260/the_eight_turn_shaped_relics_wire_their_own_status |
| centennial_puzzle | yes | the_zero_infrastructure_batch_wires_the_right_carrier | — | — | — | §266/§267/the_zero_infrastructure_batch_wires_the_right_carrier |
| ceramic_fish | yes | the_add_card_relics_fire_at_the_one_add_point | — | — | — | §270/the_add_card_relics_fire_at_the_one_add_point |
| champion_belt | yes | the_status_parameter_relics_wire_their_own_carrier | — | — | — | §263/§264/the_status_parameter_relics_wire_their_own_carrier |
| charons_ashes | yes | the_zero_infrastructure_batch_wires_the_right_carrier | — | — | — | §266/§267/the_zero_infrastructure_batch_wires_the_right_carrier |
| cloak_clasp | yes | the_eight_turn_shaped_relics_wire_their_own_status | — | — | — | §260/the_eight_turn_shaped_relics_wire_their_own_status |
| clockwork_souvenir | yes | the_zero_infrastructure_batch_wires_the_right_carrier | — | — | — | §266/§267/the_zero_infrastructure_batch_wires_the_right_carrier |
| coffee_dripper | yes | campfire_options_follow_the_relics_the_wiki_names, dig_only_rolls_common_uncommon_or_rare | — | — | — | §259/campfire_options_follow_the_relics_the_wiki_names |
| darkstone_periapt | yes | the_add_card_relics_fire_at_the_one_add_point | — | — | — | §270/the_add_card_relics_fire_at_the_one_add_point |
| dream_catcher | yes | dream_catcher_turns_rest_into_a_card_reward_and_only_with_the_relic | — | — | — | dream_catcher_turns_rest_into_a_card_reward_and_only_with_the_relic |
| du_vu_doll | yes | the_five_combat_start_relics_wire_their_own_carrier | — | — | — | §261/the_five_combat_start_relics_wire_their_own_carrier |
| duality | yes | the_zero_infrastructure_batch_wires_the_right_carrier | — | — | — | §266/§267/the_zero_infrastructure_batch_wires_the_right_carrier |
| ectoplasm | yes | the_pickup_number_relics_change_only_their_own_number, the_gold_and_shop_relics_change_only_their_own_number | — | — | — | §270/the_pickup_number_relics_change_only_their_own_number |
| empty_cage | yes | the_pickup_picks_do_not_take_over_the_screen | — | — | — | §273/§274/the_pickup_picks_do_not_take_over_the_screen |
| eternal_feather | yes | the_eternal_feather_pays_per_whole_group_of_five_on_entering, the_new_relics_pay_out | — | — | — | §156/§157/the_eternal_feather_pays_per_whole_group_of_five_on_entering |
| fossilized_helix | yes | the_zero_infrastructure_batch_wires_the_right_carrier | — | — | — | §266/§267/the_zero_infrastructure_batch_wires_the_right_carrier |
| frozen_egg | yes | the_add_card_relics_fire_at_the_one_add_point | — | — | — | §270/the_add_card_relics_fire_at_the_one_add_point |
| fusion_hammer | yes | campfire_options_follow_the_relics_the_wiki_names | — | — | — | campfire_options_follow_the_relics_the_wiki_names |
| ginger | yes | the_status_application_relics_wire_their_own_carrier | — | — | — | §264/§265/the_status_application_relics_wire_their_own_carrier |
| girya | yes | campfire_options_follow_the_relics_the_wiki_names, dig_only_rolls_common_uncommon_or_rare …(+2) | — | — | — | §259/campfire_options_follow_the_relics_the_wiki_names |
| golden_idol | yes | the_unknown_room_events_are_readable, every_kind_answers_both_sides …(+14) | — | — | — | §156/§157/the_unknown_room_events_are_readable |
| gremlin_horn | yes | the_enemy_death_and_damage_rewrite_relics_wire_their_own_carrier | — | — | — | §262/§263/the_enemy_death_and_damage_rewrite_relics_wire_their_own_carrier |
| gremlin_visage | yes | the_zero_infrastructure_batch_wires_the_right_carrier | — | — | — | §266/§267/the_zero_infrastructure_batch_wires_the_right_carrier |
| happy_flower | yes | the_zero_infrastructure_batch_wires_the_right_carrier | — | — | — | §266/§267/the_zero_infrastructure_batch_wires_the_right_carrier |
| horn_cleat | yes | the_eight_turn_shaped_relics_wire_their_own_status | — | — | — | §260/the_eight_turn_shaped_relics_wire_their_own_status |
| ice_cream | yes | the_five_combat_start_relics_wire_their_own_carrier | — | — | — | §261/the_five_combat_start_relics_wire_their_own_carrier |
| incense_burner | yes | the_eight_turn_shaped_relics_wire_their_own_status | — | — | — | §260/the_eight_turn_shaped_relics_wire_their_own_status |
| ink_bottle | yes | the_every_nth_card_relics_wire_their_own_carrier | — | — | — | §262/the_every_nth_card_relics_wire_their_own_carrier |
| juzu_bracelet | yes | the_unknown_room_odds_walk_the_wikis_base_values, tiny_chest_and_juzu_bracelet_change_the_roll | — | — | — | §271/§272/the_unknown_room_odds_walk_the_wikis_base_values |
| kunai | yes | the_every_nth_card_relics_wire_their_own_carrier | — | — | — | §261/§262/the_every_nth_card_relics_wire_their_own_carrier |
| lantern | yes | the_five_combat_start_relics_wire_their_own_carrier | — | — | — | §261/the_five_combat_start_relics_wire_their_own_carrier |
| lees_waffle | yes | the_pickup_number_relics_change_only_their_own_number | — | — | — | §273/§274/the_pickup_number_relics_change_only_their_own_number |
| letter_opener | yes | the_every_nth_card_relics_wire_their_own_carrier | — | — | — | §261/§262/the_every_nth_card_relics_wire_their_own_carrier |
| lizard_tail | yes | the_zero_infrastructure_tail_wires_its_carriers | — | — | — | §267/§268/the_zero_infrastructure_tail_wires_its_carriers |
| mango | yes | the_zero_infrastructure_batch_wires_the_right_carrier | — | — | — | §266/§267/the_zero_infrastructure_batch_wires_the_right_carrier |
| mark_of_pain | yes | the_zero_infrastructure_batch_wires_the_right_carrier | — | — | — | §266/§267/the_zero_infrastructure_batch_wires_the_right_carrier |
| mark_of_the_bloom | yes | campfire_options_follow_the_relics_the_wiki_names | — | — | — | §259/campfire_options_follow_the_relics_the_wiki_names |
| maw_bank | yes | the_gold_and_shop_relics_change_only_their_own_number, a_discounted_purchase_charges_the_discounted_price | — | — | — | §270/the_gold_and_shop_relics_change_only_their_own_number |
| meal_ticket | yes | an_unknown_room_that_becomes_a_shop_pays_the_shop_entry_relics, the_node_relics_pay_on_the_right_kind_of_room | — | — | — | §271/an_unknown_room_that_becomes_a_shop_pays_the_shop_entry_relics |
| meat_on_the_bone | yes | — | an_id_that_is_a_card_and_a_relic_is_not_an_encounter …(+5) | — | — | §156 |
| membership_card | yes | the_courier_restocks_the_slot_it_sells, the_gold_and_shop_relics_change_only_their_own_number …(+1) | — | — | — | §270/the_courier_restocks_the_slot_it_sells |
| mercury_hourglass | yes | the_eight_turn_shaped_relics_wire_their_own_status | — | — | — | §260/the_eight_turn_shaped_relics_wire_their_own_status |
| molten_egg | yes | the_add_card_relics_fire_at_the_one_add_point | — | — | — | §270/the_add_card_relics_fire_at_the_one_add_point |
| mutagenic_strength | yes | the_zero_infrastructure_batch_wires_the_right_carrier | — | — | — | §266/§267/the_zero_infrastructure_batch_wires_the_right_carrier |
| nunchaku | yes | the_every_nth_card_relics_wire_their_own_carrier | — | — | — | §261/§262/the_every_nth_card_relics_wire_their_own_carrier |
| odd_mushroom | yes | the_conditional_modifier_relics_wire_their_own_carrier | — | — | — | §265/§266/the_conditional_modifier_relics_wire_their_own_carrier |
| oddly_smooth_stone | yes | the_two_combat_start_carriers_land_on_the_right_side | — | — | — | §221/§224/the_two_combat_start_carriers_land_on_the_right_side |
| old_coin | yes | the_pickup_number_relics_change_only_their_own_number | — | — | — | §273/§274/the_pickup_number_relics_change_only_their_own_number |
| omamori | yes | the_add_card_relics_fire_at_the_one_add_point | — | — | — | §270/the_add_card_relics_fire_at_the_one_add_point |
| orichalcum | yes | the_eight_turn_shaped_relics_wire_their_own_status | — | — | — | §260/the_eight_turn_shaped_relics_wire_their_own_status |
| ornamental_fan | yes | the_every_nth_card_relics_wire_their_own_carrier | — | — | — | §261/§262/the_every_nth_card_relics_wire_their_own_carrier |
| pandoras_box | yes | pandoras_box_transforms_every_staple_and_nothing_else | — | — | — | §273/§274/pandoras_box_transforms_every_staple_and_nothing_else |
| pantograph | yes | the_kind_gated_relics_only_fire_in_their_own_kinds | — | — | — | §268/§269/the_kind_gated_relics_only_fire_in_their_own_kinds |
| paper_krane | yes | the_status_parameter_relics_wire_their_own_carrier | — | — | — | §263/§264/the_status_parameter_relics_wire_their_own_carrier |
| paper_phrog | yes | the_status_parameter_relics_wire_their_own_carrier | — | — | — | §263/§264/the_status_parameter_relics_wire_their_own_carrier |
| peace_pipe | yes | campfire_options_follow_the_relics_the_wiki_names, toke_removes_a_card_without_charging_for_it …(+1) | — | — | — | §259/campfire_options_follow_the_relics_the_wiki_names |
| pear | yes | the_relic_pool_fires_at_the_three_hooks_it_has | — | — | — | the_relic_pool_fires_at_the_three_hooks_it_has |
| pen_nib | yes | the_every_nth_card_relics_wire_their_own_carrier | — | — | — | §262/the_every_nth_card_relics_wire_their_own_carrier |
| philosophers_stone | yes | the_zero_infrastructure_batch_wires_the_right_carrier | — | — | — | §266/§267/the_zero_infrastructure_batch_wires_the_right_carrier |
| pocketwatch | yes | the_eight_turn_shaped_relics_wire_their_own_status | — | — | — | §260/the_eight_turn_shaped_relics_wire_their_own_status |
| potion_belt | yes | capacity_is_an_error_not_a_truncation, the_ascension_rules_are_each_their_own_level …(+1) | — | — | — | §156/§157/capacity_is_an_error_not_a_truncation |
| prayer_wheel | yes | the_reward_layer_relics_change_the_payout | — | — | — | §269/the_reward_layer_relics_change_the_payout |
| preserved_insect | yes | the_kind_gated_relics_only_fire_in_their_own_kinds | — | — | — | §268/§269/the_kind_gated_relics_only_fire_in_their_own_kinds |
| question_card | yes | the_reward_layer_relics_change_the_payout | — | — | — | §269/the_reward_layer_relics_change_the_payout |
| red_mask | yes | the_zero_infrastructure_batch_wires_the_right_carrier | — | — | — | §266/§267/the_zero_infrastructure_batch_wires_the_right_carrier |
| red_skull | yes | the_conditional_modifier_relics_wire_their_own_carrier | — | — | — | §265/§266/the_conditional_modifier_relics_wire_their_own_carrier |
| regal_pillow | yes | — | an_id_that_is_a_card_and_a_relic_is_not_an_encounter …(+5) | — | — | §156 |
| ring_of_the_serpent | yes | the_zero_infrastructure_batch_wires_the_right_carrier | — | — | — | §266/§267/the_zero_infrastructure_batch_wires_the_right_carrier |
| ring_of_the_snake | yes | the_zero_infrastructure_batch_wires_the_right_carrier | — | — | — | §266/§267/the_zero_infrastructure_batch_wires_the_right_carrier |
| runic_cube | yes | the_zero_infrastructure_batch_wires_the_right_carrier | — | — | — | §266/§267/the_zero_infrastructure_batch_wires_the_right_carrier |
| runic_pyramid | yes | the_zero_infrastructure_tail_wires_its_carriers | — | — | — | §267/§268/the_zero_infrastructure_tail_wires_its_carriers |
| self_forming_clay | yes | the_zero_infrastructure_tail_wires_its_carriers | — | — | — | §267/§268/the_zero_infrastructure_tail_wires_its_carriers |
| shovel | yes | campfire_options_follow_the_relics_the_wiki_names, dig_only_rolls_common_uncommon_or_rare | — | — | — | §259/campfire_options_follow_the_relics_the_wiki_names |
| shuriken | yes | the_every_nth_card_relics_wire_their_own_carrier | — | — | — | §261/§262/the_every_nth_card_relics_wire_their_own_carrier |
| slavers_collar | yes | the_kind_gated_relics_only_fire_in_their_own_kinds | — | — | — | §268/§269/the_kind_gated_relics_only_fire_in_their_own_kinds |
| sling_of_courage | yes | the_kind_gated_relics_only_fire_in_their_own_kinds | — | — | — | §268/§269/the_kind_gated_relics_only_fire_in_their_own_kinds |
| smiling_mask | yes | the_gold_and_shop_relics_change_only_their_own_number | — | — | — | §270/the_gold_and_shop_relics_change_only_their_own_number |
| snecko_skull | yes | the_status_application_relics_wire_their_own_carrier | — | — | — | §264/§265/the_status_application_relics_wire_their_own_carrier |
| sozu | yes | sozu_refuses_potions_at_both_doors | — | — | — | §271/sozu_refuses_potions_at_both_doors |
| ssserpent_head | yes | the_node_relics_pay_on_the_right_kind_of_room | — | — | — | §271/the_node_relics_pay_on_the_right_kind_of_room |
| stone_calendar | yes | the_eight_turn_shaped_relics_wire_their_own_status | — | — | — | §260/the_eight_turn_shaped_relics_wire_their_own_status |
| strawberry | yes | — | an_id_that_is_a_card_and_a_relic_is_not_an_encounter …(+5) | — | — | §156 |
| the_boot | yes | the_enemy_death_and_damage_rewrite_relics_wire_their_own_carrier | — | — | — | §262/§263/the_enemy_death_and_damage_rewrite_relics_wire_their_own_carrier |
| the_courier | yes | the_courier_restocks_the_slot_it_sells | — | — | — | §272/§273/the_courier_restocks_the_slot_it_sells |
| the_specimen | yes | the_enemy_death_and_damage_rewrite_relics_wire_their_own_carrier | — | — | — | §262/§263/the_enemy_death_and_damage_rewrite_relics_wire_their_own_carrier |
| thread_and_needle | yes | the_relic_pool_fires_at_the_three_hooks_it_has, an_elite_pays_a_relic_and_a_normal_fight_does_not | — | — | — | the_relic_pool_fires_at_the_three_hooks_it_has |
| tiny_chest | yes | tiny_chest_and_juzu_bracelet_change_the_roll | — | — | — | §271/§272/tiny_chest_and_juzu_bracelet_change_the_roll |
| torii | yes | the_enemy_death_and_damage_rewrite_relics_wire_their_own_carrier | — | — | — | §262/§263/the_enemy_death_and_damage_rewrite_relics_wire_their_own_carrier |
| toxic_egg | yes | the_add_card_relics_fire_at_the_one_add_point | — | — | — | §270/the_add_card_relics_fire_at_the_one_add_point |
| toy_ornithopter | yes | the_potion_relics_carry_their_own_numbers, drinking_a_potion_heals_five_with_the_toy_ornithopter | — | — | — | §271/the_potion_relics_carry_their_own_numbers |
| tungsten_rod | yes | the_enemy_death_and_damage_rewrite_relics_wire_their_own_carrier | — | — | — | §262/§263/the_enemy_death_and_damage_rewrite_relics_wire_their_own_carrier |
| turnip | yes | the_status_application_relics_wire_their_own_carrier | — | — | — | §264/§265/the_status_application_relics_wire_their_own_carrier |
| twisted_funnel | yes | the_status_application_relics_wire_their_own_carrier, the_status_application_relics_change_what_lands_on_the_target | — | — | — | §264/§265/the_status_application_relics_wire_their_own_carrier |
| unceasing_top | yes | the_zero_infrastructure_tail_wires_its_carriers | — | — | — | §267/§268/the_zero_infrastructure_tail_wires_its_carriers |
| vajra | yes | every_invariant_names_itself_when_violated, a_relic_you_already_hold_is_not_offered_again …(+5) | — | — | — | every_invariant_names_itself_when_violated |
| war_paint | yes | the_upgrade_eggs_upgrade_two_of_their_own_kind | — | — | — | §273/§274/the_upgrade_eggs_upgrade_two_of_their_own_kind |
| whetstone | yes | the_upgrade_eggs_upgrade_two_of_their_own_kind | — | — | — | §273/§274/the_upgrade_eggs_upgrade_two_of_their_own_kind |
| white_beast_statue | yes | — | an_id_that_is_a_card_and_a_relic_is_not_an_encounter …(+5) | — | — | §269 |

## 药水（33）

| Entity | Implemented | TestNamed | HarnessOnly | SourceTie | DeclaredDeviation | Evidence |
|---|---|---|---|---|---|---|
| ancient_potion | yes | the_potions_are_readable | — | — | — | the_potions_are_readable |
| attack_potion | yes | the_potions_are_readable, an_attack_potion_offers_three_definitions_and_creates_only_the_chosen_card …(+1) | — | — | — | the_potions_are_readable |
| blessing_of_the_forge | yes | the_potions_are_readable, blessing_of_the_forge_upgrades_every_strike_in_hand | — | — | — | the_potions_are_readable |
| block_potion | yes | the_potions_are_readable, dropping_a_potion_keeps_the_order_of_the_survivors …(+4) | — | — | — | the_potions_are_readable |
| blood_potion | yes | the_potions_are_readable, the_new_potion_shapes_all_do_something …(+1) | — | — | — | the_potions_are_readable |
| colorless_potion | yes | the_potions_are_readable, colorless_potion_offers_three_colorless_cards_and_the_pick_lands_in_hand | — | — | — | the_potions_are_readable |
| cultist_potion | yes | the_potions_are_readable | — | — | — | the_potions_are_readable |
| dexterity_potion | yes | the_potions_are_readable | — | — | — | the_potions_are_readable |
| distilled_chaos | yes | the_potions_are_readable, distilled_chaos_plays_the_top_three_for_free | — | — | — | the_potions_are_readable |
| duplication_potion | yes | the_potions_are_readable | — | — | — | the_potions_are_readable |
| elixir | yes | the_potions_are_readable, every_potion_in_the_table_classifies_as_known …(+1) | — | — | — | the_potions_are_readable |
| energy_potion | yes | the_potions_are_readable, potions_are_drawn_by_rarity_weight …(+3) | — | — | — | the_potions_are_readable |
| entropic_brew | yes | the_potions_are_readable, entropic_brew_fills_the_belt_after_freeing_its_own_slot | — | — | — | the_potions_are_readable |
| essence_of_steel | yes | the_potions_are_readable | — | — | — | the_potions_are_readable |
| explosive_potion | yes | the_potions_are_readable, the_new_potion_shapes_all_do_something | — | — | — | the_potions_are_readable |
| fairy_in_a_bottle | yes | the_potions_are_readable | — | — | — | the_potions_are_readable |
| fear_potion | yes | the_potions_are_readable | — | — | — | the_potions_are_readable |
| fire_potion | yes | the_potions_are_readable, the_same_state_hashes_the_same_and_a_change_moves_it …(+11) | — | — | — | the_potions_are_readable |
| flex_potion | yes | the_potions_are_readable, flex_potion_gives_strength_and_takes_it_back | — | — | — | the_potions_are_readable |
| fruit_juice | yes | the_potions_are_readable, fruit_juice_works_outside_a_fight | — | — | — | the_potions_are_readable |
| gamblers_brew | yes | the_potions_are_readable, every_potion_in_the_table_classifies_as_known …(+1) | — | — | — | the_potions_are_readable |
| heart_of_iron | yes | the_potions_are_readable | — | — | — | the_potions_are_readable |
| liquid_bronze | yes | the_potions_are_readable | — | — | — | the_potions_are_readable |
| liquid_memories | yes | the_potions_are_readable, liquid_memories_returns_a_card_and_makes_that_copy_free_once …(+1) | — | — | — | the_potions_are_readable |
| power_potion | yes | the_potions_are_readable, a_power_potion_offers_the_three_power_cards_and_they_are_real_powers …(+1) | — | — | — | the_potions_are_readable |
| regen_potion | yes | the_potions_are_readable, potions_are_drawn_by_rarity_weight | — | — | — | the_potions_are_readable |
| skill_potion | yes | the_potions_are_readable, every_potion_in_the_table_classifies_as_known | — | — | — | the_potions_are_readable |
| smoke_bomb | yes | the_potions_are_readable, smoke_bomb_ends_a_normal_fight_and_refuses_a_boss | — | — | — | the_potions_are_readable |
| snecko_oil | yes | the_potions_are_readable, snecko_oil_draws_five_and_randomizes_every_price_in_hand …(+1) | — | — | — | the_potions_are_readable |
| speed_potion | yes | the_potions_are_readable | — | — | — | the_potions_are_readable |
| strength_potion | yes | the_potions_are_readable, the_new_potion_shapes_all_do_something | — | — | — | the_potions_are_readable |
| swift_potion | yes | the_potions_are_readable, the_new_potion_shapes_all_do_something …(+1) | — | — | — | the_potions_are_readable |
| weak_potion | yes | the_potions_are_readable, the_new_potion_shapes_all_do_something | — | — | — | the_potions_are_readable |
