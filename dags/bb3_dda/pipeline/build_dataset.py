# Dựng dữ liệu train hằng ngày: cohort Android first_open, chia N_CHUNKS phần theo hash user -> parquet
# Bản chuyển từ ~/dda_demo/run_full.py sang clickhouse_connect (HTTP) + cửa sổ trượt theo ngày chạy.
import os, gc, time, logging
from datetime import date, datetime, timedelta, timezone
import numpy as np, pandas as pd

from configs import settings as S
from core.fe_lib import level_tables, build, add_tier_code, F_DEVICE

log = logging.getLogger(__name__)
T = S.SOURCE_TABLE


def client():
    import clickhouse_connect
    return clickhouse_connect.get_client(**S.CH, send_receive_timeout=3600,
                                         settings={'max_threads': 8, 'max_execution_time': 3600})


def us(d):
    """00:00 UTC của ngày d -> microseconds (đơn vị event_timestamp)."""
    return int(datetime(d.year, d.month, d.day, tzinfo=timezone.utc).timestamp() * 1_000_000)


def windows(data_end):
    """data_end: ngày cuối cùng có dữ liệu đầy đủ."""
    label_end = data_end - timedelta(days=S.LABEL_DAYS)     # lượt chơi phải trước mốc này để đủ 7 ngày quan sát
    return dict(data_end=data_end, label_end=label_end,
                coh_start=label_end - timedelta(days=S.COHORT_DAYS - 1),
                valid_start=label_end - timedelta(days=S.VALID_DAYS - 1),
                data_end_us=us(data_end + timedelta(days=1)),
                cut_us=us(label_end + timedelta(days=1)))


def check_source(run_date):
    """Tìm ngày gần nhất (<= run_date - 1) có đủ level_up. Bảng staging thường trễ 1-2 ngày."""
    rows = client().query(
        f"SELECT event_date, count() FROM {T} WHERE event_name = 'level_up' "
        f"AND event_date BETWEEN toDate('{run_date - timedelta(days=10)}') AND toDate('{run_date - timedelta(days=1)}') "
        f"GROUP BY event_date ORDER BY event_date").result_rows
    full = [d for d, n in rows if n >= S.MIN_ROWS_D1]
    log.info('level_up 10 ngay gan nhat: %s', ', '.join(f'{d}: {n:,}' for d, n in rows))
    if not full:
        raise RuntimeError('Khong co ngay nao du du lieu trong 10 ngay gan nhat')
    data_end = full[-1]
    lag = (run_date - data_end).days
    if lag > S.MAX_LAG_DAYS:
        raise RuntimeError(f'Du lieu moi nhat la {data_end} (tre {lag} ngay > {S.MAX_LAG_DAYS}) - cho lan chay lai')
    log.info('dung du lieu den het %s (tre %d ngay)', data_end, lag)
    return str(data_end)


COH = """cohort AS (SELECT user_pseudo_id AS uid, min(event_date) AS inst FROM {T}
  WHERE event_name = 'first_open' AND platform = 'ANDROID' GROUP BY uid
  HAVING inst BETWEEN toDate('{a}') AND toDate('{b}') {ch})"""

STATS = """WITH {coh}
SELECT src, avgIf(remain, win = 1) AS mu, stddevSampIf(remain, win = 1) AS sd, 1 - avg(win) AS lr, count() AS n FROM (
  SELECT toInt64OrNull(ep_level_up_level) AS l, if(l <= 1000, l, 100 + ((l - 100) % 900)) AS src,
         toInt64OrNull(ep_level_up_value) AS win, ep_level_up_numball_remain AS remain
  FROM {T} WHERE event_name = 'level_up' AND event_timestamp <= {tsmax} AND event_timestamp < {cut}
    AND days_since_install BETWEEN 0 AND {dsi}
    AND user_pseudo_id IN (SELECT uid FROM cohort) AND l BETWEEN 1 AND 100000 AND win IS NOT NULL)
GROUP BY src ORDER BY src"""

ATT = """WITH {coh},
seq AS (SELECT user_pseudo_id AS uid, event_timestamp AS ts, days_since_install AS dsi, ga_session_number AS sess,
  toInt64OrNull(ep_level_up_level) AS lvl, toInt64OrNull(ep_level_up_value) AS win, ep_level_up_stars AS stars,
  ep_level_up_numball_remain AS remain, ep_level_up_numballspec_used AS spec_used, ep_level_up_user_do AS user_do,
  leadInFrame(event_timestamp) OVER (PARTITION BY user_pseudo_id ORDER BY event_timestamp
      ROWS BETWEEN UNBOUNDED PRECEDING AND UNBOUNDED FOLLOWING) AS next_ts
  FROM {T} WHERE event_name = 'level_up' AND event_timestamp <= {tsmax} AND event_timestamp < {dend}
    AND user_pseudo_id IN (SELECT uid FROM cohort))
SELECT s.uid AS uid, c.inst AS install_date, s.ts AS ts, s.dsi AS dsi, s.sess AS sess, s.lvl AS lvl, s.win AS win,
       s.stars AS stars, s.remain AS remain, s.spec_used AS spec_used, s.user_do AS user_do, s.next_ts AS next_ts
FROM seq AS s INNER JOIN cohort AS c ON s.uid = c.uid
WHERE s.dsi BETWEEN 0 AND {dsi} AND s.lvl BETWEEN 1 AND 100000"""

EX = """WITH {coh},
ev AS (SELECT user_pseudo_id AS uid, event_timestamp AS ts, event_name AS en, country, app_version,
  hours_since_install AS hsi,
  if(event_name = 'paid_ad_impression', ep_paid_ad_impression_valuemicros / 1e6, 0) AS usd,
  if(event_name = 'user_engagement', engagement_time, 0) AS eng_ms,
  toInt64(sum(if(event_name = 'level_up', 1, 0)) OVER (PARTITION BY user_pseudo_id ORDER BY event_timestamp,
      event_name = 'level_up' ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW)) AS seg
  FROM {T} WHERE event_timestamp <= {tsmax} AND event_timestamp < {dend} AND days_since_install BETWEEN 0 AND {dsi}
    AND user_pseudo_id IN (SELECT uid FROM cohort)
    AND event_name IN ('level_up', 'paid_ad_impression', 'ad_reward', 'show_ad_inter_fail_ev', 'show_ad_fail_ev',
                       'rate_dialog_ev', 'screen_view', 'user_engagement', 'session_start')),
seg_agg AS (SELECT uid, seg, countIf(en = 'paid_ad_impression') AS s_ad_imps, sum(usd) AS s_ad_usd,
  countIf(en = 'ad_reward') AS s_rewarded, countIf(en IN ('show_ad_inter_fail_ev', 'show_ad_fail_ev')) AS s_ad_fail,
  countIf(en = 'rate_dialog_ev') AS s_rate_dialog, countIf(en = 'screen_view') AS s_screen_views,
  sum(eng_ms) / 1000 AS s_engage_sec, countIf(en = 'session_start') AS s_new_session
  FROM ev WHERE en != 'level_up' GROUP BY uid, seg),
lu AS (SELECT uid, ts, seg, country, app_version, hsi FROM ev WHERE en = 'level_up')
SELECT lu.uid AS uid, lu.ts AS ts, lu.country AS country, lu.app_version AS app_version, lu.hsi AS hsi,
  s.s_ad_imps AS s_ad_imps, s.s_ad_usd AS s_ad_usd, s.s_rewarded AS s_rewarded, s.s_ad_fail AS s_ad_fail,
  s.s_rate_dialog AS s_rate_dialog, s.s_screen_views AS s_screen_views, s.s_engage_sec AS s_engage_sec,
  s.s_new_session AS s_new_session
FROM lu LEFT JOIN seg_agg AS s ON lu.uid = s.uid AND s.seg = lu.seg - 1"""


def build_dataset(data_end, work_dir):
    os.makedirs(work_dir, exist_ok=True)
    W = windows(data_end)
    cl = client()
    t0 = time.time()
    # lọc timestamp tương lai bằng mốc động (hết ngày data_end), KHÔNG dùng hằng số cố định
    fmt = dict(T=T, tsmax=W['data_end_us'] - 1, cut=W['cut_us'], dend=W['data_end_us'], dsi=S.MAX_DSI)

    # bảng thống kê từng màn: CHỈ từ user train
    coh_tr = COH.format(T=T, a=W['coh_start'], b=W['valid_start'] - timedelta(days=1), ch='')
    st = cl.query_df(STATS.format(coh=coh_tr, **fmt))
    st.to_csv(os.path.join(work_dir, 'level_stats.csv'), index=False)
    ST = level_tables(st)
    cfg = pd.read_csv(os.path.join(S.DATA_DIR, 'level_config.csv')).set_index('level').total_balls
    tier = pd.read_csv(os.path.join(S.DATA_DIR, 'country_tier.csv')).set_index('country').tier
    log.info('level stats: %d man (%.0fs)', len(st), time.time() - t0)

    keep_cols = F_DEVICE + ['lost_7d', 'w', 'split', 'uid', 'lvl', 'install_date', 'ts', 'win']
    tot = dict(rows_new=0, kept=0)
    for c in range(S.N_CHUNKS):
        out = os.path.join(work_dir, f'chunk_{c:02d}.parquet')
        if os.path.exists(out):
            continue
        t1 = time.time()
        coh = COH.format(T=T, a=W['coh_start'], b=W['label_end'], ch=f'AND cityHash64(uid) % {S.N_CHUNKS} = {c}')
        att = cl.query_df(ATT.format(coh=coh, **fmt))
        ex = cl.query_df(EX.format(coh=coh, **fmt))
        t2 = time.time()
        att['install_date'] = pd.to_datetime(att.install_date)
        df = build(att, ex, ST, cfg, tier)
        del att, ex; gc.collect()
        df = df[df.ts < W['cut_us']]                         # chỉ giữ lượt đủ 7 ngày quan sát
        df = add_tier_code(df)
        df['split'] = np.where(df.install_date < pd.Timestamp(W['valid_start']), 'train', 'valid')
        rng = np.random.default_rng(1000 + c)
        n_all = len(df)
        keep = (df.split != 'train') | (df.lost_7d == 1) | (rng.random(n_all) < S.NEG_SAMPLE)
        df = df[keep]
        df['w'] = np.where((df.split == 'train') & (df.lost_7d == 0), 1 / S.NEG_SAMPLE, 1.0)
        o = df[keep_cols].copy()
        o = o.loc[:, ~o.columns.duplicated()]
        for col in F_DEVICE:                                 # kiểu nullable (Int64/Float64 từ clickhouse_connect) -> float32, NA -> NaN
            o[col] = o[col].astype('Float64').to_numpy(dtype='float32', na_value=np.nan)
        for col in o.columns:
            if o[col].dtype == 'float64':
                o[col] = o[col].astype('float32')
        o.to_parquet(out, index=False)
        tot['rows_new'] += n_all
        log.info('chunk %02d: %s luot -> %s | query %.0fs, FE %.0fs', c, f'{n_all:,}', f'{len(o):,}', t2 - t1, time.time() - t2)
        del df, o; gc.collect()
    import pyarrow.parquet as pq
    files = sorted(f for f in os.listdir(work_dir) if f.startswith('chunk_'))
    tot['kept'] = sum(pq.ParquetFile(os.path.join(work_dir, f)).metadata.num_rows for f in files)   # tính cả phần dùng lại
    tot['chunks'] = len(files)
    log.info('dung du lieu xong: %d phan, %s luot (%.1f phut)', len(files), f"{tot['kept']:,}", (time.time() - t0) / 60)
    return {**{k: str(v) for k, v in W.items()}, **tot}
