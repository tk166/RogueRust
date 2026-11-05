# 覆盖矩阵（**生成物，别手改**）

> 生成：`python -X utf8 native/coverage_matrix.py`；校验：`... --check`（闸门 13 就是它）。
> 手改这一页会让闸门红 —— 这是故意的：一张"人维护的覆盖表"活不过下一次内容变更。

回答一个问题：**每一个实体（怪/动作/卡/状态/遭遇/事件/遗物/药水）被验证到哪里了？**
下面这张 360 行的表靠记性是维护不了的，所以每一列都是派生的（口径见 `native/coverage_matrix.py` 顶部）：

* **Implemented** —— 在内容里且**可达**（`orphan` = 内容长出一条没人引用的行，闸门红）。
* **RuntimeTested** —— `test:<函数名>`：某条内核测试的函数体里出现了这个 id；
  `harness:<名字>`：只有通用对拍层遍历到它（`ENEMY_DIFF` 跑每一条 `EACT`、`CARD_DIFF` 跑每一张卡）。
  ⚠️ `harness` 比 `test` 弱：它只说明"跑过、程序文本与参考实现一致"，不说明"按 wiki 的数在跑"。
* **WikiVerified** —— `wiki:<dump>`：`native/wiki_asc/` 或 `native/wiki_*.txt` 里有它的
  Infobox，**并且** checker 钉了它的数字；`spec:<TABLE>`：只对上了 checker 里那份**也是人抄的**清单；
  `—`：没有任何独立来源。**这一列是本页最大的洞，不粉饰**。
* **Deviation** —— 声明过的偏差（`INV_UNWIRED` / `INV_NO_ASC` / `INV_NO_ASC_HP` /
  `docs/sts-wiki-gap.md` §G、§H 两张表，直接解析）。
* **Evidence** —— `§N`（`sts_content_check.py` 引用到的 port-plan 小节）+ 不变量表 + 测试名。

**怎么用**：想找下一件该干的活，就按 `WikiVerified = —` 或 `RuntimeTested = —` 排序看。


## 汇总（每类实体数 × 证据强度）

| 类别 | 行数 | `test:` | `harness:` | `—` | `wiki:` | `spec:` | 有偏差 | orphan |
|---|---|---|---|---|---|---|---|---|
| 怪物 | 47 | 33 | 0 | 14 | 47 | 0 | 11 | 0 |
| 敌人动作 | 130 | 59 | 71 | 0 | 130 | 0 | 57 | 0 |
| 卡牌 | 51 | 21 | 30 | 0 | 0 | 51 | 0 | 0 |
| 状态 | 43 | 40 | 1 | 2 | 0 | 43 | 0 | 0 |
| 遭遇 | 34 | 25 | 9 | 0 | 0 | 0 | 0 | 0 |
| 事件 | 9 | 9 | 0 | 0 | 0 | 0 | 0 | 0 |
| 遗物 | 13 | 9 | 4 | 0 | 0 | 0 | 0 | 0 |
| 药水 | 33 | 33 | 0 | 0 | 0 | 0 | 0 | 0 |
| **合计** | 360 | 229 | 115 | 16 | 177 | 94 | 68 | 0 |

扫描到的具名测试：**897** 条；wiki dump：**45** 份（其中 47 只怪有 dump）。

事件：池里有 **12** 个位次、**9** 个不同 id（`golden_idol` / `ancient_forge` / `purification_shrine` 跨幕复用）。

同一页面的早期副本（内容同源，矩阵只用 `wiki_asc/` 那一份）：`wiki_book_of_stabbing.txt`、`wiki_lagavulin.txt`、`wiki_nemesis.txt`、`wiki_reptomancer.txt`、`wiki_slavers.txt`、`wiki_taskmaster.txt`

## 怪物（47）

| Entity | Implemented | RuntimeTested | WikiVerified | Deviation | Evidence |
|---|---|---|---|---|---|
| acid_slime_m | yes | test:a_split_spawns_two_combatants_when_the_boss_dies, a_spawned_combatant_still_resolves_to_its_enemy_record | wiki:wiki_asc/acid_slime.txt | — | INV_ASC_HP+INV_MONSTERS/a_split_spawns_two_combatants_when_the_boss_dies |
| acid_slime_s | orphan (declared) | — | wiki:wiki_asc/acid_slime.txt | — | INV_ASC_HP+INV_MONSTERS |
| awakened_one | yes | test:the_awakened_one_survives_its_first_death_and_then_really_dies, the_awakened_one_draws_phase_one_by_weight_and_flips_on_the_guard …(+3) | wiki:wiki_asc/awakened_one.txt | gap §H: 二阶段"不能连续三次 Tackle/Sludge"未做（规则预算 8 条已满）；Regenerate/Curiosity 层数不随 A19 变 | §195.8/INV_ASC_HP+INV_MONSTERS/the_awakened_one_survives_its_first_death_and_then_really_dies |
| blue_slaver | yes | test:a_round_one_rule_beats_the_cycle_and_the_cycle_takes_over_after_it | wiki:wiki_asc/slavers.txt | — | INV_ASC_HP+INV_MONSTERS/a_round_one_rule_beats_the_cycle_and_the_cycle_takes_over_after_it |
| book_of_stabbing | yes | — | wiki:wiki_asc/book_of_stabbing.txt | — | §173/INV_ASC_HP+INV_MONSTERS |
| bronze_automaton | yes | test:stasis_steals_the_best_card_and_returns_it_when_the_orb_dies, a_96_card_pile_still_reaches_the_best_card_at_the_end …(+5) | wiki:wiki_asc/bronze_automaton.txt | gap §H: Orb 的 `Stasis` 用"最高稀有度"（并列随机），与 wiki 一致；"同一招不能三次"已做 | §138/§194/INV_ASC_HP+INV_MONSTERS/stasis_steals_the_best_card_and_returns_it_when_the_orb_dies |
| bronze_orb | yes | test:a_weighted_boss_never_repeats_the_move_the_wiki_forbids, a_minion_is_not_on_the_field_until_its_summon_lands …(+1) | wiki:wiki_asc/bronze_automaton.txt | gap §H: Orb 的 `Stasis` 用"最高稀有度"（并列随机），与 wiki 一致；"同一招不能三次"已做 | §194/§195.6/INV_ASC_HP+INV_MONSTERS/a_weighted_boss_never_repeats_the_move_the_wiki_forbids |
| byrd | yes | test:flying_halves_attack_damage_and_loses_a_stack_per_hit | wiki:wiki_asc/byrd.txt | — | §208/§213/INV_ASC_HP+INV_MONSTERS/flying_halves_attack_damage_and_loses_a_stack_per_hit |
| chosen | yes | test:hex_shuffles_a_dazed_only_for_non_attack_cards, chosen_swaps_its_opener_at_a17 …(+1) | wiki:wiki_asc/chosen.txt | — | §130/§213/INV_ASC_HP+INV_MONSTERS/hex_shuffles_a_dazed_only_for_non_attack_cards |
| cultist | yes | test:building_a_fight_keeps_the_ascension_but_not_the_last_fights_gold, a_fight_built_from_the_content_deck_can_play_a_strike …(+5) | wiki:wiki_asc/cultist.txt | — | §5.2/§195.8/INV_ASC_HP+INV_MONSTERS/building_a_fight_keeps_the_ascension_but_not_the_last_fights_gold |
| dagger | yes | — | wiki:wiki_asc/dagger.txt | — | §175/INV_ASC_HP+INV_MONSTERS |
| darkling | yes | test:an_encounter_with_two_records_of_the_same_id_builds | wiki:wiki_asc/darkling.txt | — | §129/§137/INV_ASC_HP+INV_MONSTERS+INV_ROLLS/an_encounter_with_two_records_of_the_same_id_builds |
| deca | yes | test:donus_circle_of_power_buffs_the_enemy_team_and_not_the_player | wiki:wiki_asc/donu_and_deca.txt | gap §H: Artifact 层数不随 A19 变（`StartingStatuses` 没有升档轴） | §195.8/INV_ASC_HP+INV_MONSTERS/donus_circle_of_power_buffs_the_enemy_team_and_not_the_player |
| donu | yes | test:donus_circle_of_power_buffs_the_enemy_team_and_not_the_player | wiki:wiki_asc/donu_and_deca.txt | gap §H: Artifact 层数不随 A19 变（`StartingStatuses` 没有升档轴） | §195.8/INV_ASC_HP+INV_MONSTERS/donus_circle_of_power_buffs_the_enemy_team_and_not_the_player |
| fat_gremlin | yes | — | wiki:wiki_asc/fat_gremlin.txt | — | §138/§214/INV_ASC_HP+INV_MONSTERS |
| fungi_beast | yes | test:act_two_fights_act_two_enemies | wiki:wiki_asc/fungi_beast.txt | — | §152/INV_ASC_HP+INV_MONSTERS/act_two_fights_act_two_enemies |
| giant_head | yes | test:giant_head_counts_down_then_only_its_time, it_is_time_escalates_by_five_and_respects_its_cap | wiki:wiki_asc/giant_head.txt | — | §134/§211/INV_ASC_HP+INV_MONSTERS+INV_SPAWN_COUNTERS/giant_head_counts_down_then_only_its_time |
| gremlin_leader | yes | test:the_summon_cap_is_a_loud_failure | wiki:wiki_asc/gremlin_leader.txt | — | §134/§212/INV_ASC_HP+INV_MONSTERS/the_summon_cap_is_a_loud_failure |
| gremlin_nob | yes | — | wiki:wiki_asc/gremlin_nob.txt | — | §152/INV_ASC_HP+INV_MONSTERS |
| gremlin_wizard | yes | — | wiki:wiki_asc/gremlin_wizard.txt | — | §130/§138/INV_ASC_HP+INV_MONSTERS |
| hexaghost | yes | test:hexaghost_plays_the_wikis_seven_move_pattern_after_its_two_openers, the_boss_is_offered_at_floor_16_and_clears_the_act | wiki:wiki_asc/hexaghost.txt | gap §H: Sear 后续塞的 Burn 不自动升级（wiki："for the rest of combat"）；Divider 读结算时 HP | INV_ASC_HP+INV_MONSTERS/hexaghost_plays_the_wikis_seven_move_pattern_after_its_two_openers |
| jaw_worm | yes | test:a_jaw_worm_starts_with_block_and_a17_makes_it_bigger, act_two_fights_act_two_enemies | wiki:wiki_asc/jaw_worm.txt | — | §5.2/INV_ASC_HP+INV_MONSTERS/a_jaw_worm_starts_with_block_and_a17_makes_it_bigger |
| lagavulin | yes | test:an_elite_node_fights_the_sentries_and_pays_the_elite_tier | wiki:wiki_asc/lagavulin.txt | — | §173/INV_ASC_HP+INV_MONSTERS/an_elite_node_fights_the_sentries_and_pays_the_elite_tier |
| looter | yes | test:ascension_two_makes_the_looter_mug_hit_for_eleven, a_looter_steals_thievery_gold_on_every_attack_and_carries_it_away …(+4) | wiki:wiki_asc/thieves.txt | — | §175/§201/INV_ASC_HP+INV_MONSTERS/ascension_two_makes_the_looter_mug_hit_for_eleven |
| louse_green | orphan (declared) | — | wiki:wiki_asc/louses.txt | — | §152/INV_ASC_HP+INV_MONSTERS |
| louse_red | yes | test:a_spawn_roll_is_drawn_once_per_fight_and_read_by_the_action, an_encounter_without_rolls_draws_nothing …(+2) | wiki:wiki_asc/louses.txt | — | §152/§209/INV_ASC_HP+INV_MONSTERS+INV_ROLLS/a_spawn_roll_is_drawn_once_per_fight_and_read_by_the_action |
| maw | yes | test:nom_nom_hits_five_damage_ceil_round_over_two_times, the_maw_follows_the_wikis_transition_table | wiki:wiki_asc/the_maw.txt | 无 AscHP：wiki The Maw: max HP does not change with ascension | §207/§212/INV_MONSTERS+INV_NO_ASC_HP/nom_nom_hits_five_damage_ceil_round_over_two_times |
| nemesis | yes | — | wiki:wiki_asc/nemesis.txt | — | §175/INV_ASC_HP+INV_MONSTERS |
| orb_walker | yes | — | wiki:wiki_asc/orb_walker.txt | — | §208/§214/INV_ASC_HP+INV_MONSTERS |
| reptomancer | yes | — | wiki:wiki_asc/reptomancer.txt | — | §175/INV_ASC_HP+INV_MONSTERS |
| sentry_1 | yes | test:a_turn_boundary_leaves_no_chain_referenced, dexterity_from_the_content_scales_a_real_defend …(+2) | wiki:wiki_asc/sentry.txt | — | §4.2/§134/INV_ASC_HP+INV_MONSTERS/a_turn_boundary_leaves_no_chain_referenced |
| sentry_2 | yes | test:a_long_fight_never_reports_a_step_problem | wiki:wiki_asc/sentry.txt | — | §4.2/§134/INV_ASC_HP+INV_MONSTERS/a_long_fight_never_reports_a_step_problem |
| sentry_3 | yes | test:a_long_fight_never_reports_a_step_problem | wiki:wiki_asc/sentry.txt | — | §134/INV_ASC_HP+INV_MONSTERS/a_long_fight_never_reports_a_step_problem |
| shelled_parasite | yes | test:act_two_fights_act_two_enemies | wiki:wiki_asc/shelled_parasite.txt | — | §130/INV_ASC_HP+INV_MONSTERS/act_two_fights_act_two_enemies |
| slaver_red | yes | — | wiki:wiki_asc/slavers.txt | — | §152/INV_ASC_HP+INV_MONSTERS |
| slime_boss | yes | test:a_phase_split_happens_once_even_under_three_hits, the_boss_is_offered_at_floor_16_and_clears_the_act | wiki:wiki_asc/slime_boss.txt | — | §4.3/INV_ASC_HP+INV_MONSTERS/a_phase_split_happens_once_even_under_three_hits |
| sneaky_gremlin | yes | — | wiki:wiki_asc/sneaky_gremlin.txt | — | §130/§138/INV_ASC_HP+INV_MONSTERS |
| spike_slime_m | orphan (declared) | — | wiki:wiki_asc/spike_slime.txt | — | INV_ASC_HP+INV_MONSTERS |
| spike_slime_s | yes | test:a_minion_flees_when_its_master_falls, the_summon_cap_is_a_loud_failure | wiki:wiki_asc/spike_slime.txt | — | INV_ASC_HP+INV_MONSTERS/a_minion_flees_when_its_master_falls |
| spiker | yes | test:spiker_never_repeats_its_attack_and_buffs_thorns_at_most_six_times, starting_statuses_follow_their_ascension_rows | wiki:wiki_asc/shapes.txt | — | §207/§214/INV_ASC_HP+INV_MONSTERS/spiker_never_repeats_its_attack_and_buffs_thorns_at_most_six_times |
| spire_growth | yes | test:spire_growth_smashes_instead_of_choosing | wiki:wiki_asc/spire_growth.txt | — | §148/§214/INV_ASC_HP+INV_MONSTERS/spire_growth_smashes_instead_of_choosing |
| taskmaster | yes | — | wiki:wiki_asc/taskmaster.txt | — | INV_ASC_HP+INV_MONSTERS |
| the_champ | yes | test:a_weighted_boss_never_repeats_the_move_the_wiki_forbids, the_champ_taunts_every_fourth_round_and_enters_phase_two_below_half …(+1) | wiki:wiki_asc/the_champ.txt | gap §H: A19 的 "Gloat 换成 Defensive Stance" 未实现；Anger 按名清 debuff；第二阶段只做第一次 Execute | §194/INV_ASC_HP+INV_MONSTERS/a_weighted_boss_never_repeats_the_move_the_wiki_forbids |
| the_collector | yes | test:the_collector_draws_by_weight_and_never_buffs_twice_in_a_row, a_minion_is_not_on_the_field_until_its_summon_lands | wiki:wiki_asc/the_collector.txt | gap §H: 25/45/30（0-1 只 Torch Head 时的权重）未分档 | §138/INV_ASC_HP+INV_MONSTERS/the_collector_draws_by_weight_and_never_buffs_twice_in_a_row |
| the_guardian | yes | test:mode_shift_is_a_budget_drained_by_the_health_actually_lost, building_a_guardian_fight_seeds_its_mode_shift_budget_by_ascension …(+1) | wiki:wiki_asc/the_guardian.txt | — | §194/INV_ASC_HP+INV_MONSTERS+INV_SPAWN_COUNTERS/mode_shift_is_a_budget_drained_by_the_health_actually_lost |
| time_eater | yes | test:a_weighted_boss_never_repeats_the_move_the_wiki_forbids | wiki:wiki_asc/time_eater.txt | gap §H: Haste 不清 debuff（没有"清空状态"节点）；`Draw Reduction` 已实现但 wiki 的"A19 另加 2 Slimed"没做 | §138/§211/INV_ASC_HP+INV_MONSTERS/a_weighted_boss_never_repeats_the_move_the_wiki_forbids |
| torch_head | yes | test:a_minion_is_not_on_the_field_until_its_summon_lands | wiki:wiki_asc/torch_head.txt | gap §H: 25/45/30（0-1 只 Torch Head 时的权重）未分档 | §138/§195.3/INV_ASC_HP+INV_MONSTERS/a_minion_is_not_on_the_field_until_its_summon_lands |

## 敌人动作（130）

| Entity | Implemented | RuntimeTested | WikiVerified | Deviation | Evidence |
|---|---|---|---|---|---|
| acid_slime_m.corrosive_spit | yes | harness:ENEMY_DIFF | wiki:wiki_asc/acid_slime.txt | — | §192/INV_ACTIONS+INV_ASC_VARIANTS |
| acid_slime_m.lick | yes | harness:ENEMY_DIFF | wiki:wiki_asc/acid_slime.txt (仅基础值) | 无升档：wiki Acid Slime: M Lick is 1 Weak, no A-row | §206/INV_ACTIONS+INV_NO_ASC |
| acid_slime_m.tackle | yes | harness:ENEMY_DIFF | wiki:wiki_asc/acid_slime.txt | — | §192/INV_ACTIONS+INV_ASC_VARIANTS |
| acid_slime_s.lick | yes | harness:ENEMY_DIFF | wiki:wiki_asc/acid_slime.txt (仅基础值) | 无升档：wiki Acid Slime: S Lick is 1 Weak, no A-row | §206/INV_ACTIONS+INV_NO_ASC |
| acid_slime_s.tackle | yes | harness:ENEMY_DIFF | wiki:wiki_asc/acid_slime.txt | — | INV_ACTIONS+INV_ASC_VARIANTS |
| awakened_one.dark_echo | yes | test:the_awakened_one_draws_phase_one_by_weight_and_flips_on_the_guard | wiki:wiki_asc/awakened_one.txt (仅基础值) | 无升档：wiki Awakened One: no A-row on moves | INV_ACTIONS+INV_NO_ASC/the_awakened_one_draws_phase_one_by_weight_and_flips_on_the_guard |
| awakened_one.rebirth | yes | test:the_awakened_one_survives_its_first_death_and_then_really_dies, the_awakened_one_draws_phase_one_by_weight_and_flips_on_the_guard | wiki:wiki_asc/awakened_one.txt (仅基础值) | 无升档：wiki Awakened One: Rebirth is a rule, no numbers | INV_ACTIONS+INV_NO_ASC/the_awakened_one_survives_its_first_death_and_then_really_dies |
| awakened_one.slash | yes | test:the_awakened_one_draws_phase_one_by_weight_and_flips_on_the_guard | wiki:wiki_asc/awakened_one.txt (仅基础值) | 无升档：wiki Awakened One: no A-row on moves | INV_ACTIONS+INV_NO_ASC/the_awakened_one_draws_phase_one_by_weight_and_flips_on_the_guard |
| awakened_one.sludge | yes | test:the_awakened_one_draws_phase_one_by_weight_and_flips_on_the_guard | wiki:wiki_asc/awakened_one.txt (仅基础值) | 无升档：wiki Awakened One: no A-row on moves | INV_ACTIONS+INV_NO_ASC/the_awakened_one_draws_phase_one_by_weight_and_flips_on_the_guard |
| awakened_one.soul_strike | yes | test:the_awakened_one_draws_phase_one_by_weight_and_flips_on_the_guard | wiki:wiki_asc/awakened_one.txt (仅基础值) | 无升档：wiki Awakened One: no A-row on moves | INV_ACTIONS+INV_NO_ASC/the_awakened_one_draws_phase_one_by_weight_and_flips_on_the_guard |
| awakened_one.tackle | yes | test:the_awakened_one_draws_phase_one_by_weight_and_flips_on_the_guard | wiki:wiki_asc/awakened_one.txt (仅基础值) | 无升档：wiki Awakened One: no A-row on moves | INV_ACTIONS+INV_NO_ASC/the_awakened_one_draws_phase_one_by_weight_and_flips_on_the_guard |
| blue_slaver.rake | yes | test:a_round_one_rule_beats_the_cycle_and_the_cycle_takes_over_after_it | wiki:wiki_asc/slavers.txt | — | INV_ACTIONS+INV_ASC_VARIANTS/a_round_one_rule_beats_the_cycle_and_the_cycle_takes_over_after_it |
| blue_slaver.stab | yes | test:a_round_one_rule_beats_the_cycle_and_the_cycle_takes_over_after_it | wiki:wiki_asc/slavers.txt | — | INV_ACTIONS+INV_ASC_VARIANTS/a_round_one_rule_beats_the_cycle_and_the_cycle_takes_over_after_it |
| book_of_stabbing.big_stab | yes | harness:ENEMY_DIFF | wiki:wiki_asc/book_of_stabbing.txt | — | INV_ACTIONS+INV_ASC_VARIANTS |
| book_of_stabbing.multi_stab | yes | harness:ENEMY_DIFF | wiki:wiki_asc/book_of_stabbing.txt | — | INV_ACTIONS+INV_ASC_VARIANTS |
| bronze_automaton.boost | yes | test:the_automaton_swaps_stunned_for_boost_only_at_a19 | wiki:wiki_asc/bronze_automaton.txt | — | §195.6/INV_ACTIONS+INV_ASC_VARIANTS/the_automaton_swaps_stunned_for_boost_only_at_a19 |
| bronze_automaton.flail | yes | test:the_automaton_swaps_stunned_for_boost_only_at_a19 | wiki:wiki_asc/bronze_automaton.txt | — | §195.6/INV_ACTIONS+INV_ASC_VARIANTS/the_automaton_swaps_stunned_for_boost_only_at_a19 |
| bronze_automaton.hyper_beam | yes | harness:ENEMY_DIFF | wiki:wiki_asc/bronze_automaton.txt | — | INV_ACTIONS+INV_ASC_VARIANTS |
| bronze_automaton.spawn_orbs | yes | test:a_minion_is_not_on_the_field_until_its_summon_lands | wiki:wiki_asc/bronze_automaton.txt (仅基础值) | 无升档：wiki Bronze Automaton: Spawn Orbs has no numbers | §195.6/INV_ACTIONS+INV_NO_ASC/a_minion_is_not_on_the_field_until_its_summon_lands |
| bronze_automaton.stunned | yes | test:the_automaton_swaps_stunned_for_boost_only_at_a19 | wiki:wiki_asc/bronze_automaton.txt (仅基础值) | 无升档：wiki Bronze Automaton: Stunned does nothing | INV_ACTIONS+INV_NO_ASC/the_automaton_swaps_stunned_for_boost_only_at_a19 |
| bronze_orb.beam | yes | test:a_weighted_boss_never_repeats_the_move_the_wiki_forbids | wiki:wiki_asc/bronze_automaton.txt (仅基础值) | 无升档：wiki Bronze Orb: Beam is 8, no A-row | INV_ACTIONS+INV_NO_ASC/a_weighted_boss_never_repeats_the_move_the_wiki_forbids |
| bronze_orb.stasis | yes | test:stasis_steals_the_best_card_and_returns_it_when_the_orb_dies, a_96_card_pile_still_reaches_the_best_card_at_the_end …(+2) | wiki:wiki_asc/bronze_automaton.txt (仅基础值) | 无升档：wiki Bronze Orb: Stasis is a rule, no numbers | §195.4/INV_ACTIONS+INV_NO_ASC/stasis_steals_the_best_card_and_returns_it_when_the_orb_dies |
| bronze_orb.support_beam | yes | test:a_weighted_boss_never_repeats_the_move_the_wiki_forbids | wiki:wiki_asc/bronze_automaton.txt (仅基础值) | 无升档：wiki Bronze Orb: Support Beam is 12 Block, no A-row | INV_ACTIONS+INV_NO_ASC/a_weighted_boss_never_repeats_the_move_the_wiki_forbids |
| byrd.peck | yes | harness:ENEMY_DIFF | wiki:wiki_asc/byrd.txt | — | §213/INV_ACTIONS+INV_ASC_VARIANTS |
| byrd.swoop | yes | harness:ENEMY_DIFF | wiki:wiki_asc/byrd.txt | — | §213/INV_ACTIONS+INV_ASC_VARIANTS |
| chosen.debilitate | yes | harness:ENEMY_DIFF | wiki:wiki_asc/chosen.txt | — | §204/§213/INV_ACTIONS+INV_ASC_VARIANTS |
| chosen.drain | yes | harness:ENEMY_DIFF | wiki:wiki_asc/chosen.txt (仅基础值) | 无升档：wiki Chosen: Drain is 3 Weak + 3 Strength, no A-row | §212/§213/INV_ACTIONS+INV_NO_ASC |
| chosen.hex | yes | test:chosen_swaps_its_opener_at_a17 | wiki:wiki_asc/chosen.txt (仅基础值) | 无升档：wiki Chosen: Hex applies the Hex debuff, no A-row | §212/§213/INV_ACTIONS+INV_NO_ASC/chosen_swaps_its_opener_at_a17 |
| chosen.poke | yes | test:chosen_swaps_its_opener_at_a17 | wiki:wiki_asc/chosen.txt | ours 6+6 / wiki 5+5 —— 有（A2: 6+6） | §204/§213/INV_ACTIONS+INV_ASC_VARIANTS/chosen_swaps_its_opener_at_a17 |
| chosen.zap | yes | harness:ENEMY_DIFF | wiki:wiki_asc/chosen.txt | — | §213/INV_ACTIONS+INV_ASC_VARIANTS |
| cultist.dark_strike | yes | harness:ENEMY_DIFF | wiki:wiki_asc/cultist.txt (仅基础值) | 无升档：wiki Cultist: 6 damage, no A-row | INV_ACTIONS+INV_NO_ASC |
| cultist.incantation | yes | harness:ENEMY_DIFF | wiki:wiki_asc/cultist.txt | — | INV_ACTIONS+INV_ASC_VARIANTS |
| dagger.explode | yes | test:a_dagger_that_explodes_removes_itself_and_hands_the_seat_on | wiki:wiki_asc/dagger.txt (仅基础值) | 无升档：wiki Reptomancer: Explode 25, no A-row | §200/INV_ACTIONS+INV_NO_ASC/a_dagger_that_explodes_removes_itself_and_hands_the_seat_on |
| dagger.wound | yes | harness:ENEMY_DIFF | wiki:wiki_asc/dagger.txt (仅基础值) | 无升档：wiki Reptomancer: dagger moves have no A-row | INV_ACTIONS+INV_NO_ASC |
| darkling.chomp | yes | harness:ENEMY_DIFF | wiki:wiki_asc/darkling.txt | ours 单段 11 / wiki 8×2 —— 有（A2: 9×2） | §137/§193/INV_ACTIONS+INV_ASC_VARIANTS |
| darkling.nip | yes | harness:ENEMY_DIFF | wiki:wiki_asc/darkling.txt (仅基础值) | 无升档：wiki Darkling: Nip is rolled at spawn (A2 changes the roll, §193) | §137/§193/INV_ACTIONS+INV_NO_ASC |
| deca.beam | yes | harness:ENEMY_DIFF | wiki:wiki_asc/donu_and_deca.txt | — | INV_ACTIONS+INV_ASC_VARIANTS |
| deca.square_of_protection | yes | harness:ENEMY_DIFF | wiki:wiki_asc/donu_and_deca.txt | — | INV_ACTIONS+INV_ASC_VARIANTS |
| donu.beam | yes | harness:ENEMY_DIFF | wiki:wiki_asc/donu_and_deca.txt | — | INV_ACTIONS+INV_ASC_VARIANTS |
| donu.circle_of_power | yes | test:donus_circle_of_power_buffs_the_enemy_team_and_not_the_player | wiki:wiki_asc/donu_and_deca.txt (仅基础值) | 无升档：wiki Donu and Deca: Circle of Power has no A-row | INV_ACTIONS+INV_NO_ASC/donus_circle_of_power_buffs_the_enemy_team_and_not_the_player |
| fat_gremlin.smash | yes | harness:ENEMY_DIFF | wiki:wiki_asc/fat_gremlin.txt | — | §214/INV_ACTIONS+INV_ASC_VARIANTS |
| fungi_beast.bite | yes | harness:ENEMY_DIFF | wiki:wiki_asc/fungi_beast.txt (仅基础值) | 无升档：wiki Fungi Beast: Bite has no A-row | §152/INV_ACTIONS+INV_NO_ASC |
| fungi_beast.grow | yes | harness:ENEMY_DIFF | wiki:wiki_asc/fungi_beast.txt | — | §152/INV_ACTIONS+INV_ASC_VARIANTS |
| giant_head.count | yes | test:giant_head_counts_down_then_only_its_time | wiki:wiki_asc/giant_head.txt (仅基础值) | 无升档：wiki Giant Head: Count is flat 13, no A-row；ours 12 伤害 + Weak / 26 伤害 / wiki Weak 1（无伤害）/ 13 —— 本项目是 320 HP 的简化版（§130），招式表跟着简化 | §130/§211/INV_ACTIONS+INV_NO_ASC/giant_head_counts_down_then_only_its_time |
| giant_head.glare | yes | test:giant_head_counts_down_then_only_its_time | wiki:wiki_asc/giant_head.txt (仅基础值) | 无升档：wiki Giant Head: Glare applies 1 Weak, no A-row；ours 12 伤害 + Weak / 26 伤害 / wiki Weak 1（无伤害）/ 13 —— 本项目是 320 HP 的简化版（§130），招式表跟着简化 | §130/§211/INV_ACTIONS+INV_NO_ASC/giant_head_counts_down_then_only_its_time |
| giant_head.it_is_time | yes | test:an_ascension_variant_is_picked_on_the_threshold_and_only_changes_its_number, giant_head_counts_down_then_only_its_time …(+1) | wiki:wiki_asc/giant_head.txt | — | §211/INV_ACTIONS+INV_ASC_VARIANTS/an_ascension_variant_is_picked_on_the_threshold_and_only_changes_its_number |
| gremlin_leader.rally | yes | harness:ENEMY_DIFF | wiki:wiki_asc/gremlin_leader.txt (仅基础值) | 无升档：wiki rows describe "all enemies" wording; this content is the §130 simplification | §130/§134/INV_ACTIONS+INV_NO_ASC |
| gremlin_leader.slash | yes | harness:ENEMY_DIFF | wiki:wiki_asc/gremlin_leader.txt (仅基础值) | 无升档：wiki Gremlin Leader: Slash is 6x3, no A-row；ours 单段 16 / wiki 6×3 —— 无（wiki 无升档值） | §130/§134/INV_ACTIONS+INV_NO_ASC |
| gremlin_leader.summon | yes | test:the_summon_cap_is_a_loud_failure | wiki:wiki_asc/gremlin_leader.txt (仅基础值) | 无升档：wiki Gremlin Leader: Summon has no numbers | §134/INV_ACTIONS+INV_NO_ASC/the_summon_cap_is_a_loud_failure |
| gremlin_nob.bellow | yes | harness:ENEMY_DIFF | wiki:wiki_asc/gremlin_nob.txt | — | §186/INV_ACTIONS+INV_ASC_VARIANTS |
| gremlin_nob.rush | yes | harness:ENEMY_DIFF | wiki:wiki_asc/gremlin_nob.txt | — | §186/INV_ACTIONS+INV_ASC_VARIANTS |
| gremlin_nob.skull_bash | yes | harness:ENEMY_DIFF | wiki:wiki_asc/gremlin_nob.txt | — | INV_ACTIONS+INV_ASC_VARIANTS |
| gremlin_wizard.charging | yes | harness:ENEMY_DIFF | wiki:wiki_asc/gremlin_wizard.txt (仅基础值) | 无升档：wiki Gremlin Wizard: Charging has no numbers | §0/INV_ACTIONS+INV_NO_ASC |
| gremlin_wizard.ultimate_blast | yes | harness:ENEMY_DIFF | wiki:wiki_asc/gremlin_wizard.txt | — | INV_ACTIONS+INV_ASC_VARIANTS |
| hexaghost.activate | yes | test:hexaghost_plays_the_wikis_seven_move_pattern_after_its_two_openers | wiki:wiki_asc/hexaghost.txt (仅基础值) | 无升档：wiki Hexaghost: Activate has no numbers | INV_ACTIONS+INV_NO_ASC/hexaghost_plays_the_wikis_seven_move_pattern_after_its_two_openers |
| hexaghost.divider | yes | test:hexaghosts_divider_repeats_ceil_of_hp_over_twelve_plus_one, hexaghost_plays_the_wikis_seven_move_pattern_after_its_two_openers | wiki:wiki_asc/hexaghost.txt (仅基础值) | 无升档：wiki Hexaghost: Divider has no A-row | INV_ACTIONS+INV_NO_ASC/hexaghosts_divider_repeats_ceil_of_hp_over_twelve_plus_one |
| hexaghost.inferno | yes | test:upgrading_burns_walks_every_pile_and_skips_cards_without_an_upgrade, hexaghost_plays_the_wikis_seven_move_pattern_after_its_two_openers | wiki:wiki_asc/hexaghost.txt | — | §195.7/INV_ACTIONS+INV_ASC_VARIANTS/upgrading_burns_walks_every_pile_and_skips_cards_without_an_upgrade |
| hexaghost.inflame | yes | test:hexaghost_plays_the_wikis_seven_move_pattern_after_its_two_openers | wiki:wiki_asc/hexaghost.txt | — | INV_ACTIONS+INV_ASC_VARIANTS/hexaghost_plays_the_wikis_seven_move_pattern_after_its_two_openers |
| hexaghost.sear | yes | test:hexaghost_plays_the_wikis_seven_move_pattern_after_its_two_openers | wiki:wiki_asc/hexaghost.txt | — | INV_ACTIONS+INV_ASC_VARIANTS/hexaghost_plays_the_wikis_seven_move_pattern_after_its_two_openers |
| hexaghost.tackle | yes | test:hexaghost_plays_the_wikis_seven_move_pattern_after_its_two_openers | wiki:wiki_asc/hexaghost.txt | — | INV_ACTIONS+INV_ASC_VARIANTS/hexaghost_plays_the_wikis_seven_move_pattern_after_its_two_openers |
| jaw_worm.bellow | yes | test:one_action_can_carry_two_ascension_tiers | wiki:wiki_asc/jaw_worm.txt | — | INV_ACTIONS+INV_ASC_VARIANTS/one_action_can_carry_two_ascension_tiers |
| jaw_worm.chomp | yes | harness:ENEMY_DIFF | wiki:wiki_asc/jaw_worm.txt | — | INV_ACTIONS+INV_ASC_VARIANTS |
| jaw_worm.thrash | yes | harness:ENEMY_DIFF | wiki:wiki_asc/jaw_worm.txt (仅基础值) | 无升档：wiki Jaw Worm: Thrash has no A-row | INV_ACTIONS+INV_NO_ASC |
| lagavulin.attack | yes | test:an_ascension_variant_replaces_the_program_at_its_threshold | wiki:wiki_asc/lagavulin.txt | — | §173/INV_ACTIONS+INV_ASC_VARIANTS/an_ascension_variant_replaces_the_program_at_its_threshold |
| lagavulin.siphon_soul | yes | test:an_ascension_variant_is_picked_on_the_threshold_and_only_changes_its_number | wiki:wiki_asc/lagavulin.txt | — | §174/§204/INV_ACTIONS+INV_ASC_VARIANTS/an_ascension_variant_is_picked_on_the_threshold_and_only_changes_its_number |
| lagavulin.sleep | yes | harness:ENEMY_DIFF | wiki:wiki_asc/lagavulin.txt (仅基础值) | 无升档：wiki Lagavulin: Sleep does nothing | §173/§193/INV_ACTIONS+INV_NO_ASC |
| looter.escape | yes | test:a_looter_steals_thievery_gold_on_every_attack_and_carries_it_away, escaping_moves_the_counter_instead_of_copying_it …(+1) | wiki:wiki_asc/thieves.txt (仅基础值) | 无升档：wiki Thieves: Escape has no numbers | §201/INV_ACTIONS+INV_NO_ASC/a_looter_steals_thievery_gold_on_every_attack_and_carries_it_away |
| looter.lunge | yes | test:an_ascension_variant_is_picked_on_the_threshold_and_only_changes_its_number, the_looter_mugs_twice_then_bombs_then_escapes | wiki:wiki_asc/thieves.txt | — | §201/INV_ACTIONS+INV_ASC_VARIANTS/an_ascension_variant_is_picked_on_the_threshold_and_only_changes_its_number |
| looter.mug | yes | test:ascension_two_makes_the_looter_mug_hit_for_eleven, a_looter_steals_thievery_gold_on_every_attack_and_carries_it_away …(+3) | wiki:wiki_asc/thieves.txt | — | §201/§205/INV_ACTIONS+INV_ASC_VARIANTS/ascension_two_makes_the_looter_mug_hit_for_eleven |
| looter.smoke_bomb | yes | test:the_looter_mugs_twice_then_bombs_then_escapes | wiki:wiki_asc/thieves.txt (仅基础值) | 无升档：wiki Thieves: 6 Block, no A-row | §201/INV_ACTIONS+INV_NO_ASC/the_looter_mugs_twice_then_bombs_then_escapes |
| louse_green.bite | yes | harness:ENEMY_DIFF | wiki:wiki_asc/louses.txt (仅基础值) | unwired：没有敌人记录列出它（`INV_UNWIRED`）；无升档：wiki Louses: Bite is rolled at spawn (A2 changes the roll, §193) | §152/§193/INV_ACTIONS+INV_NO_ASC |
| louse_green.grow | yes | harness:ENEMY_DIFF | wiki:wiki_asc/louses.txt | unwired：没有敌人记录列出它（`INV_UNWIRED`） | §152/§193/INV_ACTIONS+INV_ASC_VARIANTS |
| louse_red.bite | yes | test:a_spawn_roll_is_drawn_once_per_fight_and_read_by_the_action | wiki:wiki_asc/louses.txt (仅基础值) | 无升档：wiki Louses: Bite is rolled at spawn (A2 changes the roll, §193) | §152/§193/INV_ACTIONS+INV_NO_ASC/a_spawn_roll_is_drawn_once_per_fight_and_read_by_the_action |
| louse_red.grow | yes | harness:ENEMY_DIFF | wiki:wiki_asc/louses.txt | — | §152/§193/INV_ACTIONS+INV_ASC_VARIANTS |
| louse_red.spit_web | yes | harness:ENEMY_DIFF | wiki:wiki_asc/louses.txt (仅基础值) | 无升档：wiki Louses: Spit Web is 2 Weak, no A-row | §152/§193/INV_ACTIONS+INV_NO_ASC |
| maw.drool | yes | test:the_maw_follows_the_wikis_transition_table | wiki:wiki_asc/the_maw.txt | — | §137/§212/INV_ACTIONS+INV_ASC_VARIANTS/the_maw_follows_the_wikis_transition_table |
| maw.nom_nom | yes | test:nom_nom_hits_five_damage_ceil_round_over_two_times, the_maw_follows_the_wikis_transition_table | wiki:wiki_asc/the_maw.txt (仅基础值) | 无升档：wiki The Maw: Nom Nom is 5 x ceil(turn/2), no A-row | §137/§212/INV_ACTIONS+INV_NO_ASC/nom_nom_hits_five_damage_ceil_round_over_two_times |
| maw.roar | yes | test:the_maw_follows_the_wikis_transition_table | wiki:wiki_asc/the_maw.txt | — | §137/§212/INV_ACTIONS+INV_ASC_VARIANTS/the_maw_follows_the_wikis_transition_table |
| maw.slam | yes | test:the_maw_follows_the_wikis_transition_table | wiki:wiki_asc/the_maw.txt | — | §137/§212/INV_ACTIONS+INV_ASC_VARIANTS/the_maw_follows_the_wikis_transition_table |
| nemesis.scythe | yes | harness:ENEMY_DIFF | wiki:wiki_asc/nemesis.txt (仅基础值) | 无升档：wiki Nemesis: Scythe has no A-row | §175/INV_ACTIONS+INV_NO_ASC |
| nemesis.tri_attack | yes | harness:ENEMY_DIFF | wiki:wiki_asc/nemesis.txt | — | §175/INV_ACTIONS+INV_ASC_VARIANTS |
| nemesis.tri_burn | yes | harness:ENEMY_DIFF | wiki:wiki_asc/nemesis.txt | — | §175/INV_ACTIONS+INV_ASC_VARIANTS |
| orb_walker.claw | yes | harness:ENEMY_DIFF | wiki:wiki_asc/orb_walker.txt | — | §214/INV_ACTIONS+INV_ASC_VARIANTS |
| orb_walker.laser | yes | harness:ENEMY_DIFF | wiki:wiki_asc/orb_walker.txt | — | §214/INV_ACTIONS+INV_ASC_VARIANTS |
| reptomancer.big_bite | yes | harness:ENEMY_DIFF | wiki:wiki_asc/reptomancer.txt | — | §175/INV_ACTIONS+INV_ASC_VARIANTS |
| reptomancer.snake_strike | yes | harness:ENEMY_DIFF | wiki:wiki_asc/reptomancer.txt | — | §175/INV_ACTIONS+INV_ASC_VARIANTS |
| reptomancer.spawn_dagger | yes | harness:ENEMY_DIFF | wiki:wiki_asc/reptomancer.txt | — | §175/INV_ACTIONS+INV_ASC_VARIANTS |
| sentry.beam | yes | harness:ENEMY_DIFF | wiki:wiki_asc/sentry.txt | — | §4.2/INV_ACTIONS+INV_ASC_VARIANTS |
| sentry.bolt | yes | harness:ENEMY_DIFF | wiki:wiki_asc/sentry.txt | ours 10 伤害 / wiki 塞 2 张 Dazed —— 有（A18: 3 张） | §4.2/INV_ACTIONS+INV_ASC_VARIANTS |
| shelled_parasite.double_strike | yes | harness:ENEMY_DIFF | wiki:wiki_asc/shelled_parasite.txt | — | §130/INV_ACTIONS+INV_ASC_VARIANTS |
| shelled_parasite.suck | yes | harness:ENEMY_DIFF | wiki:wiki_asc/shelled_parasite.txt | — | §130/INV_ACTIONS+INV_ASC_VARIANTS |
| slaver_red.entangle | yes | harness:ENEMY_DIFF | wiki:wiki_asc/slavers.txt (仅基础值) | 无升档：wiki Slavers: Entangle applies a status, no A-row | §152/§196/INV_ACTIONS+INV_NO_ASC |
| slaver_red.scrape | yes | harness:ENEMY_DIFF | wiki:wiki_asc/slavers.txt | — | §186/§187/INV_ACTIONS+INV_ASC_VARIANTS |
| slaver_red.stab | yes | harness:ENEMY_DIFF | wiki:wiki_asc/slavers.txt | — | §152/§196/INV_ACTIONS+INV_ASC_VARIANTS |
| slime_boss.goop_spray | yes | harness:ENEMY_DIFF | wiki:wiki_asc/slime_boss.txt | — | §4.3/INV_ACTIONS+INV_ASC_VARIANTS |
| slime_boss.preparing | yes | harness:ENEMY_DIFF | wiki:wiki_asc/slime_boss.txt (仅基础值) | 无升档：wiki Slime Boss: Preparing has no numbers | §4.3/INV_ACTIONS+INV_NO_ASC |
| slime_boss.slam | yes | test:a_combinator_rule_switches_the_boss_move | wiki:wiki_asc/slime_boss.txt | — | §4.3/INV_ACTIONS+INV_ASC_VARIANTS/a_combinator_rule_switches_the_boss_move |
| sneaky_gremlin.puncture | yes | harness:ENEMY_DIFF | wiki:wiki_asc/sneaky_gremlin.txt | — | INV_ACTIONS+INV_ASC_VARIANTS |
| spike_slime_m.flame_tackle | yes | harness:ENEMY_DIFF | wiki:wiki_asc/spike_slime.txt | — | INV_ACTIONS+INV_ASC_VARIANTS |
| spike_slime_m.lick | yes | harness:ENEMY_DIFF | wiki:wiki_asc/spike_slime.txt (仅基础值) | 无升档：wiki Spike Slime: M Lick is 1 Frail, no A-row (only L has A17) | INV_ACTIONS+INV_NO_ASC |
| spike_slime_s.tackle | yes | harness:ENEMY_DIFF | wiki:wiki_asc/spike_slime.txt | — | INV_ACTIONS+INV_ASC_VARIANTS |
| spiker.cut | yes | test:spiker_never_repeats_its_attack_and_buffs_thorns_at_most_six_times | wiki:wiki_asc/shapes.txt | ours 8 / wiki 7 —— 有（A2: 9） | §214/INV_ACTIONS+INV_ASC_VARIANTS/spiker_never_repeats_its_attack_and_buffs_thorns_at_most_six_times |
| spiker.spike | yes | test:spiker_never_repeats_its_attack_and_buffs_thorns_at_most_six_times | wiki:wiki_asc/shapes.txt (仅基础值) | 无升档：wiki Shapes#Spiker: Buff Thorns is always +2 Thorns, no A-row | §214/INV_ACTIONS+INV_NO_ASC/spiker_never_repeats_its_attack_and_buffs_thorns_at_most_six_times |
| spire_growth.aggressive | yes | harness:ENEMY_DIFF | wiki:wiki_asc/spire_growth.txt | — | §147/§214/INV_ACTIONS+INV_ASC_VARIANTS |
| spire_growth.aggressive_heavy | yes | test:spire_growth_smashes_instead_of_choosing | wiki:wiki_asc/spire_growth.txt | — | §147/§214/INV_ACTIONS+INV_ASC_VARIANTS/spire_growth_smashes_instead_of_choosing |
| spire_growth.strategic | yes | harness:ENEMY_DIFF | wiki:wiki_asc/spire_growth.txt | ours Constricted 2 / wiki 10 —— 有（A2: 12） | §147/§214/INV_ACTIONS+INV_ASC_VARIANTS |
| taskmaster.scouring_whip | yes | harness:ENEMY_DIFF | wiki:wiki_asc/taskmaster.txt | — | INV_ACTIONS+INV_ASC_VARIANTS |
| the_champ.anger | yes | test:the_champ_taunts_every_fourth_round_and_enters_phase_two_below_half | wiki:wiki_asc/the_champ.txt | — | INV_ACTIONS+INV_ASC_VARIANTS/the_champ_taunts_every_fourth_round_and_enters_phase_two_below_half |
| the_champ.defensive_stance | yes | test:the_champ_swaps_gloat_for_defensive_stance_at_a19 | wiki:wiki_asc/the_champ.txt | — | §194/INV_ACTIONS+INV_ASC_VARIANTS/the_champ_swaps_gloat_for_defensive_stance_at_a19 |
| the_champ.execute | yes | test:the_champ_taunts_every_fourth_round_and_enters_phase_two_below_half | wiki:wiki_asc/the_champ.txt (仅基础值) | 无升档：wiki The Champ: Execute is 10x2, no A-row；ours 单段 30 / wiki 10×2 —— 无 | §194/INV_ACTIONS+INV_NO_ASC/the_champ_taunts_every_fourth_round_and_enters_phase_two_below_half |
| the_champ.face_slap | yes | harness:ENEMY_DIFF | wiki:wiki_asc/the_champ.txt | — | INV_ACTIONS+INV_ASC_VARIANTS |
| the_champ.gloat | yes | test:the_champ_swaps_gloat_for_defensive_stance_at_a19 | wiki:wiki_asc/the_champ.txt | — | INV_ACTIONS+INV_ASC_VARIANTS/the_champ_swaps_gloat_for_defensive_stance_at_a19 |
| the_champ.heavy_slash | yes | test:a_weighted_boss_never_repeats_the_move_the_wiki_forbids, the_champ_taunts_every_fourth_round_and_enters_phase_two_below_half | wiki:wiki_asc/the_champ.txt | ours 18（写成了 A4 值） / wiki 16 —— 有（A4: 18） | INV_ACTIONS+INV_ASC_VARIANTS/a_weighted_boss_never_repeats_the_move_the_wiki_forbids |
| the_champ.taunt | yes | test:the_champ_taunts_every_fourth_round_and_enters_phase_two_below_half | wiki:wiki_asc/the_champ.txt (仅基础值) | 无升档：wiki The Champ: Taunt has no A-row | INV_ACTIONS+INV_NO_ASC/the_champ_taunts_every_fourth_round_and_enters_phase_two_below_half |
| the_collector.buff | yes | test:the_collector_draws_by_weight_and_never_buffs_twice_in_a_row | wiki:wiki_asc/the_collector.txt | — | INV_ACTIONS+INV_ASC_VARIANTS/the_collector_draws_by_weight_and_never_buffs_twice_in_a_row |
| the_collector.fireball | yes | test:the_collector_draws_by_weight_and_never_buffs_twice_in_a_row | wiki:wiki_asc/the_collector.txt | — | §195.3/INV_ACTIONS+INV_ASC_VARIANTS/the_collector_draws_by_weight_and_never_buffs_twice_in_a_row |
| the_collector.mega_debuff | yes | harness:ENEMY_DIFF | wiki:wiki_asc/the_collector.txt | — | INV_ACTIONS+INV_ASC_VARIANTS |
| the_collector.spawn | yes | test:a_minion_is_not_on_the_field_until_its_summon_lands | wiki:wiki_asc/the_collector.txt (仅基础值) | 无升档：wiki The Collector: Spawn has no numbers | §195.3/INV_ACTIONS+INV_NO_ASC/a_minion_is_not_on_the_field_until_its_summon_lands |
| the_guardian.charging_up | yes | harness:ENEMY_DIFF | wiki:wiki_asc/the_guardian.txt (仅基础值) | 无升档：wiki The Guardian: Mode Shift moves, no A-row on the move itself | §194/INV_ACTIONS+INV_NO_ASC |
| the_guardian.defensive_mode | yes | test:mode_shift_is_a_budget_drained_by_the_health_actually_lost | wiki:wiki_asc/the_guardian.txt | — | §195.1/INV_ACTIONS+INV_ASC_VARIANTS/mode_shift_is_a_budget_drained_by_the_health_actually_lost |
| the_guardian.fierce_bash | yes | harness:ENEMY_DIFF | wiki:wiki_asc/the_guardian.txt | — | §194/INV_ACTIONS+INV_ASC_VARIANTS |
| the_guardian.roll_attack | yes | harness:ENEMY_DIFF | wiki:wiki_asc/the_guardian.txt | — | §194/INV_ACTIONS+INV_ASC_VARIANTS |
| the_guardian.twin_slam | yes | test:sharp_hide_hurts_the_player_for_attacks_and_only_attacks | wiki:wiki_asc/the_guardian.txt (仅基础值) | 无升档：wiki The Guardian: no A-row | INV_ACTIONS+INV_NO_ASC/sharp_hide_hurts_the_player_for_attacks_and_only_attacks |
| the_guardian.vent_steam | yes | harness:ENEMY_DIFF | wiki:wiki_asc/the_guardian.txt (仅基础值) | 无升档：wiki The Guardian: Vent Steam has no A-row | §194/INV_ACTIONS+INV_NO_ASC |
| the_guardian.whirlwind | yes | harness:ENEMY_DIFF | wiki:wiki_asc/the_guardian.txt (仅基础值) | 无升档：wiki The Guardian: no A-row | §194/INV_ACTIONS+INV_NO_ASC |
| time_eater.haste | yes | harness:ENEMY_DIFF | wiki:wiki_asc/time_eater.txt | — | §194/INV_ACTIONS+INV_ASC_VARIANTS |
| time_eater.head_slam | yes | test:a_weighted_boss_never_repeats_the_move_the_wiki_forbids | wiki:wiki_asc/time_eater.txt | — | §195.7/INV_ACTIONS+INV_ASC_VARIANTS/a_weighted_boss_never_repeats_the_move_the_wiki_forbids |
| time_eater.reverberate | yes | test:a_weighted_boss_never_repeats_the_move_the_wiki_forbids | wiki:wiki_asc/time_eater.txt | — | §194/INV_ACTIONS+INV_ASC_VARIANTS/a_weighted_boss_never_repeats_the_move_the_wiki_forbids |
| time_eater.ripple | yes | test:a_weighted_boss_never_repeats_the_move_the_wiki_forbids | wiki:wiki_asc/time_eater.txt | — | §195.7/INV_ACTIONS+INV_ASC_VARIANTS/a_weighted_boss_never_repeats_the_move_the_wiki_forbids |
| torch_head.tackle | yes | harness:ENEMY_DIFF | wiki:wiki_asc/torch_head.txt (仅基础值) | 无升档：wiki Torch Head: Tackle is 7, no A-row | INV_ACTIONS+INV_NO_ASC |

## 卡牌（51）

| Entity | Implemented | RuntimeTested | WikiVerified | Deviation | Evidence |
|---|---|---|---|---|---|
| anger | yes | test:the_same_state_hashes_the_same_and_a_change_moves_it, the_potion_chance_walks_the_wikis_ten_percent …(+4) | spec:INV_CARDS | — | INV_CARDS/the_same_state_hashes_the_same_and_a_change_moves_it |
| anger+ | yes | harness:CARD_DIFF | spec:INV_CARDS | — | INV_CARDS |
| apparition | yes | harness:CARD_DIFF | spec:INV_CARDS | — | §149/INV_CARDS |
| apparition+ | yes | harness:CARD_DIFF | spec:INV_CARDS | — | INV_CARDS |
| ascenders_bane | yes | harness:CARD_DIFF | spec:INV_CARDS | — | §183/§189/INV_CARDS |
| bandage_up | yes | test:colorless_potion_offers_three_colorless_cards_and_the_pick_lands_in_hand | spec:INV_CARDS | — | §191/INV_CARDS/colorless_potion_offers_three_colorless_cards_and_the_pick_lands_in_hand |
| barricade | yes | harness:CARD_DIFF | spec:INV_CARDS | — | INV_CARDS |
| barricade+ | yes | harness:CARD_DIFF | spec:INV_CARDS | — | INV_CARDS |
| bash | yes | test:card_rarity_is_readable_and_the_schema_moved_the_version, a_new_run_is_before_the_map_with_a_known_start …(+3) | spec:INV_CARDS | — | §2/§2.1/INV_CARDS/card_rarity_is_readable_and_the_schema_moved_the_version |
| bash+ | yes | harness:CARD_DIFF | spec:INV_CARDS | — | INV_CARDS |
| berserk | yes | harness:CARD_DIFF | spec:INV_CARDS | — | §197/§199/INV_CARDS |
| berserk+ | yes | harness:CARD_DIFF | spec:INV_CARDS | — | INV_CARDS |
| blind | yes | test:colorless_potion_offers_three_colorless_cards_and_the_pick_lands_in_hand | spec:INV_CARDS | — | INV_CARDS/colorless_potion_offers_three_colorless_cards_and_the_pick_lands_in_hand |
| blur | yes | harness:CARD_DIFF | spec:INV_CARDS | — | INV_CARDS |
| blur+ | yes | harness:CARD_DIFF | spec:INV_CARDS | — | INV_CARDS |
| buffer | yes | harness:CARD_DIFF | spec:INV_CARDS | — | §149/INV_CARDS |
| buffer+ | yes | harness:CARD_DIFF | spec:INV_CARDS | — | INV_CARDS |
| burn | yes | test:upgrading_burns_walks_every_pile_and_skips_cards_without_an_upgrade | spec:INV_CARDS | — | §175/INV_CARDS/upgrading_burns_walks_every_pile_and_skips_cards_without_an_upgrade |
| burn+ | yes | test:upgrading_burns_walks_every_pile_and_skips_cards_without_an_upgrade | spec:INV_CARDS | — | INV_CARDS/upgrading_burns_walks_every_pile_and_skips_cards_without_an_upgrade |
| clothesline | yes | harness:CARD_DIFF | spec:INV_CARDS | — | INV_CARDS |
| clothesline+ | yes | harness:CARD_DIFF | spec:INV_CARDS | — | INV_CARDS |
| combust | yes | harness:CARD_DIFF | spec:INV_CARDS | — | INV_CARDS |
| combust+ | yes | harness:CARD_DIFF | spec:INV_CARDS | — | INV_CARDS |
| dark_shackles | yes | test:colorless_potion_offers_three_colorless_cards_and_the_pick_lands_in_hand | spec:INV_CARDS | — | INV_CARDS/colorless_potion_offers_three_colorless_cards_and_the_pick_lands_in_hand |
| dazed | yes | test:upgrading_burns_walks_every_pile_and_skips_cards_without_an_upgrade, hex_shuffles_a_dazed_only_for_non_attack_cards | spec:INV_CARDS | — | §189/§191/INV_CARDS/upgrading_burns_walks_every_pile_and_skips_cards_without_an_upgrade |
| defend | yes | test:dexterity_from_the_content_scales_a_real_defend, card_tags_are_readable_and_a_junk_card_is_not_a_reward …(+15) | spec:INV_CARDS | — | §3.1/§6.5/INV_CARDS/dexterity_from_the_content_scales_a_real_defend |
| defend+ | yes | harness:CARD_DIFF | spec:INV_CARDS | — | INV_CARDS |
| inflame | yes | harness:CARD_DIFF | spec:INV_CARDS | — | INV_CARDS |
| inflame+ | yes | harness:CARD_DIFF | spec:INV_CARDS | — | INV_CARDS |
| injury | yes | test:the_event_vocabulary_parses_and_refuses_what_it_does_not_know, an_event_option_can_apply_several_effects_at_once …(+1) | spec:INV_CARDS | — | §143/INV_CARDS/the_event_vocabulary_parses_and_refuses_what_it_does_not_know |
| iron_wave | yes | test:stasis_steals_the_best_card_and_returns_it_when_the_orb_dies, tied_rarities_are_broken_by_the_combat_rng | spec:INV_CARDS | — | §72.5/INV_CARDS/stasis_steals_the_best_card_and_returns_it_when_the_orb_dies |
| iron_wave+ | yes | harness:CARD_DIFF | spec:INV_CARDS | — | INV_CARDS |
| metallicize | yes | test:decay_predicate_splits_the_two_groups, the_prototype_namespace_supplies_metallicize_and_ritual | spec:INV_CARDS | — | INV_CARDS/decay_predicate_splits_the_two_groups |
| metallicize+ | yes | harness:CARD_DIFF | spec:INV_CARDS | — | INV_CARDS |
| patient_guard | yes | test:the_keyword_cells_are_in_the_image | spec:INV_CARDS | — | INV_CARDS/the_keyword_cells_are_in_the_image |
| patient_guard+ | yes | harness:CARD_DIFF | spec:INV_CARDS | — | INV_CARDS |
| sentinel | yes | test:the_keyword_cells_are_in_the_image, a_sink_appends_after_the_callers_prefix_and_a_tiny_sink_is_still_ok | spec:INV_CARDS | — | §144/INV_CARDS/the_keyword_cells_are_in_the_image |
| sentinel+ | yes | harness:CARD_DIFF | spec:INV_CARDS | — | INV_CARDS |
| slimed | yes | test:card_tags_are_readable_and_a_junk_card_is_not_a_reward, card_rarity_is_readable_and_the_schema_moved_the_version …(+1) | spec:INV_CARDS | — | §10/§192/INV_CARDS/card_tags_are_readable_and_a_junk_card_is_not_a_reward |
| strike | yes | test:an_innate_card_is_pulled_to_the_top_of_the_draw_pile, a_card_play_leaves_no_chain_referenced …(+76) | spec:INV_CARDS | — | §6.5/§72.5/INV_CARDS/an_innate_card_is_pulled_to_the_top_of_the_draw_pile |
| strike+ | yes | test:card_tags_are_readable_and_a_junk_card_is_not_a_reward, smithing_replaces_the_card_with_its_upgraded_row …(+6) | spec:INV_CARDS | — | INV_CARDS/card_tags_are_readable_and_a_junk_card_is_not_a_reward |
| swift_strike | yes | test:an_innate_card_is_pulled_to_the_top_of_the_draw_pile, the_keyword_cells_are_in_the_image | spec:INV_CARDS | — | INV_CARDS/an_innate_card_is_pulled_to_the_top_of_the_draw_pile |
| swift_strike+ | yes | harness:CARD_DIFF | spec:INV_CARDS | — | INV_CARDS |
| twin_strike | yes | harness:CARD_DIFF | spec:INV_CARDS | — | §72.5/INV_CARDS |
| twin_strike+ | yes | harness:CARD_DIFF | spec:INV_CARDS | — | INV_CARDS |
| uppercut | yes | test:stasis_steals_the_best_card_and_returns_it_when_the_orb_dies, a_96_card_pile_still_reaches_the_best_card_at_the_end …(+2) | spec:INV_CARDS | — | INV_CARDS/stasis_steals_the_best_card_and_returns_it_when_the_orb_dies |
| uppercut+ | yes | harness:CARD_DIFF | spec:INV_CARDS | — | INV_CARDS |
| void | yes | harness:CARD_DIFF | spec:INV_CARDS | — | INV_CARDS |
| whirlwind | yes | test:an_upgraded_card_row_is_buildable, the_keyword_cells_are_in_the_image …(+5) | spec:INV_CARDS | — | INV_CARDS/an_upgraded_card_row_is_buildable |
| whirlwind+ | yes | test:an_upgraded_card_row_is_buildable | spec:INV_CARDS | — | INV_CARDS/an_upgraded_card_row_is_buildable |
| wound | yes | harness:CARD_DIFF | spec:INV_CARDS | — | §173/INV_CARDS |

## 状态（43）

| Entity | Implemented | RuntimeTested | WikiVerified | Deviation | Evidence |
|---|---|---|---|---|---|
| ritual | yes | test:ritual_grants_strength_at_the_end_of_the_turn, decay_predicate_splits_the_two_groups …(+1) | spec:INV_STATUSES | — | §213/INV_STATUSES/ritual_grants_strength_at_the_end_of_the_turn |
| standard.artifact | yes | test:artifact_turns_a_debuff_into_a_prevented_beat_naming_the_blocked_status, artifact_eats_one_debuff_and_nothing_else …(+6) | spec:INV_STATUSES | — | §116/§117/INV_STATUSES/artifact_turns_a_debuff_into_a_prevented_beat_naming_the_blocked_status |
| standard.barricade | yes | test:barricade_keeps_block_forever_and_blur_only_for_one_turn | spec:INV_STATUSES | — | §197/INV_STATUSES/barricade_keeps_block_forever_and_blur_only_for_one_turn |
| standard.berserk | yes | test:berserk_adds_one_energy_per_stack_at_turn_start | spec:INV_STATUSES | — | §199/§210/INV_STATUSES/berserk_adds_one_energy_per_stack_at_turn_start |
| standard.blur | yes | test:barricade_keeps_block_forever_and_blur_only_for_one_turn | spec:INV_STATUSES | — | §197/INV_STATUSES/barricade_keeps_block_forever_and_blur_only_for_one_turn |
| standard.buffer | yes | test:the_damage_pipeline_honours_intangible_buffer_and_plated_armor | spec:INV_STATUSES | — | §125/§149/INV_STATUSES/the_damage_pipeline_honours_intangible_buffer_and_plated_armor |
| standard.combust | yes | test:flame_barrier_hits_back_and_combust_burns_everyone | spec:INV_STATUSES | — | §119/INV_STATUSES/flame_barrier_hits_back_and_combust_burns_everyone |
| standard.constricted | yes | test:constricted_loses_its_stacks_of_hp_through_block_at_turn_end, statuses_outside_the_five_axes_are_readable_by_name …(+1) | spec:INV_STATUSES | — | §175/§214/INV_STATUSES/constricted_loses_its_stacks_of_hp_through_block_at_turn_end |
| standard.curiosity | yes | test:the_awakened_one_survives_its_first_death_and_then_really_dies | spec:INV_STATUSES | — | §194/INV_STATUSES/the_awakened_one_survives_its_first_death_and_then_really_dies |
| standard.curl_up | yes | test:curl_up_pays_out_once_and_only_for_a_hit_that_draws_blood | spec:INV_STATUSES | — | §208/§209/INV_STATUSES/curl_up_pays_out_once_and_only_for_a_hit_that_draws_blood |
| standard.dexterity | yes | test:dexterity_from_the_content_scales_a_real_defend, global_status_lines_use_the_gs_prefix_and_list_order …(+5) | spec:INV_STATUSES | — | §174/§204/INV_STATUSES/dexterity_from_the_content_scales_a_real_defend |
| standard.draw_reduction | yes | test:draw_reduction_costs_exactly_one_turns_draw_and_then_expires | spec:INV_STATUSES | — | §10/§195.7/INV_STATUSES/draw_reduction_costs_exactly_one_turns_draw_and_then_expires |
| standard.duplication | yes | test:duplication_plays_the_program_twice_but_pays_and_counts_once | spec:INV_STATUSES | — | §181/INV_STATUSES/duplication_plays_the_program_twice_but_pays_and_counts_once |
| standard.enrage | yes | test:a_card_play_leaves_no_chain_referenced, enrage_answers_only_a_skill | spec:INV_STATUSES | — | §117/INV_STATUSES/a_card_play_leaves_no_chain_referenced |
| standard.entangle_ready | yes | harness:ENEMY_DIFF | spec:INV_STATUSES | — | §196/INV_STATUSES |
| standard.entangled | yes | test:entangled_refuses_attacks_but_not_skills_and_expires_at_turn_end | spec:INV_STATUSES | — | §195.7/§196/INV_STATUSES/entangled_refuses_attacks_but_not_skills_and_expires_at_turn_end |
| standard.fairy_in_a_bottle | yes | test:the_charm_catches_one_killing_blow_and_is_spent | spec:INV_STATUSES | — | §180/INV_STATUSES/the_charm_catches_one_killing_blow_and_is_spent |
| standard.flame_barrier | yes (test-only) | test:flame_barrier_hits_back_and_combust_burns_everyone | spec:INV_STATUSES | — | §119/INV_STATUSES/flame_barrier_hits_back_and_combust_burns_everyone |
| standard.flying | yes | test:flying_halves_attack_damage_and_loses_a_stack_per_hit | spec:INV_STATUSES | — | §208/§216/INV_STATUSES/flying_halves_attack_damage_and_loses_a_stack_per_hit |
| standard.frail | yes | test:damage_table_rows_are_the_frozen_shape, standard_status_ids_are_byte_ordered_not_registration_ordered …(+3) | spec:INV_STATUSES | — | §196/§212/INV_STATUSES/damage_table_rows_are_the_frozen_shape |
| standard.hex | yes | test:hex_shuffles_a_dazed_only_for_non_attack_cards | spec:INV_STATUSES | — | §210/§213/INV_STATUSES/hex_shuffles_a_dazed_only_for_non_attack_cards |
| standard.intangible | yes | test:the_damage_pipeline_honours_intangible_buffer_and_plated_armor | spec:INV_STATUSES | — | §149/§210/INV_STATUSES/the_damage_pipeline_honours_intangible_buffer_and_plated_armor |
| standard.lose_dexterity | yes | — | spec:INV_STATUSES | — | §158/INV_STATUSES |
| standard.lose_strength | yes | test:flex_potion_gives_strength_and_takes_it_back | spec:INV_STATUSES | — | §158/INV_STATUSES/flex_potion_gives_strength_and_takes_it_back |
| standard.metallicize | yes | test:metallicize_grants_block_at_the_end_of_the_turn, plated_armor_and_metallicize_both_pay_block_at_turn_end | spec:INV_STATUSES | — | §107/§194/INV_STATUSES/metallicize_grants_block_at_the_end_of_the_turn |
| standard.mode_shift | yes | test:mode_shift_is_a_budget_drained_by_the_health_actually_lost | spec:INV_STATUSES | — | §195.1/INV_STATUSES/mode_shift_is_a_budget_drained_by_the_health_actually_lost |
| standard.phantom_veil | yes | — | spec:INV_STATUSES | — | §175/§181/INV_STATUSES |
| standard.phase_split | yes | test:the_boss_phase_splits_once_at_low_health, a_phase_split_happens_once_even_under_three_hits | spec:INV_STATUSES | — | §121/§122/INV_STATUSES/the_boss_phase_splits_once_at_low_health |
| standard.plated_armor | yes | test:a_long_fight_never_reports_a_step_problem, plated_armor_wears_down_to_nothing_without_an_error …(+4) | spec:INV_STATUSES | — | §209/§210/INV_STATUSES/a_long_fight_never_reports_a_step_problem |
| standard.rage | yes (test-only) | test:rage_gives_block_only_for_an_attack, standard_status_ids_are_byte_ordered_not_registration_ordered …(+2) | spec:INV_STATUSES | — | §119/INV_STATUSES/rage_gives_block_only_for_an_attack |
| standard.regen | yes | test:the_awakened_one_survives_its_first_death_and_then_really_dies, regen_heals_at_the_end_of_the_turn …(+1) | spec:INV_STATUSES | — | §119/INV_STATUSES/the_awakened_one_survives_its_first_death_and_then_really_dies |
| standard.sharp_hide | yes | test:sharp_hide_hurts_the_player_for_attacks_and_only_attacks, mode_shift_is_a_budget_drained_by_the_health_actually_lost | spec:INV_STATUSES | — | §194/§195.1/INV_STATUSES/sharp_hide_hurts_the_player_for_attacks_and_only_attacks |
| standard.slow | yes | test:a_card_play_leaves_no_chain_referenced, a_slow_spec_on_a_pipeline_without_a_card_count_is_refused …(+1) | spec:INV_STATUSES | — | §216/INV_STATUSES/a_card_play_leaves_no_chain_referenced |
| standard.split | yes | test:a_spawned_enemy_joins_the_turn_order_after_the_current_actor, a_phase_split_happens_once_even_under_three_hits …(+1) | spec:INV_STATUSES | — | §121/INV_STATUSES/a_spawned_enemy_joins_the_turn_order_after_the_current_actor |
| standard.spore_cloud | yes | test:spore_cloud_weakens_the_killer_on_death | spec:INV_STATUSES | — | §116/§117/INV_STATUSES/spore_cloud_weakens_the_killer_on_death |
| standard.stasis | yes | test:stasis_steals_the_best_card_and_returns_it_when_the_orb_dies, a_96_card_pile_still_reaches_the_best_card_at_the_end …(+2) | spec:INV_STATUSES | — | §195.1/§195.4/INV_STATUSES/stasis_steals_the_best_card_and_returns_it_when_the_orb_dies |
| standard.stasis_ready | yes | test:stasis_steals_the_best_card_and_returns_it_when_the_orb_dies, a_96_card_pile_still_reaches_the_best_card_at_the_end …(+2) | spec:INV_STATUSES | — | §195.4/INV_STATUSES/stasis_steals_the_best_card_and_returns_it_when_the_orb_dies |
| standard.strength | yes | test:dot_slips_past_the_standard_pack_rows_that_direct_hits_do_not, modifier_rows_match_exactly_and_through_the_documented_namespace_bridge …(+47) | spec:INV_STATUSES | — | §208/§212/INV_STATUSES/dot_slips_past_the_standard_pack_rows_that_direct_hits_do_not |
| standard.thorns | yes | test:thorns_hurts_whoever_hits_its_owner, standard_status_ids_are_byte_ordered_not_registration_ordered …(+4) | spec:INV_STATUSES | — | §207/§214/INV_STATUSES/thorns_hurts_whoever_hits_its_owner |
| standard.time_warp | yes | test:the_twelfth_card_asks_for_the_turn_to_end | spec:INV_STATUSES | — | §122/§125/INV_STATUSES/the_twelfth_card_asks_for_the_turn_to_end |
| standard.unawakened | yes | test:the_awakened_one_survives_its_first_death_and_then_really_dies, the_awakened_one_draws_phase_one_by_weight_and_flips_on_the_guard | spec:INV_STATUSES | — | §180/§195.2/INV_STATUSES/the_awakened_one_survives_its_first_death_and_then_really_dies |
| standard.vulnerable | yes | test:the_def_table_is_a_side_table_not_a_copy_per_beat, clear_wipes_the_names_too …(+17) | spec:INV_STATUSES | — | §204/§213/INV_STATUSES/the_def_table_is_a_side_table_not_a_copy_per_beat |
| standard.weak | yes | test:the_def_table_is_a_side_table_not_a_copy_per_beat, clear_wipes_the_names_too …(+26) | spec:INV_STATUSES | — | §212/§213/INV_STATUSES/the_def_table_is_a_side_table_not_a_copy_per_beat |

## 遭遇（34）

| Entity | Implemented | RuntimeTested | WikiVerified | Deviation | Evidence |
|---|---|---|---|---|---|
| enc_awakened_one | yes | test:every_act_has_three_bosses_and_each_one_is_a_buildable_encounter, the_awakened_one_draws_phase_one_by_weight_and_flips_on_the_guard …(+3) | — | — | §194/§195.8/every_act_has_three_bosses_and_each_one_is_a_buildable_encounter |
| enc_book_of_stabbing | yes | harness:entity_tables_decode_row_by_row …(+11) | — | — | §173 |
| enc_bronze_automaton | yes | test:every_act_has_three_bosses_and_each_one_is_a_buildable_encounter, the_automaton_swaps_stunned_for_boost_only_at_a19 …(+3) | — | — | §138/§194/every_act_has_three_bosses_and_each_one_is_a_buildable_encounter |
| enc_byrds | yes | test:flying_halves_attack_damage_and_loses_a_stack_per_hit | — | — | §138/§201/flying_halves_attack_damage_and_loses_a_stack_per_hit |
| enc_chosen | yes | test:hex_shuffles_a_dazed_only_for_non_attack_cards, chosen_swaps_its_opener_at_a17 | — | — | §153/§201/hex_shuffles_a_dazed_only_for_non_attack_cards |
| enc_cultist | yes | test:an_encounter_without_rolls_draws_nothing, building_a_louse_fight_draws_its_bite_and_a_cultist_fight_does_not | — | — | §5.2/§130/an_encounter_without_rolls_draws_nothing |
| enc_darklings | yes | test:an_encounter_with_two_records_of_the_same_id_builds | — | — | §201/an_encounter_with_two_records_of_the_same_id_builds |
| enc_donu_and_deca | yes | test:every_act_has_three_bosses_and_each_one_is_a_buildable_encounter | — | — | §194/§195.8/every_act_has_three_bosses_and_each_one_is_a_buildable_encounter |
| enc_fungi_beast | yes | harness:entity_tables_decode_row_by_row …(+11) | — | — | §130/§152 |
| enc_giant_head | yes | test:a_summoned_minion_resolves_through_the_image_not_the_encounter, giant_head_counts_down_then_only_its_time …(+1) | — | — | §134/a_summoned_minion_resolves_through_the_image_not_the_encounter |
| enc_gremlin_gang | yes | harness:entity_tables_decode_row_by_row …(+11) | — | — | §138/§153 |
| enc_gremlin_leader | yes | harness:entity_tables_decode_row_by_row …(+11) | — | — | §5.3/§134 |
| enc_gremlin_nob | yes | test:an_ascension_health_row_applies_at_its_own_level_and_not_below | — | — | §152/an_ascension_health_row_applies_at_its_own_level_and_not_below |
| enc_hexaghost | yes | test:every_act_has_three_bosses_and_each_one_is_a_buildable_encounter, hexaghost_plays_the_wikis_seven_move_pattern_after_its_two_openers | — | — | §194/every_act_has_three_bosses_and_each_one_is_a_buildable_encounter |
| enc_jaw_worm | yes | test:uppercut_hurts_the_enemy_and_not_the_hero, a_jaw_worm_starts_with_block_and_a17_makes_it_bigger | — | — | §5.2/§130/uppercut_hurts_the_enemy_and_not_the_hero |
| enc_lagavulin | yes | test:lagavulin_can_be_fought_for_eight_rounds_including_siphon_soul | — | — | §173/lagavulin_can_be_fought_for_eight_rounds_including_siphon_soul |
| enc_looter | yes | test:an_ascension_health_row_applies_at_its_own_level_and_not_below, the_looter_mugs_twice_then_bombs_then_escapes | — | — | §175/§201/an_ascension_health_row_applies_at_its_own_level_and_not_below |
| enc_louse | yes | test:a_spawn_roll_is_drawn_once_per_fight_and_read_by_the_action, an_encounter_without_rolls_draws_nothing …(+2) | — | — | §130/§152/a_spawn_roll_is_drawn_once_per_fight_and_read_by_the_action |
| enc_maw | yes | test:nom_nom_hits_five_damage_ceil_round_over_two_times, the_maw_follows_the_wikis_transition_table | — | — | §147/§201/nom_nom_hits_five_damage_ceil_round_over_two_times |
| enc_nemesis | yes | harness:entity_tables_decode_row_by_row …(+11) | — | — | §175 |
| enc_orb_walker | yes | harness:entity_tables_decode_row_by_row …(+11) | — | — | §138/§201 |
| enc_reptomancer | yes | test:act_three_reptomancer_daggers_arrive_and_then_take_themselves_out | — | — | §175/act_three_reptomancer_daggers_arrive_and_then_take_themselves_out |
| enc_shelled_parasite | yes | harness:entity_tables_decode_row_by_row …(+11) | — | — | §153/§201 |
| enc_slaver_red | yes | harness:entity_tables_decode_row_by_row …(+11) | — | — | §130/§152 |
| enc_slavers | yes | test:a_round_one_rule_beats_the_cycle_and_the_cycle_takes_over_after_it | — | — | a_round_one_rule_beats_the_cycle_and_the_cycle_takes_over_after_it |
| enc_slime_boss | yes | test:every_act_has_three_bosses_and_each_one_is_a_buildable_encounter, a_combinator_rule_switches_the_boss_move …(+1) | — | — | §194/every_act_has_three_bosses_and_each_one_is_a_buildable_encounter |
| enc_small_slimes | yes | test:a_spawned_combatant_still_resolves_to_its_enemy_record | — | — | §130/a_spawned_combatant_still_resolves_to_its_enemy_record |
| enc_spiker | yes | test:spiker_never_repeats_its_attack_and_buffs_thorns_at_most_six_times, starting_statuses_follow_their_ascension_rows | — | — | §138/§201/spiker_never_repeats_its_attack_and_buffs_thorns_at_most_six_times |
| enc_spire_growth | yes | test:spire_growth_smashes_instead_of_choosing | — | — | §147/§201/spire_growth_smashes_instead_of_choosing |
| enc_the_champ | yes | test:an_ascension_health_row_applies_at_its_own_level_and_not_below, every_act_has_three_bosses_and_each_one_is_a_buildable_encounter …(+4) | — | — | §194/an_ascension_health_row_applies_at_its_own_level_and_not_below |
| enc_the_collector | yes | test:the_collector_draws_by_weight_and_never_buffs_twice_in_a_row, every_act_has_three_bosses_and_each_one_is_a_buildable_encounter …(+1) | — | — | §138/§194/the_collector_draws_by_weight_and_never_buffs_twice_in_a_row |
| enc_the_guardian | yes | test:mode_shift_is_a_budget_drained_by_the_health_actually_lost, every_act_has_three_bosses_and_each_one_is_a_buildable_encounter …(+1) | — | — | §194/mode_shift_is_a_budget_drained_by_the_health_actually_lost |
| enc_three_sentries | yes | harness:entity_tables_decode_row_by_row …(+11) | — | — | §134 |
| enc_time_eater | yes | test:every_act_has_three_bosses_and_each_one_is_a_buildable_encounter, a_weighted_boss_never_repeats_the_move_the_wiki_forbids …(+1) | — | — | §138/§194/every_act_has_three_bosses_and_each_one_is_a_buildable_encounter |

## 事件（9）

| Entity | Implemented | RuntimeTested | WikiVerified | Deviation | Evidence |
|---|---|---|---|---|---|
| ancient_forge | yes | test:the_unknown_room_events_are_readable, an_event_that_edits_the_deck_owes_a_pick_first …(+3) | — | — | the_unknown_room_events_are_readable |
| ancient_writing | yes | test:the_unknown_room_events_are_readable, an_event_choice_that_edits_the_deck_owes_a_pick | — | — | the_unknown_room_events_are_readable |
| forgotten_altar | yes | test:the_unknown_room_events_are_readable, an_event_choice_that_edits_the_deck_owes_a_pick | — | — | the_unknown_room_events_are_readable |
| golden_idol | yes | test:the_unknown_room_events_are_readable, an_event_relic_is_never_drawn …(+5) | — | — | §156/§157/the_unknown_room_events_are_readable |
| old_shrine | yes | test:the_unknown_room_events_are_readable, an_event_can_give_a_relic_only_if_the_kernel_can_run_it | — | — | the_unknown_room_events_are_readable |
| purification_shrine | yes | test:the_unknown_room_events_are_readable | — | — | the_unknown_room_events_are_readable |
| scrap_pile | yes | test:the_unknown_room_events_are_readable | — | — | the_unknown_room_events_are_readable |
| shining_light | yes | test:the_unknown_room_events_are_readable | — | — | the_unknown_room_events_are_readable |
| wandering_merchant | yes | test:the_unknown_room_events_are_readable | — | — | the_unknown_room_events_are_readable |

## 遗物（13）

| Entity | Implemented | RuntimeTested | WikiVerified | Deviation | Evidence |
|---|---|---|---|---|---|
| anchor | yes | test:the_same_state_hashes_the_same_and_a_change_moves_it, every_invariant_names_itself_when_violated …(+6) | — | — | the_same_state_hashes_the_same_and_a_change_moves_it |
| blood_vial | yes | test:the_relic_pool_fires_at_the_three_hooks_it_has | — | — | the_relic_pool_fires_at_the_three_hooks_it_has |
| bronze_scales | yes | harness:an_id_that_is_a_card_and_a_relic_is_not_an_encounter …(+5) | — | — | §156 |
| burning_blood | yes | test:capacity_is_an_error_not_a_truncation, burning_blood_heals_six_at_the_end_of_a_fight …(+7) | — | — | capacity_is_an_error_not_a_truncation |
| eternal_feather | yes | test:the_eternal_feather_pays_per_whole_group_of_five_on_entering, the_new_relics_pay_out | — | — | §156/§157/the_eternal_feather_pays_per_whole_group_of_five_on_entering |
| golden_idol | yes | test:the_unknown_room_events_are_readable, an_event_relic_is_never_drawn …(+5) | — | — | §156/§157/the_unknown_room_events_are_readable |
| meat_on_the_bone | yes | harness:an_id_that_is_a_card_and_a_relic_is_not_an_encounter …(+5) | — | — | §156 |
| pear | yes | test:the_relic_pool_fires_at_the_three_hooks_it_has | — | — | the_relic_pool_fires_at_the_three_hooks_it_has |
| potion_belt | yes | test:capacity_is_an_error_not_a_truncation, the_ascension_rules_are_each_their_own_level …(+1) | — | — | §156/§157/capacity_is_an_error_not_a_truncation |
| regal_pillow | yes | harness:an_id_that_is_a_card_and_a_relic_is_not_an_encounter …(+5) | — | — | §156 |
| strawberry | yes | harness:an_id_that_is_a_card_and_a_relic_is_not_an_encounter …(+5) | — | — | §156 |
| thread_and_needle | yes | test:the_relic_pool_fires_at_the_three_hooks_it_has, an_elite_pays_a_relic_and_a_normal_fight_does_not | — | — | the_relic_pool_fires_at_the_three_hooks_it_has |
| vajra | yes | test:every_invariant_names_itself_when_violated, a_relic_you_already_hold_is_not_offered_again …(+3) | — | — | every_invariant_names_itself_when_violated |

## 药水（33）

| Entity | Implemented | RuntimeTested | WikiVerified | Deviation | Evidence |
|---|---|---|---|---|---|
| ancient_potion | yes | test:the_potions_are_readable | — | — | the_potions_are_readable |
| attack_potion | yes | test:the_potions_are_readable, an_attack_potion_offers_three_definitions_and_creates_only_the_chosen_card …(+1) | — | — | the_potions_are_readable |
| blessing_of_the_forge | yes | test:the_potions_are_readable, blessing_of_the_forge_upgrades_every_strike_in_hand | — | — | the_potions_are_readable |
| block_potion | yes | test:the_potions_are_readable, dropping_a_potion_keeps_the_order_of_the_survivors …(+2) | — | — | the_potions_are_readable |
| blood_potion | yes | test:the_potions_are_readable, the_new_potion_shapes_all_do_something | — | — | the_potions_are_readable |
| colorless_potion | yes | test:the_potions_are_readable, colorless_potion_offers_three_colorless_cards_and_the_pick_lands_in_hand | — | — | the_potions_are_readable |
| cultist_potion | yes | test:the_potions_are_readable | — | — | the_potions_are_readable |
| dexterity_potion | yes | test:the_potions_are_readable | — | — | the_potions_are_readable |
| distilled_chaos | yes | test:the_potions_are_readable, distilled_chaos_plays_the_top_three_for_free | — | — | the_potions_are_readable |
| duplication_potion | yes | test:the_potions_are_readable | — | — | the_potions_are_readable |
| elixir | yes | test:the_potions_are_readable, every_potion_in_the_table_classifies_as_known …(+1) | — | — | the_potions_are_readable |
| energy_potion | yes | test:the_potions_are_readable, potions_are_drawn_by_rarity_weight …(+2) | — | — | the_potions_are_readable |
| entropic_brew | yes | test:the_potions_are_readable, entropic_brew_fills_the_belt_after_freeing_its_own_slot | — | — | the_potions_are_readable |
| essence_of_steel | yes | test:the_potions_are_readable | — | — | the_potions_are_readable |
| explosive_potion | yes | test:the_potions_are_readable, the_new_potion_shapes_all_do_something | — | — | the_potions_are_readable |
| fairy_in_a_bottle | yes | test:the_potions_are_readable | — | — | the_potions_are_readable |
| fear_potion | yes | test:the_potions_are_readable | — | — | the_potions_are_readable |
| fire_potion | yes | test:the_potions_are_readable, the_same_state_hashes_the_same_and_a_change_moves_it …(+9) | — | — | the_potions_are_readable |
| flex_potion | yes | test:the_potions_are_readable, flex_potion_gives_strength_and_takes_it_back | — | — | the_potions_are_readable |
| fruit_juice | yes | test:the_potions_are_readable, fruit_juice_works_outside_a_fight | — | — | the_potions_are_readable |
| gamblers_brew | yes | test:the_potions_are_readable, every_potion_in_the_table_classifies_as_known …(+1) | — | — | the_potions_are_readable |
| heart_of_iron | yes | test:the_potions_are_readable | — | — | the_potions_are_readable |
| liquid_bronze | yes | test:the_potions_are_readable | — | — | the_potions_are_readable |
| liquid_memories | yes | test:the_potions_are_readable, liquid_memories_returns_a_card_and_makes_that_copy_free_once …(+1) | — | — | the_potions_are_readable |
| power_potion | yes | test:the_potions_are_readable, a_power_potion_offers_the_three_power_cards_and_they_are_real_powers …(+1) | — | — | the_potions_are_readable |
| regen_potion | yes | test:the_potions_are_readable, potions_are_drawn_by_rarity_weight | — | — | the_potions_are_readable |
| skill_potion | yes | test:the_potions_are_readable, every_potion_in_the_table_classifies_as_known | — | — | the_potions_are_readable |
| smoke_bomb | yes | test:the_potions_are_readable, smoke_bomb_ends_a_normal_fight_and_refuses_a_boss | — | — | the_potions_are_readable |
| snecko_oil | yes | test:the_potions_are_readable, snecko_oil_draws_five_and_randomizes_every_price_in_hand | — | — | the_potions_are_readable |
| speed_potion | yes | test:the_potions_are_readable | — | — | the_potions_are_readable |
| strength_potion | yes | test:the_potions_are_readable, the_new_potion_shapes_all_do_something | — | — | the_potions_are_readable |
| swift_potion | yes | test:the_potions_are_readable, the_new_potion_shapes_all_do_something | — | — | the_potions_are_readable |
| weak_potion | yes | test:the_potions_are_readable, the_new_potion_shapes_all_do_something | — | — | the_potions_are_readable |
