# Settings 字段（对齐原 `GameScript.Models.Settings`）

| JSON 键 | 原属性 | 说明 |
|---------|--------|------|
| stage1 / stage2 | Stage1 / Stage2 | 关卡选择 |
| room_name / room_password | RoomName / RoomPassword | 带队建房 |
| new_room_every_times | NewRoomEveryTimes | 每局新房间 |
| query_timeout | QueryTimeOut | 等待/查询超时（秒级语义，实机标定） |
| game_timeout | GameTimeOut | 单局超时（分钟级；MAIN_LINE idle watchdog：`idle_minutes >= max(game_timeout,5)` 触发 ERROR，可被受确认的正常进展刷新） |
| round_timeout_s | （S0 新增） | 单局 hard deadline（秒，默认 900 = game_timeout×60）。进入 MAIN_LINE 时固定、不可续期；技能/面板/神器/挑战/进化动作不得延期；到期先 QUIT 再 ERROR。迁移决定：旧 game_timeout=15 官方语义是分钟（不接成秒级 hard deadline），round_timeout_s 独立承担硬期限。 |
| game_mode | GameMode | 0 独狼 …（枚举待实机确认） |
| dragon_ball_count | DragonBallCount | 6 或 7 |
| find_longzhu_where_multi_game | FindLongzhuWhereMultiGame | 组队找龙珠 |
| auto_secret_realm | AutoSecretRealm | 自动秘境 |
| auto_close_main_line | AutoCloseMainLine | 自动关主线 |
| close_main_line_time | CloseMainLineTime | 关主线时机 |
| auto_clean_interval | AutoCleanInterval | 每 N 局清理 |
| auto_card / auto_weapon | AutoCard / AutoWeapon | 卡/武器 |
| damage_increase_card | DamageIncreaseCard | 奥数增伤优先 |
| develop_time / develop_priority | DevelopTime / DevelopPriority | 发育 |
| auto_reputation 等 | AutoReputation… | 声望线 |
| cjb_boss / sgzx_boss | CJBBoss / SGZXBoss | Boss 名/图键 |
| skills | Skills | 技能短码，对应 `Images/skills/{code}.png` |
| cards | Cards | 卡组 |
| archive_boss_time | ArchiveBossTime | 存档挑战计时 |
| auto_gambling_time | AutoGamblingTime | 赌木 |
| match_threshold | （重建新增） | 找图阈值 |
| window_title_contains | （重建新增） | 窗口标题过滤 |
| dry_run | （重建新增） | true=只匹配不点击 |

原 `LicenseTxt` / `CertEnable` / `BatFile` 不纳入本地自用默认配置。
