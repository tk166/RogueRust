# 覆盖矩阵（**生成物，别手改**）

> 生成：`python -X utf8 native/coverage_matrix.py`；校验：`... --check`（闸门 13 就是它）。
> 手改这一页会让闸门红 —— 这是故意的：一张"人维护的覆盖表"活不过下一次内容变更。

回答一个问题：**每一个实体（怪/动作/卡/状态/遭遇/事件/遗物/药水）被验证到哪里了？**
下面这张 535 行的表靠记性是维护不了的，所以每一列都是派生的（口径见 `native/coverage_matrix.py` 顶部）：

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
| 怪物 | 47 | 33 | 0 | 14 | 47 | 0 | 11 | 0 |
| 敌人动作 | 130 | 59 | 71 | 0 | 130 | 0 | 51 | 0 |
| 卡牌 | 209 | 128 | 81 | 0 | 199 | 10 | 18 | 0 |
| 状态 | 56 | 52 | 2 | 2 | 0 | 56 | 1 | 0 |
| 遭遇 | 34 | 25 | 9 | 0 | 0 | 0 | 0 | 0 |
| 事件 | 11 | 11 | 0 | 0 | 0 | 0 | 0 | 0 |
| 遗物 | 15 | 11 | 4 | 0 | 0 | 0 | 0 | 0 |
| 药水 | 33 | 33 | 0 | 0 | 0 | 0 | 0 | 0 |
| **合计** | 535 | 352 | 167 | 16 | 376 | 66 | 81 | 0 |

扫描到的具名测试：**963** 条；wiki dump：**45** 份（其中 47 只怪有 dump）。

事件：池里有 **14** 个位次、**11** 个不同 id（`golden_idol` / `ancient_forge` / `purification_shrine` 跨幕复用）。

同一页面的早期副本（内容同源，矩阵只用 `wiki_asc/` 那一份）：`wiki_book_of_stabbing.txt`、`wiki_lagavulin.txt`、`wiki_nemesis.txt`、`wiki_reptomancer.txt`、`wiki_slavers.txt`、`wiki_taskmaster.txt`

## 怪物（47）

| Entity | Implemented | TestNamed | HarnessOnly | SourceTie | DeclaredDeviation | Evidence |
|---|---|---|---|---|---|---|
| acid_slime_m | yes | a_split_spawns_two_combatants_when_the_boss_dies, a_spawned_combatant_still_resolves_to_its_enemy_record | — | wiki:wiki_asc/acid_slime.txt | — | INV_ASC_HP+INV_MONSTERS/a_split_spawns_two_combatants_when_the_boss_dies |
| acid_slime_s | orphan (declared) | — | — | wiki:wiki_asc/acid_slime.txt | — | INV_ASC_HP+INV_MONSTERS |
| awakened_one | yes | the_awakened_one_survives_its_first_death_and_then_really_dies, the_awakened_one_draws_phase_one_by_weight_and_flips_on_the_guard …(+3) | — | wiki:wiki_asc/awakened_one.txt | gap §H: 二阶段"不能连续三次 Tackle/Sludge"未做（规则预算 8 条已满）；Regenerate/Curiosity 层数不随 A19 变 | §195.8/INV_ASC_HP+INV_MONSTERS/the_awakened_one_survives_its_first_death_and_then_really_dies |
| blue_slaver | yes | a_round_one_rule_beats_the_cycle_and_the_cycle_takes_over_after_it | — | wiki:wiki_asc/slavers.txt | — | INV_ASC_HP+INV_MONSTERS/a_round_one_rule_beats_the_cycle_and_the_cycle_takes_over_after_it |
| book_of_stabbing | yes | — | — | wiki:wiki_asc/book_of_stabbing.txt | — | §173/INV_ASC_HP+INV_MONSTERS |
| bronze_automaton | yes | stasis_steals_the_best_card_and_returns_it_when_the_orb_dies, a_96_card_pile_still_reaches_the_best_card_at_the_end …(+5) | — | wiki:wiki_asc/bronze_automaton.txt | gap §H: Orb 的 `Stasis` 用"最高稀有度"（并列随机），与 wiki 一致；"同一招不能三次"已做 | §138/§194/INV_ASC_HP+INV_MONSTERS/stasis_steals_the_best_card_and_returns_it_when_the_orb_dies |
| bronze_orb | yes | a_weighted_boss_never_repeats_the_move_the_wiki_forbids, a_minion_is_not_on_the_field_until_its_summon_lands …(+1) | — | wiki:wiki_asc/bronze_automaton.txt | gap §H: Orb 的 `Stasis` 用"最高稀有度"（并列随机），与 wiki 一致；"同一招不能三次"已做 | §194/§195.6/INV_ASC_HP+INV_MONSTERS/a_weighted_boss_never_repeats_the_move_the_wiki_forbids |
| byrd | yes | flying_halves_attack_damage_and_loses_a_stack_per_hit | — | wiki:wiki_asc/byrd.txt | — | §208/§213/INV_ASC_HP+INV_MONSTERS/flying_halves_attack_damage_and_loses_a_stack_per_hit |
| chosen | yes | hex_shuffles_a_dazed_only_for_non_attack_cards, chosen_swaps_its_opener_at_a17 …(+1) | — | wiki:wiki_asc/chosen.txt | — | §130/§213/INV_ASC_HP+INV_MONSTERS/hex_shuffles_a_dazed_only_for_non_attack_cards |
| cultist | yes | building_a_fight_keeps_the_ascension_but_not_the_last_fights_gold, a_fight_built_from_the_content_deck_can_play_a_strike …(+6) | — | wiki:wiki_asc/cultist.txt | — | §5.2/§195.8/INV_ASC_HP+INV_MONSTERS/building_a_fight_keeps_the_ascension_but_not_the_last_fights_gold |
| dagger | yes | — | — | wiki:wiki_asc/dagger.txt | — | §175/INV_ASC_HP+INV_MONSTERS |
| darkling | yes | an_encounter_with_two_records_of_the_same_id_builds | — | wiki:wiki_asc/darkling.txt | — | §129/§137/INV_ASC_HP+INV_MONSTERS+INV_ROLLS/an_encounter_with_two_records_of_the_same_id_builds |
| deca | yes | donus_circle_of_power_buffs_the_enemy_team_and_not_the_player | — | wiki:wiki_asc/donu_and_deca.txt | gap §H: Artifact 层数不随 A19 变（`StartingStatuses` 没有升档轴） | §195.8/INV_ASC_HP+INV_MONSTERS/donus_circle_of_power_buffs_the_enemy_team_and_not_the_player |
| donu | yes | donus_circle_of_power_buffs_the_enemy_team_and_not_the_player | — | wiki:wiki_asc/donu_and_deca.txt | gap §H: Artifact 层数不随 A19 变（`StartingStatuses` 没有升档轴） | §195.8/INV_ASC_HP+INV_MONSTERS/donus_circle_of_power_buffs_the_enemy_team_and_not_the_player |
| fat_gremlin | yes | — | — | wiki:wiki_asc/fat_gremlin.txt | — | §138/§214/INV_ASC_HP+INV_MONSTERS |
| fungi_beast | yes | act_two_fights_act_two_enemies | — | wiki:wiki_asc/fungi_beast.txt | — | §152/INV_ASC_HP+INV_MONSTERS/act_two_fights_act_two_enemies |
| giant_head | yes | giant_head_counts_down_then_only_its_time, it_is_time_escalates_by_five_and_respects_its_cap | — | wiki:wiki_asc/giant_head.txt | — | §134/§211/INV_ASC_HP+INV_MONSTERS+INV_SPAWN_COUNTERS/giant_head_counts_down_then_only_its_time |
| gremlin_leader | yes | the_summon_cap_is_a_loud_failure | — | wiki:wiki_asc/gremlin_leader.txt | — | §134/§212/INV_ASC_HP+INV_MONSTERS/the_summon_cap_is_a_loud_failure |
| gremlin_nob | yes | — | — | wiki:wiki_asc/gremlin_nob.txt | — | §152/INV_ASC_HP+INV_MONSTERS |
| gremlin_wizard | yes | — | — | wiki:wiki_asc/gremlin_wizard.txt | — | §130/§138/INV_ASC_HP+INV_MONSTERS |
| hexaghost | yes | hexaghost_plays_the_wikis_seven_move_pattern_after_its_two_openers, the_boss_is_offered_at_floor_16_and_clears_the_act | — | wiki:wiki_asc/hexaghost.txt | gap §H: Sear 后续塞的 Burn 不自动升级（wiki："for the rest of combat"）；Divider 读结算时 HP | INV_ASC_HP+INV_MONSTERS/hexaghost_plays_the_wikis_seven_move_pattern_after_its_two_openers |
| jaw_worm | yes | spot_weakness_follows_the_enemy_intent, a_jaw_worm_starts_with_block_and_a17_makes_it_bigger …(+1) | — | wiki:wiki_asc/jaw_worm.txt | — | §5.2/INV_ASC_HP+INV_MONSTERS/spot_weakness_follows_the_enemy_intent |
| lagavulin | yes | an_elite_node_fights_the_sentries_and_pays_the_elite_tier | — | wiki:wiki_asc/lagavulin.txt | — | §173/INV_ASC_HP+INV_MONSTERS/an_elite_node_fights_the_sentries_and_pays_the_elite_tier |
| looter | yes | ascension_two_makes_the_looter_mug_hit_for_eleven, a_looter_steals_thievery_gold_on_every_attack_and_carries_it_away …(+4) | — | wiki:wiki_asc/thieves.txt | — | §175/§201/INV_ASC_HP+INV_MONSTERS/ascension_two_makes_the_looter_mug_hit_for_eleven |
| louse_green | orphan (declared) | — | — | wiki:wiki_asc/louses.txt | — | §152/INV_ASC_HP+INV_MONSTERS |
| louse_red | yes | a_spawn_roll_is_drawn_once_per_fight_and_read_by_the_action, an_encounter_without_rolls_draws_nothing …(+2) | — | wiki:wiki_asc/louses.txt | — | §152/§209/INV_ASC_HP+INV_MONSTERS+INV_ROLLS/a_spawn_roll_is_drawn_once_per_fight_and_read_by_the_action |
| maw | yes | nom_nom_hits_five_damage_ceil_round_over_two_times, the_maw_follows_the_wikis_transition_table | — | wiki:wiki_asc/the_maw.txt | 无 AscHP：wiki The Maw: max HP does not change with ascension | §207/§212/INV_MONSTERS+INV_NO_ASC_HP/nom_nom_hits_five_damage_ceil_round_over_two_times |
| nemesis | yes | — | — | wiki:wiki_asc/nemesis.txt | — | §175/INV_ASC_HP+INV_MONSTERS |
| orb_walker | yes | — | — | wiki:wiki_asc/orb_walker.txt | — | §208/§214/INV_ASC_HP+INV_MONSTERS |
| reptomancer | yes | — | — | wiki:wiki_asc/reptomancer.txt | — | §175/INV_ASC_HP+INV_MONSTERS |
| sentry_1 | yes | a_turn_boundary_leaves_no_chain_referenced, dexterity_from_the_content_scales_a_real_defend …(+2) | — | wiki:wiki_asc/sentry.txt | — | §4.2/§134/INV_ASC_HP+INV_MONSTERS/a_turn_boundary_leaves_no_chain_referenced |
| sentry_2 | yes | a_long_fight_never_reports_a_step_problem | — | wiki:wiki_asc/sentry.txt | — | §4.2/§134/INV_ASC_HP+INV_MONSTERS/a_long_fight_never_reports_a_step_problem |
| sentry_3 | yes | a_long_fight_never_reports_a_step_problem | — | wiki:wiki_asc/sentry.txt | — | §134/INV_ASC_HP+INV_MONSTERS/a_long_fight_never_reports_a_step_problem |
| shelled_parasite | yes | act_two_fights_act_two_enemies | — | wiki:wiki_asc/shelled_parasite.txt | — | §130/INV_ASC_HP+INV_MONSTERS/act_two_fights_act_two_enemies |
| slaver_red | yes | — | — | wiki:wiki_asc/slavers.txt | — | §152/INV_ASC_HP+INV_MONSTERS |
| slime_boss | yes | a_phase_split_happens_once_even_under_three_hits, the_boss_is_offered_at_floor_16_and_clears_the_act | — | wiki:wiki_asc/slime_boss.txt | — | §4.3/INV_ASC_HP+INV_MONSTERS/a_phase_split_happens_once_even_under_three_hits |
| sneaky_gremlin | yes | — | — | wiki:wiki_asc/sneaky_gremlin.txt | — | §130/§138/INV_ASC_HP+INV_MONSTERS |
| spike_slime_m | orphan (declared) | — | — | wiki:wiki_asc/spike_slime.txt | — | INV_ASC_HP+INV_MONSTERS |
| spike_slime_s | yes | a_minion_flees_when_its_master_falls, the_summon_cap_is_a_loud_failure | — | wiki:wiki_asc/spike_slime.txt | — | INV_ASC_HP+INV_MONSTERS/a_minion_flees_when_its_master_falls |
| spiker | yes | spiker_never_repeats_its_attack_and_buffs_thorns_at_most_six_times, starting_statuses_follow_their_ascension_rows | — | wiki:wiki_asc/shapes.txt | — | §207/§214/INV_ASC_HP+INV_MONSTERS/spiker_never_repeats_its_attack_and_buffs_thorns_at_most_six_times |
| spire_growth | yes | spire_growth_smashes_instead_of_choosing | — | wiki:wiki_asc/spire_growth.txt | — | §148/§214/INV_ASC_HP+INV_MONSTERS/spire_growth_smashes_instead_of_choosing |
| taskmaster | yes | — | — | wiki:wiki_asc/taskmaster.txt | — | INV_ASC_HP+INV_MONSTERS |
| the_champ | yes | a_weighted_boss_never_repeats_the_move_the_wiki_forbids, the_champ_taunts_every_fourth_round_and_enters_phase_two_below_half …(+1) | — | wiki:wiki_asc/the_champ.txt | gap §H: A19 的 "Gloat 换成 Defensive Stance" 未实现；Anger 按名清 debuff；第二阶段只做第一次 Execute | §194/INV_ASC_HP+INV_MONSTERS/a_weighted_boss_never_repeats_the_move_the_wiki_forbids |
| the_collector | yes | the_collector_draws_by_weight_and_never_buffs_twice_in_a_row, a_minion_is_not_on_the_field_until_its_summon_lands | — | wiki:wiki_asc/the_collector.txt | gap §H: 25/45/30（0-1 只 Torch Head 时的权重）未分档 | §138/INV_ASC_HP+INV_MONSTERS/the_collector_draws_by_weight_and_never_buffs_twice_in_a_row |
| the_guardian | yes | mode_shift_is_a_budget_drained_by_the_health_actually_lost, building_a_guardian_fight_seeds_its_mode_shift_budget_by_ascension …(+1) | — | wiki:wiki_asc/the_guardian.txt | — | §194/INV_ASC_HP+INV_MONSTERS+INV_SPAWN_COUNTERS/mode_shift_is_a_budget_drained_by_the_health_actually_lost |
| time_eater | yes | a_weighted_boss_never_repeats_the_move_the_wiki_forbids | — | wiki:wiki_asc/time_eater.txt | gap §H: Haste 不清 debuff（没有"清空状态"节点）；`Draw Reduction` 已实现但 wiki 的"A19 另加 2 Slimed"没做 | §138/§211/INV_ASC_HP+INV_MONSTERS/a_weighted_boss_never_repeats_the_move_the_wiki_forbids |
| torch_head | yes | a_minion_is_not_on_the_field_until_its_summon_lands | — | wiki:wiki_asc/torch_head.txt | gap §H: 25/45/30（0-1 只 Torch Head 时的权重）未分档 | §138/§195.3/INV_ASC_HP+INV_MONSTERS/a_minion_is_not_on_the_field_until_its_summon_lands |

## 敌人动作（130）

| Entity | Implemented | TestNamed | HarnessOnly | SourceTie | DeclaredDeviation | Evidence |
|---|---|---|---|---|---|---|
| acid_slime_m.corrosive_spit | yes | — | ENEMY_DIFF | wiki:wiki_asc/acid_slime.txt (via acid_slime_m) | — | §192/INV_ACTIONS+INV_ASC_VARIANTS |
| acid_slime_m.lick | yes | — | ENEMY_DIFF | wiki:wiki_asc/acid_slime.txt (via acid_slime_m) · 仅基础值 | 无升档：wiki Acid Slime: M Lick is 1 Weak, no A-row | §206/INV_ACTIONS+INV_NO_ASC |
| acid_slime_m.tackle | yes | — | ENEMY_DIFF | wiki:wiki_asc/acid_slime.txt (via acid_slime_m) | — | §192/INV_ACTIONS+INV_ASC_VARIANTS |
| acid_slime_s.lick | yes | — | ENEMY_DIFF | wiki:wiki_asc/acid_slime.txt (via acid_slime_s) · 仅基础值 | 无升档：wiki Acid Slime: S Lick is 1 Weak, no A-row | §206/INV_ACTIONS+INV_NO_ASC |
| acid_slime_s.tackle | yes | — | ENEMY_DIFF | wiki:wiki_asc/acid_slime.txt (via acid_slime_s) | — | INV_ACTIONS+INV_ASC_VARIANTS |
| awakened_one.dark_echo | yes | the_awakened_one_draws_phase_one_by_weight_and_flips_on_the_guard | — | wiki:wiki_asc/awakened_one.txt (via awakened_one) · 仅基础值 | 无升档：wiki Awakened One: no A-row on moves | INV_ACTIONS+INV_NO_ASC/the_awakened_one_draws_phase_one_by_weight_and_flips_on_the_guard |
| awakened_one.rebirth | yes | the_awakened_one_survives_its_first_death_and_then_really_dies, the_awakened_one_draws_phase_one_by_weight_and_flips_on_the_guard | — | wiki:wiki_asc/awakened_one.txt (via awakened_one) · 仅基础值 | 无升档：wiki Awakened One: Rebirth is a rule, no numbers | INV_ACTIONS+INV_NO_ASC/the_awakened_one_survives_its_first_death_and_then_really_dies |
| awakened_one.slash | yes | the_awakened_one_draws_phase_one_by_weight_and_flips_on_the_guard | — | wiki:wiki_asc/awakened_one.txt (via awakened_one) · 仅基础值 | 无升档：wiki Awakened One: no A-row on moves | INV_ACTIONS+INV_NO_ASC/the_awakened_one_draws_phase_one_by_weight_and_flips_on_the_guard |
| awakened_one.sludge | yes | the_awakened_one_draws_phase_one_by_weight_and_flips_on_the_guard | — | wiki:wiki_asc/awakened_one.txt (via awakened_one) · 仅基础值 | 无升档：wiki Awakened One: no A-row on moves | INV_ACTIONS+INV_NO_ASC/the_awakened_one_draws_phase_one_by_weight_and_flips_on_the_guard |
| awakened_one.soul_strike | yes | the_awakened_one_draws_phase_one_by_weight_and_flips_on_the_guard | — | wiki:wiki_asc/awakened_one.txt (via awakened_one) · 仅基础值 | 无升档：wiki Awakened One: no A-row on moves | INV_ACTIONS+INV_NO_ASC/the_awakened_one_draws_phase_one_by_weight_and_flips_on_the_guard |
| awakened_one.tackle | yes | the_awakened_one_draws_phase_one_by_weight_and_flips_on_the_guard | — | wiki:wiki_asc/awakened_one.txt (via awakened_one) · 仅基础值 | 无升档：wiki Awakened One: no A-row on moves | INV_ACTIONS+INV_NO_ASC/the_awakened_one_draws_phase_one_by_weight_and_flips_on_the_guard |
| blue_slaver.rake | yes | a_round_one_rule_beats_the_cycle_and_the_cycle_takes_over_after_it | — | wiki:wiki_asc/slavers.txt (via blue_slaver) | — | INV_ACTIONS+INV_ASC_VARIANTS/a_round_one_rule_beats_the_cycle_and_the_cycle_takes_over_after_it |
| blue_slaver.stab | yes | a_round_one_rule_beats_the_cycle_and_the_cycle_takes_over_after_it | — | wiki:wiki_asc/slavers.txt (via blue_slaver) | — | INV_ACTIONS+INV_ASC_VARIANTS/a_round_one_rule_beats_the_cycle_and_the_cycle_takes_over_after_it |
| book_of_stabbing.big_stab | yes | — | ENEMY_DIFF | wiki:wiki_asc/book_of_stabbing.txt (via book_of_stabbing) | — | INV_ACTIONS+INV_ASC_VARIANTS |
| book_of_stabbing.multi_stab | yes | — | ENEMY_DIFF | wiki:wiki_asc/book_of_stabbing.txt (via book_of_stabbing) | — | INV_ACTIONS+INV_ASC_VARIANTS |
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
| chosen.debilitate | yes | — | ENEMY_DIFF | wiki:wiki_asc/chosen.txt (via chosen) | — | §204/§213/INV_ACTIONS+INV_ASC_VARIANTS |
| chosen.drain | yes | — | ENEMY_DIFF | wiki:wiki_asc/chosen.txt (via chosen) · 仅基础值 | 无升档：wiki Chosen: Drain is 3 Weak + 3 Strength, no A-row | §212/§213/INV_ACTIONS+INV_NO_ASC |
| chosen.hex | yes | chosen_swaps_its_opener_at_a17 | — | wiki:wiki_asc/chosen.txt (via chosen) · 仅基础值 | 无升档：wiki Chosen: Hex applies the Hex debuff, no A-row | §212/§213/INV_ACTIONS+INV_NO_ASC/chosen_swaps_its_opener_at_a17 |
| chosen.poke | yes | chosen_swaps_its_opener_at_a17 | — | wiki:wiki_asc/chosen.txt (via chosen) | — | §204/§213/INV_ACTIONS+INV_ASC_VARIANTS/chosen_swaps_its_opener_at_a17 |
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
| fungi_beast.bite | yes | — | ENEMY_DIFF | wiki:wiki_asc/fungi_beast.txt (via fungi_beast) · 仅基础值 | 无升档：wiki Fungi Beast: Bite has no A-row | §152/INV_ACTIONS+INV_NO_ASC |
| fungi_beast.grow | yes | — | ENEMY_DIFF | wiki:wiki_asc/fungi_beast.txt (via fungi_beast) | — | §152/INV_ACTIONS+INV_ASC_VARIANTS |
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
| jaw_worm.bellow | yes | one_action_can_carry_two_ascension_tiers | — | wiki:wiki_asc/jaw_worm.txt (via jaw_worm) | — | INV_ACTIONS+INV_ASC_VARIANTS/one_action_can_carry_two_ascension_tiers |
| jaw_worm.chomp | yes | — | ENEMY_DIFF | wiki:wiki_asc/jaw_worm.txt (via jaw_worm) | — | INV_ACTIONS+INV_ASC_VARIANTS |
| jaw_worm.thrash | yes | — | ENEMY_DIFF | wiki:wiki_asc/jaw_worm.txt (via jaw_worm) · 仅基础值 | 无升档：wiki Jaw Worm: Thrash has no A-row | INV_ACTIONS+INV_NO_ASC |
| lagavulin.attack | yes | an_ascension_variant_replaces_the_program_at_its_threshold | — | wiki:wiki_asc/lagavulin.txt (via lagavulin) | — | §173/INV_ACTIONS+INV_ASC_VARIANTS/an_ascension_variant_replaces_the_program_at_its_threshold |
| lagavulin.siphon_soul | yes | an_ascension_variant_is_picked_on_the_threshold_and_only_changes_its_number | — | wiki:wiki_asc/lagavulin.txt (via lagavulin) | — | §174/§204/INV_ACTIONS+INV_ASC_VARIANTS/an_ascension_variant_is_picked_on_the_threshold_and_only_changes_its_number |
| lagavulin.sleep | yes | — | ENEMY_DIFF | wiki:wiki_asc/lagavulin.txt (via lagavulin) · 仅基础值 | 无升档：wiki Lagavulin: Sleep does nothing | §173/§193/INV_ACTIONS+INV_NO_ASC |
| looter.escape | yes | a_looter_steals_thievery_gold_on_every_attack_and_carries_it_away, escaping_moves_the_counter_instead_of_copying_it …(+1) | — | wiki:wiki_asc/thieves.txt (via looter) · 仅基础值 | 无升档：wiki Thieves: Escape has no numbers | §201/INV_ACTIONS+INV_NO_ASC/a_looter_steals_thievery_gold_on_every_attack_and_carries_it_away |
| looter.lunge | yes | an_ascension_variant_is_picked_on_the_threshold_and_only_changes_its_number, the_looter_mugs_twice_then_bombs_then_escapes | — | wiki:wiki_asc/thieves.txt (via looter) | — | §201/INV_ACTIONS+INV_ASC_VARIANTS/an_ascension_variant_is_picked_on_the_threshold_and_only_changes_its_number |
| looter.mug | yes | ascension_two_makes_the_looter_mug_hit_for_eleven, a_looter_steals_thievery_gold_on_every_attack_and_carries_it_away …(+3) | — | wiki:wiki_asc/thieves.txt (via looter) | — | §201/§205/INV_ACTIONS+INV_ASC_VARIANTS/ascension_two_makes_the_looter_mug_hit_for_eleven |
| looter.smoke_bomb | yes | the_looter_mugs_twice_then_bombs_then_escapes | — | wiki:wiki_asc/thieves.txt (via looter) · 仅基础值 | 无升档：wiki Thieves: 6 Block, no A-row | §201/INV_ACTIONS+INV_NO_ASC/the_looter_mugs_twice_then_bombs_then_escapes |
| louse_green.bite | yes | — | ENEMY_DIFF | wiki:wiki_asc/louses.txt (via louse_green) · 仅基础值 | unwired：没有敌人记录列出它（`INV_UNWIRED`）；无升档：wiki Louses: Bite is rolled at spawn (A2 changes the roll, §193) | §152/§193/INV_ACTIONS+INV_NO_ASC |
| louse_green.grow | yes | — | ENEMY_DIFF | wiki:wiki_asc/louses.txt (via louse_green) | unwired：没有敌人记录列出它（`INV_UNWIRED`） | §152/§193/INV_ACTIONS+INV_ASC_VARIANTS |
| louse_red.bite | yes | a_spawn_roll_is_drawn_once_per_fight_and_read_by_the_action | — | wiki:wiki_asc/louses.txt (via louse_red) · 仅基础值 | 无升档：wiki Louses: Bite is rolled at spawn (A2 changes the roll, §193) | §152/§193/INV_ACTIONS+INV_NO_ASC/a_spawn_roll_is_drawn_once_per_fight_and_read_by_the_action |
| louse_red.grow | yes | — | ENEMY_DIFF | wiki:wiki_asc/louses.txt (via louse_red) | — | §152/§193/INV_ACTIONS+INV_ASC_VARIANTS |
| louse_red.spit_web | yes | — | ENEMY_DIFF | wiki:wiki_asc/louses.txt (via louse_red) · 仅基础值 | 无升档：wiki Louses: Spit Web is 2 Weak, no A-row | §152/§193/INV_ACTIONS+INV_NO_ASC |
| maw.drool | yes | the_maw_follows_the_wikis_transition_table | — | wiki:wiki_asc/the_maw.txt (via maw) | — | §137/§212/INV_ACTIONS+INV_ASC_VARIANTS/the_maw_follows_the_wikis_transition_table |
| maw.nom_nom | yes | nom_nom_hits_five_damage_ceil_round_over_two_times, the_maw_follows_the_wikis_transition_table | — | wiki:wiki_asc/the_maw.txt (via maw) · 仅基础值 | 无升档：wiki The Maw: Nom Nom is 5 x ceil(turn/2), no A-row | §137/§212/INV_ACTIONS+INV_NO_ASC/nom_nom_hits_five_damage_ceil_round_over_two_times |
| maw.roar | yes | the_maw_follows_the_wikis_transition_table | — | wiki:wiki_asc/the_maw.txt (via maw) | — | §137/§212/INV_ACTIONS+INV_ASC_VARIANTS/the_maw_follows_the_wikis_transition_table |
| maw.slam | yes | the_maw_follows_the_wikis_transition_table | — | wiki:wiki_asc/the_maw.txt (via maw) | — | §137/§212/INV_ACTIONS+INV_ASC_VARIANTS/the_maw_follows_the_wikis_transition_table |
| nemesis.scythe | yes | — | ENEMY_DIFF | wiki:wiki_asc/nemesis.txt (via nemesis) · 仅基础值 | 无升档：wiki Nemesis: Scythe has no A-row | §175/INV_ACTIONS+INV_NO_ASC |
| nemesis.tri_attack | yes | — | ENEMY_DIFF | wiki:wiki_asc/nemesis.txt (via nemesis) | — | §175/INV_ACTIONS+INV_ASC_VARIANTS |
| nemesis.tri_burn | yes | — | ENEMY_DIFF | wiki:wiki_asc/nemesis.txt (via nemesis) | — | §175/INV_ACTIONS+INV_ASC_VARIANTS |
| orb_walker.claw | yes | — | ENEMY_DIFF | wiki:wiki_asc/orb_walker.txt (via orb_walker) | — | §214/INV_ACTIONS+INV_ASC_VARIANTS |
| orb_walker.laser | yes | — | ENEMY_DIFF | wiki:wiki_asc/orb_walker.txt (via orb_walker) | — | §214/INV_ACTIONS+INV_ASC_VARIANTS |
| reptomancer.big_bite | yes | — | ENEMY_DIFF | wiki:wiki_asc/reptomancer.txt (via reptomancer) | — | §175/INV_ACTIONS+INV_ASC_VARIANTS |
| reptomancer.snake_strike | yes | — | ENEMY_DIFF | wiki:wiki_asc/reptomancer.txt (via reptomancer) | — | §175/INV_ACTIONS+INV_ASC_VARIANTS |
| reptomancer.spawn_dagger | yes | — | ENEMY_DIFF | wiki:wiki_asc/reptomancer.txt (via reptomancer) | — | §175/INV_ACTIONS+INV_ASC_VARIANTS |
| sentry.beam | yes | — | ENEMY_DIFF | wiki:wiki_asc/sentry.txt (via sentry_1) | — | §4.2/INV_ACTIONS+INV_ASC_VARIANTS |
| sentry.bolt | yes | — | ENEMY_DIFF | wiki:wiki_asc/sentry.txt (via sentry_1) | — | §4.2/INV_ACTIONS+INV_ASC_VARIANTS |
| shelled_parasite.double_strike | yes | — | ENEMY_DIFF | wiki:wiki_asc/shelled_parasite.txt (via shelled_parasite) | — | §130/INV_ACTIONS+INV_ASC_VARIANTS |
| shelled_parasite.suck | yes | — | ENEMY_DIFF | wiki:wiki_asc/shelled_parasite.txt (via shelled_parasite) | — | §130/INV_ACTIONS+INV_ASC_VARIANTS |
| slaver_red.entangle | yes | — | ENEMY_DIFF | wiki:wiki_asc/slavers.txt (via slaver_red) · 仅基础值 | 无升档：wiki Slavers: Entangle applies a status, no A-row | §152/§196/INV_ACTIONS+INV_NO_ASC |
| slaver_red.scrape | yes | — | ENEMY_DIFF | wiki:wiki_asc/slavers.txt (via slaver_red) | — | §186/§187/INV_ACTIONS+INV_ASC_VARIANTS |
| slaver_red.stab | yes | — | ENEMY_DIFF | wiki:wiki_asc/slavers.txt (via slaver_red) | — | §152/§196/INV_ACTIONS+INV_ASC_VARIANTS |
| slime_boss.goop_spray | yes | — | ENEMY_DIFF | wiki:wiki_asc/slime_boss.txt (via slime_boss) | — | §4.3/INV_ACTIONS+INV_ASC_VARIANTS |
| slime_boss.preparing | yes | — | ENEMY_DIFF | wiki:wiki_asc/slime_boss.txt (via slime_boss) · 仅基础值 | 无升档：wiki Slime Boss: Preparing has no numbers | §4.3/INV_ACTIONS+INV_NO_ASC |
| slime_boss.slam | yes | a_combinator_rule_switches_the_boss_move | — | wiki:wiki_asc/slime_boss.txt (via slime_boss) | — | §4.3/INV_ACTIONS+INV_ASC_VARIANTS/a_combinator_rule_switches_the_boss_move |
| sneaky_gremlin.puncture | yes | — | ENEMY_DIFF | wiki:wiki_asc/sneaky_gremlin.txt (via sneaky_gremlin) | — | INV_ACTIONS+INV_ASC_VARIANTS |
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
| time_eater.head_slam | yes | a_weighted_boss_never_repeats_the_move_the_wiki_forbids | — | wiki:wiki_asc/time_eater.txt (via time_eater) | — | §195.7/INV_ACTIONS+INV_ASC_VARIANTS/a_weighted_boss_never_repeats_the_move_the_wiki_forbids |
| time_eater.reverberate | yes | a_weighted_boss_never_repeats_the_move_the_wiki_forbids | — | wiki:wiki_asc/time_eater.txt (via time_eater) | — | §194/INV_ACTIONS+INV_ASC_VARIANTS/a_weighted_boss_never_repeats_the_move_the_wiki_forbids |
| time_eater.ripple | yes | a_weighted_boss_never_repeats_the_move_the_wiki_forbids | — | wiki:wiki_asc/time_eater.txt (via time_eater) | — | §195.7/INV_ACTIONS+INV_ASC_VARIANTS/a_weighted_boss_never_repeats_the_move_the_wiki_forbids |
| torch_head.tackle | yes | — | ENEMY_DIFF | wiki:wiki_asc/torch_head.txt (via torch_head) · 仅基础值 | 无升档：wiki Torch Head: Tackle is 7, no A-row | INV_ACTIONS+INV_NO_ASC |

## 卡牌（209）

| Entity | Implemented | TestNamed | HarnessOnly | SourceTie | DeclaredDeviation | Evidence |
|---|---|---|---|---|---|---|
| anger | yes | warcry_draws_one_then_puts_the_chosen_card_on_top, perfected_strike_counts_the_tagged_cards_in_hand …(+8) | — | wiki:wiki_cards/anger.txt | — | CARD_WIKI+INV_CARDS/warcry_draws_one_then_puts_the_chosen_card_on_top |
| anger+ | yes | — | CARD_DIFF | wiki:wiki_cards/anger.txt (via anger) | — | INV_CARDS |
| apparition | yes | a_special_card_is_known_and_never_put_in_a_reward | — | wiki:wiki_cards/apparition.txt | — | §149/§223/CARD_WIKI+INV_CARDS/a_special_card_is_known_and_never_put_in_a_reward |
| apparition+ | yes | — | CARD_DIFF | wiki:wiki_cards/apparition.txt (via apparition) | — | INV_CARDS |
| armaments | yes | armaments_gains_block_then_upgrades_the_chosen_card, an_armaments_question_makes_the_page_layer_modal | — | wiki:wiki_cards/armaments.txt | — | §227/CARD_WIKI+INV_CARDS/armaments_gains_block_then_upgrades_the_chosen_card |
| armaments+ | yes | armaments_gains_block_then_upgrades_the_chosen_card | — | wiki:wiki_cards/armaments.txt (via armaments) | — | INV_CARDS/armaments_gains_block_then_upgrades_the_chosen_card |
| ascenders_bane | yes | — | CARD_DIFF | wiki:wiki_cards/ascenders_bane.txt | — | §183/§189/CARD_WIKI+INV_CARDS |
| bandage_up | yes | exhaust_on_play_is_a_zone_and_the_cards_that_use_it_are_playable, colorless_potion_offers_three_colorless_cards_and_the_pick_lands_in_hand | — | wiki:wiki_cards/bandage_up.txt | wiki 偏差：wiki 升级版治疗 6；内容没有 `bandage_up+` 这一行。（`Exhaust` 本身不是偏差：§219 起它由落区 `PlayedCardDestinationZone` 表达。） | §191/CARD_WIKI+INV_CARDS/exhaust_on_play_is_a_zone_and_the_cards_that_use_it_are_playable |
| barricade | yes | — | CARD_DIFF | wiki:wiki_cards/barricade.txt | — | CARD_WIKI+INV_CARDS |
| barricade+ | yes | — | CARD_DIFF | wiki:wiki_cards/barricade.txt (via barricade) | — | INV_CARDS |
| bash | yes | card_rarity_is_readable_and_the_schema_moved_the_version, warcry_draws_one_then_puts_the_chosen_card_on_top …(+11) | — | wiki:wiki_cards/bash.txt | — | §2/§2.1/CARD_WIKI+INV_CARDS/card_rarity_is_readable_and_the_schema_moved_the_version |
| bash+ | yes | — | CARD_DIFF | wiki:wiki_cards/bash.txt (via bash) | — | INV_CARDS |
| battle_trance | yes | battle_trance_blocks_further_draws_only_this_turn, the_ten_cards_added_in_221_do_what_the_wiki_says | — | wiki:wiki_cards/battle_trance.txt | — | CARD_WIKI+INV_CARDS/battle_trance_blocks_further_draws_only_this_turn |
| battle_trance+ | yes | — | CARD_DIFF | wiki:wiki_cards/battle_trance.txt (via battle_trance) | — | INV_CARDS |
| berserk | yes | — | CARD_DIFF | wiki:wiki_cards/berserk.txt | — | §197/§199/CARD_WIKI+INV_CARDS |
| berserk+ | yes | — | CARD_DIFF | wiki:wiki_cards/berserk.txt (via berserk) | — | INV_CARDS |
| blind | yes | colorless_potion_offers_three_colorless_cards_and_the_pick_lands_in_hand | — | wiki:wiki_cards/blind.txt | — | CARD_WIKI+INV_CARDS/colorless_potion_offers_three_colorless_cards_and_the_pick_lands_in_hand |
| blood_for_blood | yes | blood_for_blood_gets_cheaper_each_time_you_lose_hp | — | wiki:wiki_cards/blood_for_blood.txt | — | CARD_WIKI+INV_CARDS/blood_for_blood_gets_cheaper_each_time_you_lose_hp |
| blood_for_blood+ | yes | — | CARD_DIFF | wiki:wiki_cards/blood_for_blood.txt (via blood_for_blood) | — | INV_CARDS |
| bloodletting | yes | blood_for_blood_gets_cheaper_each_time_you_lose_hp, losing_hp_is_not_damage_but_it_is_hp_loss …(+1) | — | wiki:wiki_cards/bloodletting.txt | — | §236/CARD_WIKI+INV_CARDS/blood_for_blood_gets_cheaper_each_time_you_lose_hp |
| bloodletting+ | yes | the_lose_hp_cards_do_what_their_pages_say | — | wiki:wiki_cards/bloodletting.txt (via bloodletting) | — | INV_CARDS/the_lose_hp_cards_do_what_their_pages_say |
| bludgeon | yes | the_ten_cards_added_in_221_do_what_the_wiki_says | — | wiki:wiki_cards/bludgeon.txt | — | CARD_WIKI+INV_CARDS/the_ten_cards_added_in_221_do_what_the_wiki_says |
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
| clash | yes | clash_refuses_unless_every_card_in_hand_is_an_attack, a12_halves_the_upgrade_chance_in_acts_two_and_three | — | wiki:wiki_cards/clash.txt | — | §239/CARD_WIKI+INV_CARDS/clash_refuses_unless_every_card_in_hand_is_an_attack |
| clash+ | yes | clash_refuses_unless_every_card_in_hand_is_an_attack | — | wiki:wiki_cards/clash.txt (via clash) | — | INV_CARDS/clash_refuses_unless_every_card_in_hand_is_an_attack |
| cleave | yes | the_ten_cards_added_in_221_do_what_the_wiki_says | — | wiki:wiki_cards/cleave.txt | — | §221/CARD_WIKI+INV_CARDS/the_ten_cards_added_in_221_do_what_the_wiki_says |
| cleave+ | yes | — | CARD_DIFF | wiki:wiki_cards/cleave.txt (via cleave) | — | INV_CARDS |
| clothesline | yes | — | CARD_DIFF | wiki:wiki_cards/clothesline.txt | — | CARD_WIKI+INV_CARDS |
| clothesline+ | yes | — | CARD_DIFF | wiki:wiki_cards/clothesline.txt (via clothesline) | — | INV_CARDS |
| combust | yes | — | CARD_DIFF | wiki:wiki_cards/combust.txt | — | CARD_WIKI+INV_CARDS |
| combust+ | yes | — | CARD_DIFF | wiki:wiki_cards/combust.txt (via combust) | — | INV_CARDS |
| corruption | yes | — | CARD_DIFF | wiki:wiki_cards/corruption.txt | wiki 偏差：wiki 的 Exhaust 指的是**被打出的那个技能**（"Exhaust it"），Corruption 自己进弃牌堆。 | CARD_WIKI+INV_CARDS |
| corruption+ | yes | — | CARD_DIFF | wiki:wiki_cards/corruption.txt (via corruption) | wiki 偏差：wiki 的 Exhaust 指的是**被打出的那个技能**（"Exhaust it"），Corruption 自己进弃牌堆。 | INV_CARDS |
| dark_embrace | yes | — | CARD_DIFF | wiki:wiki_cards/dark_embrace.txt | — | §237/CARD_WIKI+INV_CARDS |
| dark_embrace+ | yes | — | CARD_DIFF | wiki:wiki_cards/dark_embrace.txt (via dark_embrace) | — | INV_CARDS |
| dark_shackles | yes | exhaust_on_play_is_a_zone_and_the_cards_that_use_it_are_playable, colorless_potion_offers_three_colorless_cards_and_the_pick_lands_in_hand | — | wiki:wiki_cards/dark_shackles.txt | wiki 偏差：wiki 升级版是 15 层；内容没有 `dark_shackles+` 这一行。（`Exhaust` 同 `bandage_up`：由落区表达，不是偏差。） | §219/CARD_WIKI+INV_CARDS/exhaust_on_play_is_a_zone_and_the_cards_that_use_it_are_playable |
| dazed | yes | upgrading_burns_walks_every_pile_and_skips_cards_without_an_upgrade, armaments_gains_block_then_upgrades_the_chosen_card …(+2) | — | wiki:wiki_cards/dazed.txt | — | §189/§191/CARD_WIKI+INV_CARDS/upgrading_burns_walks_every_pile_and_skips_cards_without_an_upgrade |
| deep_breath | yes | deep_breath_shuffles_the_discard_pile_back_first | — | wiki:wiki_cards/deep_breath.txt | — | CARD_WIKI+INV_CARDS/deep_breath_shuffles_the_discard_pile_back_first |
| deep_breath+ | yes | — | CARD_DIFF | wiki:wiki_cards/deep_breath.txt (via deep_breath) | — | INV_CARDS |
| defend | yes | dexterity_from_the_content_scales_a_real_defend, card_tags_are_readable_and_a_junk_card_is_not_a_reward …(+36) | — | wiki:wiki_cards/defend.txt | — | §3.1/§6.5/CARD_WIKI+INV_CARDS/dexterity_from_the_content_scales_a_real_defend |
| defend+ | yes | armaments_gains_block_then_upgrades_the_chosen_card | — | wiki:wiki_cards/defend.txt (via defend) | — | INV_CARDS/armaments_gains_block_then_upgrades_the_chosen_card |
| demon_form | yes | demon_form_grows_strength_at_every_turn_start | — | wiki:wiki_cards/demon_form.txt | — | CARD_WIKI+INV_CARDS/demon_form_grows_strength_at_every_turn_start |
| demon_form+ | yes | demon_form_grows_strength_at_every_turn_start | — | wiki:wiki_cards/demon_form.txt (via demon_form) | — | INV_CARDS/demon_form_grows_strength_at_every_turn_start |
| disarm | yes | the_new_red_skills_do_what_their_pages_say | — | wiki:wiki_cards/disarm.txt | — | CARD_WIKI+INV_CARDS/the_new_red_skills_do_what_their_pages_say |
| disarm+ | yes | the_new_red_skills_do_what_their_pages_say | — | wiki:wiki_cards/disarm.txt (via disarm) | — | INV_CARDS/the_new_red_skills_do_what_their_pages_say |
| double_tap | yes | — | CARD_DIFF | wiki:wiki_cards/double_tap.txt | — | §238/CARD_WIKI+INV_CARDS |
| double_tap+ | yes | — | CARD_DIFF | wiki:wiki_cards/double_tap.txt (via double_tap) | — | INV_CARDS |
| doubt | yes | e2e_7e_a_block_gain_spec_in_the_image_truncates_the_block_like_frail, e2e_8_strong_binder_gains_seven_block_then_applies_one_doubt …(+30) | — | wiki:wiki_cards/doubt.txt | ours 回合末给 1 层 Weak，但它在同一回合末就被自己的衰减吃掉 / wiki 原版里 Doubt 的 Weak 会留到下一回合 —— 我们的 `standard.weak` 衰减是一条 `TurnEnded` 触发器（第 ③ 步），而卡牌生命周期节目在第 ① 步 —— 同一次回合末里刚上的 Weak 当场被扣。参考把衰减放在 `decrease_timed_statuses`，与卡程序的关系不同。要修得动回合末的处理器顺序（影响 Burn 等所有生命周期节目），留作单独一节 | §220/§221/CARD_WIKI+INV_CARDS/e2e_7e_a_block_gain_spec_in_the_image_truncates_the_block_like_frail |
| dramatic_entrance | yes | — | CARD_DIFF | wiki:wiki_cards/dramatic_entrance.txt | — | CARD_WIKI+INV_CARDS |
| dramatic_entrance+ | yes | the_zero_cost_utility_batch_matches_its_pages | — | wiki:wiki_cards/dramatic_entrance.txt (via dramatic_entrance) | — | INV_CARDS/the_zero_cost_utility_batch_matches_its_pages |
| dropkick | yes | the_new_red_attacks_do_what_their_pages_say | — | wiki:wiki_cards/dropkick.txt | — | CARD_WIKI+INV_CARDS/the_new_red_attacks_do_what_their_pages_say |
| dropkick+ | yes | — | CARD_DIFF | wiki:wiki_cards/dropkick.txt (via dropkick) | — | INV_CARDS |
| dual_wield | yes | dual_wield_asks_for_an_attack_and_copies_it, a_dual_wield_question_reads_the_same_three_numbers_in_the_page_layer | — | wiki:wiki_cards/dual_wield.txt | — | §226/§227/CARD_WIKI+INV_CARDS/dual_wield_asks_for_an_attack_and_copies_it |
| dual_wield+ | yes | — | CARD_DIFF | wiki:wiki_cards/dual_wield.txt (via dual_wield) | — | INV_CARDS |
| entrench | yes | entrench_doubles_the_block_it_already_has | — | wiki:wiki_cards/entrench.txt | — | §233/CARD_WIKI+INV_CARDS/entrench_doubles_the_block_it_already_has |
| entrench+ | yes | — | CARD_DIFF | wiki:wiki_cards/entrench.txt (via entrench) | — | INV_CARDS |
| evolve | yes | — | CARD_DIFF | wiki:wiki_cards/evolve.txt | — | CARD_WIKI+INV_CARDS |
| evolve+ | yes | — | CARD_DIFF | wiki:wiki_cards/evolve.txt (via evolve) | — | INV_CARDS |
| exhume | yes | exhume_pulls_a_card_out_of_the_exhaust_pile | — | wiki:wiki_cards/exhume.txt | — | CARD_WIKI+INV_CARDS/exhume_pulls_a_card_out_of_the_exhaust_pile |
| exhume+ | yes | — | CARD_DIFF | wiki:wiki_cards/exhume.txt (via exhume) | — | INV_CARDS |
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
| flex | yes | flex_gains_strength_that_the_turn_end_takes_back, a12_halves_the_upgrade_chance_in_acts_two_and_three | — | wiki:wiki_cards/flex.txt | — | §230/CARD_WIKI+INV_CARDS/flex_gains_strength_that_the_turn_end_takes_back |
| flex+ | yes | flex_gains_strength_that_the_turn_end_takes_back | — | wiki:wiki_cards/flex.txt (via flex) | — | INV_CARDS/flex_gains_strength_that_the_turn_end_takes_back |
| ghostly_armor | yes | the_ten_cards_added_in_221_do_what_the_wiki_says | — | wiki:wiki_cards/ghostly_armor.txt | — | CARD_WIKI+INV_CARDS/the_ten_cards_added_in_221_do_what_the_wiki_says |
| ghostly_armor+ | yes | — | CARD_DIFF | wiki:wiki_cards/ghostly_armor.txt (via ghostly_armor) | — | INV_CARDS |
| good_instincts | yes | the_zero_cost_utility_batch_matches_its_pages | — | wiki:wiki_cards/good_instincts.txt | — | CARD_WIKI+INV_CARDS/the_zero_cost_utility_batch_matches_its_pages |
| good_instincts+ | yes | the_zero_cost_utility_batch_matches_its_pages | — | wiki:wiki_cards/good_instincts.txt (via good_instincts) | — | INV_CARDS/the_zero_cost_utility_batch_matches_its_pages |
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
| inflame | yes | — | CARD_DIFF | wiki:wiki_cards/inflame.txt | — | CARD_WIKI+INV_CARDS |
| inflame+ | yes | — | CARD_DIFF | wiki:wiki_cards/inflame.txt (via inflame) | — | INV_CARDS |
| injury | yes | evolve_and_fire_breathing_only_answer_to_the_right_tags, the_event_vocabulary_parses_and_refuses_what_it_does_not_know …(+2) | — | wiki:wiki_cards/injury.txt | — | §143/CARD_WIKI+INV_CARDS/evolve_and_fire_breathing_only_answer_to_the_right_tags |
| insight | yes | the_zero_cost_utility_batch_matches_its_pages | — | wiki:wiki_cards/insight.txt | — | CARD_WIKI+INV_CARDS/the_zero_cost_utility_batch_matches_its_pages |
| insight+ | yes | the_zero_cost_utility_batch_matches_its_pages | — | wiki:wiki_cards/insight.txt (via insight) | — | INV_CARDS/the_zero_cost_utility_batch_matches_its_pages |
| intimidate | yes | — | CARD_DIFF | wiki:wiki_cards/intimidate.txt | — | CARD_WIKI+INV_CARDS |
| intimidate+ | yes | the_new_red_skills_do_what_their_pages_say | — | wiki:wiki_cards/intimidate.txt (via intimidate) | — | INV_CARDS/the_new_red_skills_do_what_their_pages_say |
| iron_wave | yes | stasis_steals_the_best_card_and_returns_it_when_the_orb_dies, tied_rarities_are_broken_by_the_combat_rng | — | wiki:wiki_cards/iron_wave.txt | — | §72.5/CARD_WIKI+INV_CARDS/stasis_steals_the_best_card_and_returns_it_when_the_orb_dies |
| iron_wave+ | yes | — | CARD_DIFF | wiki:wiki_cards/iron_wave.txt (via iron_wave) | — | INV_CARDS |
| juggernaut | yes | — | CARD_DIFF | wiki:wiki_cards/juggernaut.txt | — | CARD_WIKI+INV_CARDS |
| juggernaut+ | yes | — | CARD_DIFF | wiki:wiki_cards/juggernaut.txt (via juggernaut) | — | INV_CARDS |
| limit_break | yes | limit_break_doubles_strength_and_only_the_base_copy_exhausts | — | wiki:wiki_cards/limit_break.txt | — | CARD_WIKI+INV_CARDS/limit_break_doubles_strength_and_only_the_base_copy_exhausts |
| limit_break+ | yes | limit_break_doubles_strength_and_only_the_base_copy_exhausts | — | wiki:wiki_cards/limit_break.txt (via limit_break) | — | INV_CARDS/limit_break_doubles_strength_and_only_the_base_copy_exhausts |
| malaise | yes | malaise_spends_the_energy_on_strength_loss_and_weak | — | wiki:wiki_cards/malaise.txt | — | CARD_WIKI+INV_CARDS/malaise_spends_the_energy_on_strength_loss_and_weak |
| malaise+ | yes | malaise_spends_the_energy_on_strength_loss_and_weak | — | wiki:wiki_cards/malaise.txt (via malaise) | — | INV_CARDS/malaise_spends_the_energy_on_strength_loss_and_weak |
| master_of_strategy | yes | the_zero_cost_utility_batch_matches_its_pages | — | wiki:wiki_cards/master_of_strategy.txt | — | CARD_WIKI+INV_CARDS/the_zero_cost_utility_batch_matches_its_pages |
| master_of_strategy+ | yes | the_zero_cost_utility_batch_matches_its_pages | — | wiki:wiki_cards/master_of_strategy.txt (via master_of_strategy) | — | INV_CARDS/the_zero_cost_utility_batch_matches_its_pages |
| metallicize | yes | decay_predicate_splits_the_two_groups, the_prototype_namespace_supplies_metallicize_and_ritual | — | wiki:wiki_cards/metallicize.txt | — | CARD_WIKI+INV_CARDS/decay_predicate_splits_the_two_groups |
| metallicize+ | yes | — | CARD_DIFF | wiki:wiki_cards/metallicize.txt (via metallicize) | — | INV_CARDS |
| miracle | yes | the_zero_cost_utility_batch_matches_its_pages | — | wiki:wiki_cards/miracle.txt | — | CARD_WIKI+INV_CARDS/the_zero_cost_utility_batch_matches_its_pages |
| miracle+ | yes | the_zero_cost_utility_batch_matches_its_pages | — | wiki:wiki_cards/miracle.txt (via miracle) | — | INV_CARDS/the_zero_cost_utility_batch_matches_its_pages |
| nightmare | yes | nightmare_copies_into_the_aside_pile_and_next_turn_they_arrive | — | wiki:wiki_cards/nightmare.txt | — | CARD_WIKI+INV_CARDS/nightmare_copies_into_the_aside_pile_and_next_turn_they_arrive |
| nightmare+ | yes | — | CARD_DIFF | wiki:wiki_cards/nightmare.txt (via nightmare) | — | INV_CARDS |
| offering | yes | exhausting_a_card_feeds_feel_no_pain_and_dark_embrace, losing_hp_is_not_damage_but_it_is_hp_loss …(+1) | — | wiki:wiki_cards/offering.txt | — | CARD_WIKI+INV_CARDS/exhausting_a_card_feeds_feel_no_pain_and_dark_embrace |
| offering+ | yes | the_lose_hp_cards_do_what_their_pages_say | — | wiki:wiki_cards/offering.txt (via offering) | — | INV_CARDS/the_lose_hp_cards_do_what_their_pages_say |
| panacea | yes | the_zero_cost_utility_batch_matches_its_pages | — | wiki:wiki_cards/panacea.txt | — | CARD_WIKI+INV_CARDS/the_zero_cost_utility_batch_matches_its_pages |
| panacea+ | yes | the_zero_cost_utility_batch_matches_its_pages | — | wiki:wiki_cards/panacea.txt (via panacea) | — | INV_CARDS/the_zero_cost_utility_batch_matches_its_pages |
| patient_guard | yes | the_keyword_cells_are_in_the_image | — | spec:INV_CARDS | — | INV_CARDS/the_keyword_cells_are_in_the_image |
| patient_guard+ | yes | — | CARD_DIFF | spec:INV_CARDS | — | INV_CARDS |
| perfected_strike | yes | perfected_strike_counts_the_tagged_cards_in_hand | — | wiki:wiki_cards/perfected_strike.txt | — | CARD_WIKI+INV_CARDS/perfected_strike_counts_the_tagged_cards_in_hand |
| perfected_strike+ | yes | — | CARD_DIFF | wiki:wiki_cards/perfected_strike.txt (via perfected_strike) | — | INV_CARDS |
| pommel_strike | yes | evolve_and_fire_breathing_only_answer_to_the_right_tags, the_ten_cards_added_in_221_do_what_the_wiki_says | — | wiki:wiki_cards/pommel_strike.txt | — | §221/CARD_WIKI+INV_CARDS/evolve_and_fire_breathing_only_answer_to_the_right_tags |
| pommel_strike+ | yes | — | CARD_DIFF | wiki:wiki_cards/pommel_strike.txt (via pommel_strike) | — | INV_CARDS |
| power_through | yes | the_new_red_skills_do_what_their_pages_say | — | wiki:wiki_cards/power_through.txt | — | CARD_WIKI+INV_CARDS/the_new_red_skills_do_what_their_pages_say |
| power_through+ | yes | the_new_red_skills_do_what_their_pages_say | — | wiki:wiki_cards/power_through.txt (via power_through) | — | INV_CARDS/the_new_red_skills_do_what_their_pages_say |
| pummel | yes | the_ten_cards_added_in_221_do_what_the_wiki_says | — | wiki:wiki_cards/pummel.txt | — | CARD_WIKI+INV_CARDS/the_ten_cards_added_in_221_do_what_the_wiki_says |
| pummel+ | yes | — | CARD_DIFF | wiki:wiki_cards/pummel.txt (via pummel) | — | INV_CARDS |
| rage | yes | the_new_red_skills_do_what_their_pages_say | — | wiki:wiki_cards/rage.txt | — | CARD_WIKI+INV_CARDS/the_new_red_skills_do_what_their_pages_say |
| rage+ | yes | — | CARD_DIFF | wiki:wiki_cards/rage.txt (via rage) | — | INV_CARDS |
| rampage | yes | rampage_grows_this_copy_and_only_this_copy | — | wiki:wiki_cards/rampage.txt | — | CARD_WIKI+INV_CARDS/rampage_grows_this_copy_and_only_this_copy |
| rampage+ | yes | rampage_grows_this_copy_and_only_this_copy | — | wiki:wiki_cards/rampage.txt (via rampage) | — | INV_CARDS/rampage_grows_this_copy_and_only_this_copy |
| reaper | yes | reaper_heals_only_the_unblocked_damage | — | wiki:wiki_cards/reaper.txt | — | CARD_WIKI+INV_CARDS/reaper_heals_only_the_unblocked_damage |
| reaper+ | yes | — | CARD_DIFF | wiki:wiki_cards/reaper.txt (via reaper) | — | INV_CARDS |
| reckless_charge | yes | the_new_red_attacks_do_what_their_pages_say | — | wiki:wiki_cards/reckless_charge.txt | — | CARD_WIKI+INV_CARDS/the_new_red_attacks_do_what_their_pages_say |
| reckless_charge+ | yes | — | CARD_DIFF | wiki:wiki_cards/reckless_charge.txt (via reckless_charge) | — | INV_CARDS |
| rip_and_tear | yes | rip_and_tear_hits_twice_for_seven | — | wiki:wiki_cards/rip_and_tear.txt | — | §228/§229/CARD_WIKI+INV_CARDS/rip_and_tear_hits_twice_for_seven |
| rip_and_tear+ | yes | rip_and_tear_hits_twice_for_seven | — | wiki:wiki_cards/rip_and_tear.txt (via rip_and_tear) | — | INV_CARDS/rip_and_tear_hits_twice_for_seven |
| rupture | yes | — | CARD_DIFF | wiki:wiki_cards/rupture.txt | — | CARD_WIKI+INV_CARDS |
| rupture+ | yes | the_lose_hp_cards_do_what_their_pages_say | — | wiki:wiki_cards/rupture.txt (via rupture) | — | INV_CARDS/the_lose_hp_cards_do_what_their_pages_say |
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
| seeing_red | yes | the_new_red_skills_do_what_their_pages_say | — | wiki:wiki_cards/seeing_red.txt | — | CARD_WIKI+INV_CARDS/the_new_red_skills_do_what_their_pages_say |
| seeing_red+ | yes | — | CARD_DIFF | wiki:wiki_cards/seeing_red.txt (via seeing_red) | — | INV_CARDS |
| sentinel | yes | the_keyword_cells_are_in_the_image, every_way_into_the_exhaust_pile_runs_the_exhausted_program …(+2) | — | wiki:wiki_cards/sentinel.txt | wiki 偏差：wiki 没有 Ethereal（旧版有），内容带 `ethereal`。§220 起"被 Exhaust 时给 2(3) 能量"**已经实现**（`LifecyclePrograms[Exhausted]`），所以这条偏差只剩 Ethereal 标签本身。 | §220/CARD_WIKI+INV_CARDS/the_keyword_cells_are_in_the_image |
| sentinel+ | yes | a_sentinel_that_gets_exhausted_pays_two_energy | — | wiki:wiki_cards/sentinel.txt (via sentinel) | wiki 偏差：wiki 没有 Ethereal（旧版有），内容带 `ethereal`。§220 起"被 Exhaust 时给 2(3) 能量"**已经实现**（`LifecyclePrograms[Exhausted]`），所以这条偏差只剩 Ethereal 标签本身。 | INV_CARDS/a_sentinel_that_gets_exhausted_pays_two_energy |
| sever_soul | yes | the_new_red_attacks_do_what_their_pages_say | — | wiki:wiki_cards/sever_soul.txt | wiki 偏差：wiki 的 {{KW\|Exhaust}} 是动词（消耗手里的非攻击牌），不是本牌的关键字；牌本身打完进弃牌堆。 | CARD_WIKI+INV_CARDS/the_new_red_attacks_do_what_their_pages_say |
| sever_soul+ | yes | — | CARD_DIFF | wiki:wiki_cards/sever_soul.txt (via sever_soul) | wiki 偏差：wiki 的 {{KW\|Exhaust}} 是动词（消耗手里的非攻击牌），不是本牌的关键字；牌本身打完进弃牌堆。 | INV_CARDS |
| shockwave | yes | the_new_red_skills_do_what_their_pages_say | — | wiki:wiki_cards/shockwave.txt | — | CARD_WIKI+INV_CARDS/the_new_red_skills_do_what_their_pages_say |
| shockwave+ | yes | the_new_red_skills_do_what_their_pages_say | — | wiki:wiki_cards/shockwave.txt (via shockwave) | — | INV_CARDS/the_new_red_skills_do_what_their_pages_say |
| shrug_it_off | yes | the_ten_cards_added_in_221_do_what_the_wiki_says | — | wiki:wiki_cards/shrug_it_off.txt | — | CARD_WIKI+INV_CARDS/the_ten_cards_added_in_221_do_what_the_wiki_says |
| shrug_it_off+ | yes | — | CARD_DIFF | wiki:wiki_cards/shrug_it_off.txt (via shrug_it_off) | — | INV_CARDS |
| skewer | yes | skewer_hits_once_per_energy_spent | — | wiki:wiki_cards/skewer.txt | — | §232/CARD_WIKI+INV_CARDS/skewer_hits_once_per_energy_spent |
| skewer+ | yes | — | CARD_DIFF | wiki:wiki_cards/skewer.txt (via skewer) | — | INV_CARDS |
| slimed | yes | card_tags_are_readable_and_a_junk_card_is_not_a_reward, card_rarity_is_readable_and_the_schema_moved_the_version …(+2) | — | wiki:wiki_cards/slimed.txt | — | §192/§219/CARD_WIKI+INV_CARDS/card_tags_are_readable_and_a_junk_card_is_not_a_reward |
| spot_weakness | yes | spot_weakness_follows_the_enemy_intent | — | wiki:wiki_cards/spot_weakness.txt | — | §242/CARD_WIKI+INV_CARDS/spot_weakness_follows_the_enemy_intent |
| spot_weakness+ | yes | — | CARD_DIFF | wiki:wiki_cards/spot_weakness.txt (via spot_weakness) | — | INV_CARDS |
| strike | yes | an_innate_card_is_pulled_to_the_top_of_the_draw_pile, a_card_play_leaves_no_chain_referenced …(+95) | — | wiki:wiki_cards/strike.txt | — | §72.5/§221/CARD_WIKI+INV_CARDS/an_innate_card_is_pulled_to_the_top_of_the_draw_pile |
| strike+ | yes | card_tags_are_readable_and_a_junk_card_is_not_a_reward, armaments_gains_block_then_upgrades_the_chosen_card …(+8) | — | wiki:wiki_cards/strike.txt (via strike) | — | INV_CARDS/card_tags_are_readable_and_a_junk_card_is_not_a_reward |
| swift_strike | yes | an_innate_card_is_pulled_to_the_top_of_the_draw_pile, the_keyword_cells_are_in_the_image | — | spec:INV_CARDS | — | INV_CARDS/an_innate_card_is_pulled_to_the_top_of_the_draw_pile |
| swift_strike+ | yes | — | CARD_DIFF | spec:INV_CARDS | — | INV_CARDS |
| sword_boomerang | yes | sword_boomerang_rerolls_a_target_for_each_hit | — | wiki:wiki_cards/sword_boomerang.txt | — | §228/CARD_WIKI+INV_CARDS/sword_boomerang_rerolls_a_target_for_each_hit |
| sword_boomerang+ | yes | sword_boomerang_rerolls_a_target_for_each_hit | — | wiki:wiki_cards/sword_boomerang.txt (via sword_boomerang) | — | INV_CARDS/sword_boomerang_rerolls_a_target_for_each_hit |
| thunderclap | yes | the_ten_cards_added_in_221_do_what_the_wiki_says | — | wiki:wiki_cards/thunderclap.txt | — | CARD_WIKI+INV_CARDS/the_ten_cards_added_in_221_do_what_the_wiki_says |
| thunderclap+ | yes | — | CARD_DIFF | wiki:wiki_cards/thunderclap.txt (via thunderclap) | — | INV_CARDS |
| trip | yes | the_zero_cost_utility_batch_matches_its_pages | — | wiki:wiki_cards/trip.txt | — | §243/CARD_WIKI+INV_CARDS/the_zero_cost_utility_batch_matches_its_pages |
| trip+ | yes | the_zero_cost_utility_batch_matches_its_pages | — | wiki:wiki_cards/trip.txt (via trip) | — | INV_CARDS/the_zero_cost_utility_batch_matches_its_pages |
| true_grit | yes | true_grit_gains_block_and_exhausts_exactly_one_card | — | wiki:wiki_cards/true_grit.txt | — | §195.4/§231/CARD_WIKI+INV_CARDS/true_grit_gains_block_and_exhausts_exactly_one_card |
| true_grit+ | yes | true_grit_gains_block_and_exhausts_exactly_one_card | — | wiki:wiki_cards/true_grit.txt (via true_grit) | — | INV_CARDS/true_grit_gains_block_and_exhausts_exactly_one_card |
| twin_strike | yes | a_full_deck_archive_is_bigger_than_the_generic_scratch | — | wiki:wiki_cards/twin_strike.txt | — | §72.5/CARD_WIKI+INV_CARDS/a_full_deck_archive_is_bigger_than_the_generic_scratch |
| twin_strike+ | yes | — | CARD_DIFF | wiki:wiki_cards/twin_strike.txt (via twin_strike) | — | INV_CARDS |
| uppercut | yes | stasis_steals_the_best_card_and_returns_it_when_the_orb_dies, a_96_card_pile_still_reaches_the_best_card_at_the_end …(+2) | — | wiki:wiki_cards/uppercut.txt | — | CARD_WIKI+INV_CARDS/stasis_steals_the_best_card_and_returns_it_when_the_orb_dies |
| uppercut+ | yes | — | CARD_DIFF | wiki:wiki_cards/uppercut.txt (via uppercut) | — | INV_CARDS |
| void | yes | a_void_drawn_from_the_pile_costs_one_energy | — | wiki:wiki_cards/void.txt | wiki 偏差：wiki: 抽到时失去 1 点能量。内容缺这条触发器（`OnDrawn` 对牌还没有载体），所以 Void 目前只是"不可出的虚无牌"。 | §220/CARD_WIKI+INV_CARDS/a_void_drawn_from_the_pile_costs_one_energy |
| warcry | yes | warcry_draws_one_then_puts_the_chosen_card_on_top | — | wiki:wiki_cards/warcry.txt | — | CARD_WIKI+INV_CARDS/warcry_draws_one_then_puts_the_chosen_card_on_top |
| warcry+ | yes | — | CARD_DIFF | wiki:wiki_cards/warcry.txt (via warcry) | — | INV_CARDS |
| whirlwind | yes | an_upgraded_card_row_is_buildable, the_keyword_cells_are_in_the_image …(+5) | — | wiki:wiki_cards/whirlwind.txt | — | CARD_WIKI+INV_CARDS/an_upgraded_card_row_is_buildable |
| whirlwind+ | yes | an_upgraded_card_row_is_buildable | — | wiki:wiki_cards/whirlwind.txt (via whirlwind) | — | INV_CARDS/an_upgraded_card_row_is_buildable |
| wild_strike | yes | the_ten_cards_added_in_221_do_what_the_wiki_says | — | wiki:wiki_cards/wild_strike.txt | — | CARD_WIKI+INV_CARDS/the_ten_cards_added_in_221_do_what_the_wiki_says |
| wild_strike+ | yes | — | CARD_DIFF | wiki:wiki_cards/wild_strike.txt (via wild_strike) | — | INV_CARDS |
| wound | yes | the_new_red_skills_do_what_their_pages_say, evolve_and_fire_breathing_only_answer_to_the_right_tags …(+1) | — | wiki:wiki_cards/wound.txt | — | §173/CARD_WIKI+INV_CARDS/the_new_red_skills_do_what_their_pages_say |
| writhe | yes | the_two_event_curses_behave_as_their_pages_say | — | wiki:wiki_cards/writhe.txt | — | §220/§221/CARD_WIKI+INV_CARDS/the_two_event_curses_behave_as_their_pages_say |

## 状态（56）

| Entity | Implemented | TestNamed | HarnessOnly | SourceTie | DeclaredDeviation | Evidence |
|---|---|---|---|---|---|---|
| ritual | yes | ritual_grants_strength_at_the_end_of_the_turn, decay_predicate_splits_the_two_groups …(+1) | — | spec:INV_STATUSES | — | INV_STATUSES/ritual_grants_strength_at_the_end_of_the_turn |
| standard.artifact | yes | artifact_turns_a_debuff_into_a_prevented_beat_naming_the_blocked_status, artifact_eats_one_debuff_and_nothing_else …(+7) | — | spec:INV_STATUSES | — | §116/§117/INV_STATUSES/artifact_turns_a_debuff_into_a_prevented_beat_naming_the_blocked_status |
| standard.barricade | yes | barricade_keeps_block_forever_and_blur_only_for_one_turn | — | spec:INV_STATUSES | — | §197/INV_STATUSES/barricade_keeps_block_forever_and_blur_only_for_one_turn |
| standard.berserk | yes | berserk_adds_one_energy_per_stack_at_turn_start | — | spec:INV_STATUSES | — | §199/§210/INV_STATUSES/berserk_adds_one_energy_per_stack_at_turn_start |
| standard.blur | yes | blur_gives_five_or_eight_block_and_the_status, barricade_keeps_block_forever_and_blur_only_for_one_turn | — | spec:INV_STATUSES | — | §197/§218/INV_STATUSES/blur_gives_five_or_eight_block_and_the_status |
| standard.brutality | yes | losing_hp_is_not_damage_but_it_is_hp_loss, the_lose_hp_cards_do_what_their_pages_say | — | spec:INV_STATUSES | — | §235/§236/INV_STATUSES/losing_hp_is_not_damage_but_it_is_hp_loss |
| standard.buffer | yes | the_damage_pipeline_honours_intangible_buffer_and_plated_armor | — | spec:INV_STATUSES | — | §149/§223/INV_STATUSES/the_damage_pipeline_honours_intangible_buffer_and_plated_armor |
| standard.combust | yes | flame_barrier_hits_back_and_combust_burns_everyone | — | spec:INV_STATUSES | — | §119/INV_STATUSES/flame_barrier_hits_back_and_combust_burns_everyone |
| standard.constricted | yes | constricted_loses_its_stacks_of_hp_through_block_at_turn_end, statuses_outside_the_five_axes_are_readable_by_name …(+1) | — | spec:INV_STATUSES | — | §175/§214/INV_STATUSES/constricted_loses_its_stacks_of_hp_through_block_at_turn_end |
| standard.corruption | yes | corruption_makes_skills_free_and_exhausts_them | — | spec:INV_STATUSES | — | §238/§242/INV_STATUSES/corruption_makes_skills_free_and_exhausts_them |
| standard.curiosity | yes | the_awakened_one_survives_its_first_death_and_then_really_dies | — | spec:INV_STATUSES | — | §194/INV_STATUSES/the_awakened_one_survives_its_first_death_and_then_really_dies |
| standard.curl_up | yes | curl_up_pays_out_once_and_only_for_a_hit_that_draws_blood | — | spec:INV_STATUSES | — | §208/§209/INV_STATUSES/curl_up_pays_out_once_and_only_for_a_hit_that_draws_blood |
| standard.dark_embrace | yes | exhausting_a_card_feeds_feel_no_pain_and_dark_embrace | — | spec:INV_STATUSES | — | §236/§237/INV_STATUSES/exhausting_a_card_feeds_feel_no_pain_and_dark_embrace |
| standard.demon_form | yes | — | CARD_DIFF | spec:INV_STATUSES | — | §231/§235/INV_STATUSES |
| standard.dexterity | yes | dexterity_from_the_content_scales_a_real_defend, global_status_lines_use_the_gs_prefix_and_list_order …(+6) | — | spec:INV_STATUSES | — | §174/§204/INV_STATUSES/dexterity_from_the_content_scales_a_real_defend |
| standard.double_tap | yes | double_tap_only_covers_the_next_attack | — | spec:INV_STATUSES | — | §231/§238/INV_STATUSES/double_tap_only_covers_the_next_attack |
| standard.draw_reduction | yes | draw_reduction_costs_exactly_one_turns_draw_and_then_expires | — | spec:INV_STATUSES | — | §10/§195.7/INV_STATUSES/draw_reduction_costs_exactly_one_turns_draw_and_then_expires |
| standard.duplication | yes | duplication_plays_the_program_twice_but_pays_and_counts_once | — | spec:INV_STATUSES | — | §181/INV_STATUSES/duplication_plays_the_program_twice_but_pays_and_counts_once |
| standard.enrage | yes | a_card_play_leaves_no_chain_referenced, enrage_answers_only_a_skill | — | spec:INV_STATUSES | — | §117/INV_STATUSES/a_card_play_leaves_no_chain_referenced |
| standard.entangle_ready | yes | — | ENEMY_DIFF | spec:INV_STATUSES | — | §196/INV_STATUSES |
| standard.entangled | yes | entangled_refuses_attacks_but_not_skills_and_expires_at_turn_end | — | spec:INV_STATUSES | — | §195.7/§196/INV_STATUSES/entangled_refuses_attacks_but_not_skills_and_expires_at_turn_end |
| standard.evolve | yes | evolve_and_fire_breathing_only_answer_to_the_right_tags | — | spec:INV_STATUSES | — | §236/§237/INV_STATUSES/evolve_and_fire_breathing_only_answer_to_the_right_tags |
| standard.fairy_in_a_bottle | yes | the_charm_catches_one_killing_blow_and_is_spent | — | spec:INV_STATUSES | — | §180/INV_STATUSES/the_charm_catches_one_killing_blow_and_is_spent |
| standard.feel_no_pain | yes | exhausting_a_card_feeds_feel_no_pain_and_dark_embrace | — | spec:INV_STATUSES | — | §236/§237/INV_STATUSES/exhausting_a_card_feeds_feel_no_pain_and_dark_embrace |
| standard.fire_breathing | yes | evolve_and_fire_breathing_only_answer_to_the_right_tags | — | spec:INV_STATUSES | — | §236/§237/INV_STATUSES/evolve_and_fire_breathing_only_answer_to_the_right_tags |
| standard.flame_barrier | yes | flame_barrier_hits_back_and_combust_burns_everyone, the_new_red_skills_do_what_their_pages_say | — | spec:INV_STATUSES | — | §119/INV_STATUSES/flame_barrier_hits_back_and_combust_burns_everyone |
| standard.flying | yes | flying_halves_attack_damage_and_loses_a_stack_per_hit | — | spec:INV_STATUSES | — | §208/§216/INV_STATUSES/flying_halves_attack_damage_and_loses_a_stack_per_hit |
| standard.frail | yes | entrench_doubles_the_block_it_already_has, damage_table_rows_are_the_frozen_shape …(+4) | — | spec:INV_STATUSES | — | §196/§212/INV_STATUSES/entrench_doubles_the_block_it_already_has |
| standard.hex | yes | hex_shuffles_a_dazed_only_for_non_attack_cards | — | spec:INV_STATUSES | — | §210/§213/INV_STATUSES/hex_shuffles_a_dazed_only_for_non_attack_cards |
| standard.intangible | yes | the_damage_pipeline_honours_intangible_buffer_and_plated_armor | — | spec:INV_STATUSES | — | §210/§223/INV_STATUSES/the_damage_pipeline_honours_intangible_buffer_and_plated_armor |
| standard.juggernaut | yes | juggernaut_punishes_every_block_gain | — | spec:INV_STATUSES | — | §237/§242/INV_STATUSES/juggernaut_punishes_every_block_gain |
| standard.lose_dexterity | yes | — | — | spec:INV_STATUSES | — | §158/INV_STATUSES |
| standard.lose_strength | yes | flex_potion_gives_strength_and_takes_it_back | — | spec:INV_STATUSES | — | §158/§230/INV_STATUSES/flex_potion_gives_strength_and_takes_it_back |
| standard.metallicize | yes | metallicize_grants_block_at_the_end_of_the_turn, plated_armor_and_metallicize_both_pay_block_at_turn_end | — | spec:INV_STATUSES | — | §107/§194/INV_STATUSES/metallicize_grants_block_at_the_end_of_the_turn |
| standard.mode_shift | yes | mode_shift_is_a_budget_drained_by_the_health_actually_lost | — | spec:INV_STATUSES | — | §195.1/INV_STATUSES/mode_shift_is_a_budget_drained_by_the_health_actually_lost |
| standard.nightmare_pending | yes | nightmare_copies_into_the_aside_pile_and_next_turn_they_arrive | — | spec:INV_STATUSES | — | §213/§227/INV_STATUSES/nightmare_copies_into_the_aside_pile_and_next_turn_they_arrive |
| standard.no_draw | yes | battle_trance_blocks_further_draws_only_this_turn, the_ten_cards_added_in_221_do_what_the_wiki_says | — | spec:INV_STATUSES | — | §227/§231/INV_STATUSES/battle_trance_blocks_further_draws_only_this_turn |
| standard.phantom_veil | yes | — | — | spec:INV_STATUSES | — | §175/§181/INV_STATUSES |
| standard.phase_split | yes | the_boss_phase_splits_once_at_low_health, a_phase_split_happens_once_even_under_three_hits | — | spec:INV_STATUSES | — | §121/§122/INV_STATUSES/the_boss_phase_splits_once_at_low_health |
| standard.plated_armor | yes | a_long_fight_never_reports_a_step_problem, plated_armor_wears_down_to_nothing_without_an_error …(+4) | — | spec:INV_STATUSES | — | §209/§210/INV_STATUSES/a_long_fight_never_reports_a_step_problem |
| standard.rage | yes | rage_gives_block_only_for_an_attack, the_new_red_skills_do_what_their_pages_say …(+3) | — | spec:INV_STATUSES | — | §119/INV_STATUSES/rage_gives_block_only_for_an_attack |
| standard.regain_strength | yes | exhaust_on_play_is_a_zone_and_the_cards_that_use_it_are_playable | — | spec:INV_STATUSES | — | §219/INV_STATUSES/exhaust_on_play_is_a_zone_and_the_cards_that_use_it_are_playable |
| standard.regen | yes | the_awakened_one_survives_its_first_death_and_then_really_dies, regen_heals_at_the_end_of_the_turn …(+1) | — | spec:INV_STATUSES | — | §119/INV_STATUSES/the_awakened_one_survives_its_first_death_and_then_really_dies |
| standard.rupture | yes | losing_hp_is_not_damage_but_it_is_hp_loss, the_lose_hp_cards_do_what_their_pages_say | — | spec:INV_STATUSES | — | §235/§236/INV_STATUSES/losing_hp_is_not_damage_but_it_is_hp_loss |
| standard.sharp_hide | yes | sharp_hide_hurts_the_player_for_attacks_and_only_attacks, mode_shift_is_a_budget_drained_by_the_health_actually_lost | — | spec:INV_STATUSES | — | §194/§195.1/INV_STATUSES/sharp_hide_hurts_the_player_for_attacks_and_only_attacks |
| standard.slow | yes | a_card_play_leaves_no_chain_referenced, a_slow_spec_on_a_pipeline_without_a_card_count_is_refused …(+1) | — | spec:INV_STATUSES | ours 放大任何直接伤害（`RestrictDamageKind: Direct`） / wiki 只放大"打出攻击牌造成的伤害" —— 要精确到卡牌标签需要 `RestrictSourceCardTag` 进镜像格式（`status_bind` 目前对非空值响亮拒绝），留作格式升级。基线（本回合牌数、每回合归零、不复合）已与 wiki 一致（§216） | §216/INV_STATUSES/a_card_play_leaves_no_chain_referenced |
| standard.split | yes | a_spawned_enemy_joins_the_turn_order_after_the_current_actor, a_phase_split_happens_once_even_under_three_hits …(+1) | — | spec:INV_STATUSES | — | §121/INV_STATUSES/a_spawned_enemy_joins_the_turn_order_after_the_current_actor |
| standard.spore_cloud | yes | spore_cloud_weakens_the_killer_on_death | — | spec:INV_STATUSES | — | §117/§237/INV_STATUSES/spore_cloud_weakens_the_killer_on_death |
| standard.stasis | yes | stasis_steals_the_best_card_and_returns_it_when_the_orb_dies, a_96_card_pile_still_reaches_the_best_card_at_the_end …(+2) | — | spec:INV_STATUSES | — | §195.1/§195.4/INV_STATUSES/stasis_steals_the_best_card_and_returns_it_when_the_orb_dies |
| standard.stasis_ready | yes | stasis_steals_the_best_card_and_returns_it_when_the_orb_dies, a_96_card_pile_still_reaches_the_best_card_at_the_end …(+2) | — | spec:INV_STATUSES | — | §195.4/INV_STATUSES/stasis_steals_the_best_card_and_returns_it_when_the_orb_dies |
| standard.strength | yes | dot_slips_past_the_standard_pack_rows_that_direct_hits_do_not, modifier_rows_match_exactly_and_through_the_documented_namespace_bridge …(+57) | — | spec:INV_STATUSES | — | §230/§242/INV_STATUSES/dot_slips_past_the_standard_pack_rows_that_direct_hits_do_not |
| standard.thorns | yes | thorns_hurts_whoever_hits_its_owner, standard_status_ids_are_byte_ordered_not_registration_ordered …(+4) | — | spec:INV_STATUSES | — | §214/§237/INV_STATUSES/thorns_hurts_whoever_hits_its_owner |
| standard.time_warp | yes | the_twelfth_card_asks_for_the_turn_to_end | — | spec:INV_STATUSES | — | §122/§125/INV_STATUSES/the_twelfth_card_asks_for_the_turn_to_end |
| standard.unawakened | yes | the_awakened_one_survives_its_first_death_and_then_really_dies, the_awakened_one_draws_phase_one_by_weight_and_flips_on_the_guard | — | spec:INV_STATUSES | — | §180/§195.2/INV_STATUSES/the_awakened_one_survives_its_first_death_and_then_really_dies |
| standard.vulnerable | yes | the_def_table_is_a_side_table_not_a_copy_per_beat, clear_wipes_the_names_too …(+22) | — | spec:INV_STATUSES | — | §213/§243/INV_STATUSES/the_def_table_is_a_side_table_not_a_copy_per_beat |
| standard.weak | yes | the_def_table_is_a_side_table_not_a_copy_per_beat, clear_wipes_the_names_too …(+29) | — | spec:INV_STATUSES | — | §220/§221/INV_STATUSES/the_def_table_is_a_side_table_not_a_copy_per_beat |

## 遭遇（34）

| Entity | Implemented | TestNamed | HarnessOnly | SourceTie | DeclaredDeviation | Evidence |
|---|---|---|---|---|---|---|
| enc_awakened_one | yes | every_act_has_three_bosses_and_each_one_is_a_buildable_encounter, the_awakened_one_draws_phase_one_by_weight_and_flips_on_the_guard …(+3) | — | — | — | §194/§195.8/every_act_has_three_bosses_and_each_one_is_a_buildable_encounter |
| enc_book_of_stabbing | yes | — | entity_tables_decode_row_by_row …(+11) | — | — | §173 |
| enc_bronze_automaton | yes | every_act_has_three_bosses_and_each_one_is_a_buildable_encounter, the_automaton_swaps_stunned_for_boost_only_at_a19 …(+3) | — | — | — | §138/§194/every_act_has_three_bosses_and_each_one_is_a_buildable_encounter |
| enc_byrds | yes | flying_halves_attack_damage_and_loses_a_stack_per_hit | — | — | — | §138/§201/flying_halves_attack_damage_and_loses_a_stack_per_hit |
| enc_chosen | yes | hex_shuffles_a_dazed_only_for_non_attack_cards, chosen_swaps_its_opener_at_a17 | — | — | — | §153/§201/hex_shuffles_a_dazed_only_for_non_attack_cards |
| enc_cultist | yes | an_encounter_without_rolls_draws_nothing, building_a_louse_fight_draws_its_bite_and_a_cultist_fight_does_not | — | — | — | §5.2/§130/an_encounter_without_rolls_draws_nothing |
| enc_darklings | yes | an_encounter_with_two_records_of_the_same_id_builds | — | — | — | §201/an_encounter_with_two_records_of_the_same_id_builds |
| enc_donu_and_deca | yes | every_act_has_three_bosses_and_each_one_is_a_buildable_encounter | — | — | — | §194/§195.8/every_act_has_three_bosses_and_each_one_is_a_buildable_encounter |
| enc_fungi_beast | yes | — | entity_tables_decode_row_by_row …(+11) | — | — | §130/§152 |
| enc_giant_head | yes | a_summoned_minion_resolves_through_the_image_not_the_encounter, giant_head_counts_down_then_only_its_time …(+1) | — | — | — | §134/a_summoned_minion_resolves_through_the_image_not_the_encounter |
| enc_gremlin_gang | yes | — | entity_tables_decode_row_by_row …(+11) | — | — | §138/§153 |
| enc_gremlin_leader | yes | — | entity_tables_decode_row_by_row …(+11) | — | — | §5.3/§134 |
| enc_gremlin_nob | yes | an_ascension_health_row_applies_at_its_own_level_and_not_below | — | — | — | §152/an_ascension_health_row_applies_at_its_own_level_and_not_below |
| enc_hexaghost | yes | every_act_has_three_bosses_and_each_one_is_a_buildable_encounter, hexaghost_plays_the_wikis_seven_move_pattern_after_its_two_openers | — | — | — | §194/every_act_has_three_bosses_and_each_one_is_a_buildable_encounter |
| enc_jaw_worm | yes | uppercut_hurts_the_enemy_and_not_the_hero, a_dual_wield_question_reads_the_same_three_numbers_in_the_page_layer …(+2) | — | — | — | §5.2/§130/uppercut_hurts_the_enemy_and_not_the_hero |
| enc_lagavulin | yes | lagavulin_can_be_fought_for_eight_rounds_including_siphon_soul | — | — | — | §173/lagavulin_can_be_fought_for_eight_rounds_including_siphon_soul |
| enc_looter | yes | an_ascension_health_row_applies_at_its_own_level_and_not_below, the_looter_mugs_twice_then_bombs_then_escapes | — | — | — | §175/§201/an_ascension_health_row_applies_at_its_own_level_and_not_below |
| enc_louse | yes | a_spawn_roll_is_drawn_once_per_fight_and_read_by_the_action, an_encounter_without_rolls_draws_nothing …(+2) | — | — | — | §130/§152/a_spawn_roll_is_drawn_once_per_fight_and_read_by_the_action |
| enc_maw | yes | nom_nom_hits_five_damage_ceil_round_over_two_times, the_maw_follows_the_wikis_transition_table | — | — | — | §147/§201/nom_nom_hits_five_damage_ceil_round_over_two_times |
| enc_nemesis | yes | — | entity_tables_decode_row_by_row …(+11) | — | — | §175 |
| enc_orb_walker | yes | — | entity_tables_decode_row_by_row …(+11) | — | — | §138/§201 |
| enc_reptomancer | yes | act_three_reptomancer_daggers_arrive_and_then_take_themselves_out | — | — | — | §175/act_three_reptomancer_daggers_arrive_and_then_take_themselves_out |
| enc_shelled_parasite | yes | — | entity_tables_decode_row_by_row …(+11) | — | — | §153/§201 |
| enc_slaver_red | yes | — | entity_tables_decode_row_by_row …(+11) | — | — | §130/§152 |
| enc_slavers | yes | a_round_one_rule_beats_the_cycle_and_the_cycle_takes_over_after_it | — | — | — | a_round_one_rule_beats_the_cycle_and_the_cycle_takes_over_after_it |
| enc_slime_boss | yes | every_act_has_three_bosses_and_each_one_is_a_buildable_encounter, a_combinator_rule_switches_the_boss_move …(+1) | — | — | — | §194/every_act_has_three_bosses_and_each_one_is_a_buildable_encounter |
| enc_small_slimes | yes | a_spawned_combatant_still_resolves_to_its_enemy_record | — | — | — | §130/a_spawned_combatant_still_resolves_to_its_enemy_record |
| enc_spiker | yes | spiker_never_repeats_its_attack_and_buffs_thorns_at_most_six_times, starting_statuses_follow_their_ascension_rows | — | — | — | §138/§201/spiker_never_repeats_its_attack_and_buffs_thorns_at_most_six_times |
| enc_spire_growth | yes | spire_growth_smashes_instead_of_choosing | — | — | — | §147/§201/spire_growth_smashes_instead_of_choosing |
| enc_the_champ | yes | an_ascension_health_row_applies_at_its_own_level_and_not_below, every_act_has_three_bosses_and_each_one_is_a_buildable_encounter …(+4) | — | — | — | §194/an_ascension_health_row_applies_at_its_own_level_and_not_below |
| enc_the_collector | yes | the_collector_draws_by_weight_and_never_buffs_twice_in_a_row, every_act_has_three_bosses_and_each_one_is_a_buildable_encounter …(+1) | — | — | — | §138/§194/the_collector_draws_by_weight_and_never_buffs_twice_in_a_row |
| enc_the_guardian | yes | mode_shift_is_a_budget_drained_by_the_health_actually_lost, every_act_has_three_bosses_and_each_one_is_a_buildable_encounter …(+1) | — | — | — | §194/mode_shift_is_a_budget_drained_by_the_health_actually_lost |
| enc_three_sentries | yes | — | entity_tables_decode_row_by_row …(+11) | — | — | §134 |
| enc_time_eater | yes | every_act_has_three_bosses_and_each_one_is_a_buildable_encounter, a_weighted_boss_never_repeats_the_move_the_wiki_forbids …(+1) | — | — | — | §138/§194/every_act_has_three_bosses_and_each_one_is_a_buildable_encounter |

## 事件（11）

| Entity | Implemented | TestNamed | HarnessOnly | SourceTie | DeclaredDeviation | Evidence |
|---|---|---|---|---|---|---|
| ancient_forge | yes | the_unknown_room_events_are_readable, an_event_that_edits_the_deck_owes_a_pick_first …(+3) | — | — | — | the_unknown_room_events_are_readable |
| ancient_writing | yes | the_unknown_room_events_are_readable, an_event_choice_that_edits_the_deck_owes_a_pick | — | — | — | the_unknown_room_events_are_readable |
| forgotten_altar | yes | the_unknown_room_events_are_readable, an_event_choice_that_edits_the_deck_owes_a_pick | — | — | — | the_unknown_room_events_are_readable |
| golden_idol | yes | the_unknown_room_events_are_readable, an_event_relic_is_never_drawn …(+5) | — | — | — | §156/§157/the_unknown_room_events_are_readable |
| old_shrine | yes | the_unknown_room_events_are_readable, an_event_can_give_a_relic_only_if_the_kernel_can_run_it | — | — | — | the_unknown_room_events_are_readable |
| purification_shrine | yes | the_unknown_room_events_are_readable | — | — | — | the_unknown_room_events_are_readable |
| scrap_pile | yes | the_unknown_room_events_are_readable | — | — | — | the_unknown_room_events_are_readable |
| shining_light | yes | the_unknown_room_events_are_readable | — | — | — | the_unknown_room_events_are_readable |
| the_mausoleum | yes | the_unknown_room_events_are_readable | — | — | — | the_unknown_room_events_are_readable |
| the_ssssserpent | yes | the_unknown_room_events_are_readable | — | — | — | the_unknown_room_events_are_readable |
| wandering_merchant | yes | the_unknown_room_events_are_readable | — | — | — | the_unknown_room_events_are_readable |

## 遗物（15）

| Entity | Implemented | TestNamed | HarnessOnly | SourceTie | DeclaredDeviation | Evidence |
|---|---|---|---|---|---|---|
| anchor | yes | the_same_state_hashes_the_same_and_a_change_moves_it, every_invariant_names_itself_when_violated …(+6) | — | — | — | the_same_state_hashes_the_same_and_a_change_moves_it |
| bag_of_marbles | yes | the_two_combat_start_carriers_land_on_the_right_side | — | — | — | §221/§224/the_two_combat_start_carriers_land_on_the_right_side |
| blood_vial | yes | the_relic_pool_fires_at_the_three_hooks_it_has | — | — | — | the_relic_pool_fires_at_the_three_hooks_it_has |
| bronze_scales | yes | — | an_id_that_is_a_card_and_a_relic_is_not_an_encounter …(+5) | — | — | §156 |
| burning_blood | yes | capacity_is_an_error_not_a_truncation, burning_blood_heals_six_at_the_end_of_a_fight …(+7) | — | — | — | capacity_is_an_error_not_a_truncation |
| eternal_feather | yes | the_eternal_feather_pays_per_whole_group_of_five_on_entering, the_new_relics_pay_out | — | — | — | §156/§157/the_eternal_feather_pays_per_whole_group_of_five_on_entering |
| golden_idol | yes | the_unknown_room_events_are_readable, an_event_relic_is_never_drawn …(+5) | — | — | — | §156/§157/the_unknown_room_events_are_readable |
| meat_on_the_bone | yes | — | an_id_that_is_a_card_and_a_relic_is_not_an_encounter …(+5) | — | — | §156 |
| oddly_smooth_stone | yes | the_two_combat_start_carriers_land_on_the_right_side | — | — | — | §221/§224/the_two_combat_start_carriers_land_on_the_right_side |
| pear | yes | the_relic_pool_fires_at_the_three_hooks_it_has | — | — | — | the_relic_pool_fires_at_the_three_hooks_it_has |
| potion_belt | yes | capacity_is_an_error_not_a_truncation, the_ascension_rules_are_each_their_own_level …(+1) | — | — | — | §156/§157/capacity_is_an_error_not_a_truncation |
| regal_pillow | yes | — | an_id_that_is_a_card_and_a_relic_is_not_an_encounter …(+5) | — | — | §156 |
| strawberry | yes | — | an_id_that_is_a_card_and_a_relic_is_not_an_encounter …(+5) | — | — | §156 |
| thread_and_needle | yes | the_relic_pool_fires_at_the_three_hooks_it_has, an_elite_pays_a_relic_and_a_normal_fight_does_not | — | — | — | the_relic_pool_fires_at_the_three_hooks_it_has |
| vajra | yes | every_invariant_names_itself_when_violated, a_relic_you_already_hold_is_not_offered_again …(+3) | — | — | — | every_invariant_names_itself_when_violated |

## 药水（33）

| Entity | Implemented | TestNamed | HarnessOnly | SourceTie | DeclaredDeviation | Evidence |
|---|---|---|---|---|---|---|
| ancient_potion | yes | the_potions_are_readable | — | — | — | the_potions_are_readable |
| attack_potion | yes | the_potions_are_readable, an_attack_potion_offers_three_definitions_and_creates_only_the_chosen_card …(+1) | — | — | — | the_potions_are_readable |
| blessing_of_the_forge | yes | the_potions_are_readable, blessing_of_the_forge_upgrades_every_strike_in_hand | — | — | — | the_potions_are_readable |
| block_potion | yes | the_potions_are_readable, dropping_a_potion_keeps_the_order_of_the_survivors …(+3) | — | — | — | the_potions_are_readable |
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
| fire_potion | yes | the_potions_are_readable, the_same_state_hashes_the_same_and_a_change_moves_it …(+10) | — | — | — | the_potions_are_readable |
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
| snecko_oil | yes | the_potions_are_readable, snecko_oil_draws_five_and_randomizes_every_price_in_hand | — | — | — | the_potions_are_readable |
| speed_potion | yes | the_potions_are_readable | — | — | — | the_potions_are_readable |
| strength_potion | yes | the_potions_are_readable, the_new_potion_shapes_all_do_something | — | — | — | the_potions_are_readable |
| swift_potion | yes | the_potions_are_readable, the_new_potion_shapes_all_do_something …(+1) | — | — | — | the_potions_are_readable |
| weak_potion | yes | the_potions_are_readable, the_new_potion_shapes_all_do_something | — | — | — | the_potions_are_readable |
