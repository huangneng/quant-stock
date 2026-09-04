# 跑批可靠性四修：推送日期、耗时护栏、停牌零值、成交额精度不被覆盖

- [x] Task 1: 修 `run_daily.sh` 的推送日期
    - 1.1: 在加载环境变量之后、调用推送之前 `export PUSH_DATE="$today"`
    - 1.2: 注释写清为何不能让推送脚本自己取 `date.today()`（跨午夜必扑空）
    - 1.3: 确认 `$today` 与传给 `daily_select --date` 的是同一个值

- [x] Task 2: 为推送日期补验证
    - 2.1: 模拟「当天跑完」——`PUSH_DATE` 等于当日，断言脚本定位到正确 CSV
    - 2.2: 模拟「跨午夜跑完」——系统日期已是次日，断言仍定位到跑批当日 CSV
    - 2.3: 确认未配置 SMTP/SERVERCHAN 时仍静默退出（不因本改动变成失败）

- [x] Task 3: 零成交额判据改为「目标日当日是否真有成交」
    - 3.1: 把 `_prefilter_cache_has_bad_zero_amount` 的近 5 日最高成交额判据，改为查目标日当日成交额
    - 3.2: 目标日无行或当日成交额为 0 时判定真停牌，放过不删缓存
    - 3.3: 目标日当日确有成交额却在缓存里为 0 时，仍判定缓存有问题并删除
    - 3.4: 保留零值比例 > 1% 的整体性判据不变

- [x] Task 4: 为零值判据补测试
    - 4.1: 构造真停牌（目标日无行）——断言返回 False，缓存保留
    - 4.2: 构造真停牌（目标日成交额为 0）——断言返回 False
    - 4.3: 构造坏缓存（目标日有成交额却记为 0）——断言返回 True
    - 4.4: 用 09-03 的真实 6 只停牌股跑一遍，断言缓存不再被误删

- [x] Task 5: 同步加耗时护栏
    - 5.1: `sync_kline_db` 新增 `max_round_seconds` / `slow_avg_seconds` / `slow_min_samples` 参数
    - 5.2: 整轮墙钟超预算即中止，复用既有 `aborted` 路径
    - 5.3: 样本达下限后按单票均耗时判定劣化并中止
    - 5.4: `api.py` 透传新参数，默认 7200 / 3.0 / 200
    - 5.5: `__main__.py` 打印中止原因，与早停措辞保持一致

- [x] Task 6: 为耗时护栏补测试
    - 6.1: 构造慢但成功的取数，断言按单票均耗时中止而非跑满
    - 6.2: 构造整轮超预算，断言按墙钟预算中止
    - 6.3: 断言两种中止都不推进 `last_sync_date`
    - 6.4: 回归正常速度轮次不被误杀，且失败率早停仍生效

- [x] Task 7: 备份库并为 `kline` 表加 `amt_src` 列
    - 7.1: 备份 `kline.db` 到带时间戳的文件，记录行数与校验口径
    - 7.2: 用 `PRAGMA table_info` 判断后再 `ALTER TABLE`，保证迁移幂等
    - 7.3: 历史行 `amt_src` 保持 NULL，语义为「未知、可被覆盖」
    - 7.4: 确认迁移后既有读路径（`query_kline` 等）不受影响

- [x] Task 8: `upsert_kline` 按成交额精度决定覆盖
    - 8.1: 改为 `ON CONFLICT(code,date) DO UPDATE`，OHLC/volume/turn/pctChg 照常覆盖
    - 8.2: `amount` 与 `amt_src` 按优先级取值：exact 可覆盖任何值，approx 不得覆盖 exact
    - 8.3: 各源标注精度——sina/baostock/akshare 为 exact，tencent/mootdx 为 approx
    - 8.4: `router.py` 在所有 upsert 调用点带上 `amt_src`
    - 8.5: 补数脚本 `fill_kline_from_snapshot.py` 写入时标注 exact

- [x] Task 9: 为精度优先级补测试
    - 9.1: exact 写入后再用 approx 写同一行，断言 amount 与 amt_src 不变
    - 9.2: approx 写入后再用 exact 写，断言 amount 被更新且 amt_src 变 exact
    - 9.3: 断言 OHLC/volume 在两种方向上都被正常覆盖
    - 9.4: 历史 NULL 行可被 approx 覆盖（不能当 exact 保护）
    - 9.5: 回归 `upsert_kline` 的返回值语义与缺列补 None 的既有行为

- [x] Task 10: 标注近期已知精确的成交额
    - 10.1: 把 09-01 / 09-02 / 09-03 已修正为精确值的行标为 exact
    - 10.2: 校验标注行数与各日的预筛缓存条数一致
    - 10.3: 跑一次 `daily_select` 与报告生成，断言这三天的 amount 不再被改写

- [x] Task 11: 端到端验证与提交
    - 11.1: 全部测试脚本重跑，确认无回归
    - 11.2: 刷新总览页，检查 `git status` 后提交并推送
    - 11.3: 生成 summary.md，记录四项改动的实测依据与遗留项
