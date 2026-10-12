# Feature engineering cho model DDA - GIỐNG HỆT ~/dda_demo/fe_lib.py (model v5/v6, đã kiểm tra parity: 0 cột lệch)
# Bổ sung cho bản đóng gói lên thiết bị: tier_code (số) thay cho tier_c (categorical) để client không phải xử lý split categorical.
import pandas as pd, numpy as np

DAY = 86400 * 1_000_000
src = lambda L: np.where(L <= 1000, L, 100 + (L - 100) % 900)

FEATS = ['src', 'win', 'stars', 'remain', 'spec_used', 'assist', 'used_ratio', 'total_balls', 'z_attempt',
         'roll10w_z_attempt', 'roll10_win', 'roll10_spec_used', 'roll10_assist', 'roll10w_used_ratio',
         'consec_loss', 'consec_win', 'tries_at_level', 'attempt_idx', 'dsi', 'sess', 'attempts_in_sess',
         'gap_prev_sec', 'max_lvl_so_far', 'lvl_loss_rate', 'next_loss_rate', 'next_jump', 'next_total_balls']
NEW = ['hsi', 'cum_engage_sec', 's_ad_usd', 'cum_ad_usd', 'cum_ad_imps', 's_engage_sec', 'hour_utc',
       'roll10_ad_imps', 's_screen_views', 'cum_rate_dialog', 's_ad_imps', 'dow']
F5 = FEATS + NEW + ['tier_c']
TIERS = ['T1', 'T2', 'T3', 'Z']
S_COLS = ['s_ad_imps', 's_ad_usd', 's_rewarded', 's_ad_fail', 's_rate_dialog', 's_screen_views',
          's_engage_sec', 's_new_session']


def level_tables(st):
    st = st.set_index('src')
    lr = st.lr.reindex(range(1, 1001))
    lr = lr.fillna(lr.mean())
    jump = (lr - lr.shift(1).rolling(3, min_periods=1).mean()).fillna(0)
    return dict(mu=st.mu, sd=st.sd, lr=lr, jump=jump)


def roll_mean(frame, col, wn=10):
    v = frame[col].fillna(0)
    n = frame[col].notna().astype(float)
    u = frame.uid
    cv = v.groupby(u).cumsum()
    cn = n.groupby(u).cumsum()
    return (cv - cv.groupby(u).shift(wn).fillna(0)) / (cn - cn.groupby(u).shift(wn).fillna(0)).replace(0, np.nan)


def build(df, ex, ST, cfg, tier):
    for c in ['sess', 'lvl', 'win', 'stars', 'remain', 'spec_used', 'user_do', 'next_ts']:
        df[c] = pd.to_numeric(df[c], errors='coerce')
    df = df.dropna(subset=['lvl', 'win']).sort_values(['uid', 'ts']).reset_index(drop=True)
    df['src'] = src(df.lvl)
    df['total_balls'] = df.src.map(cfg)
    gap_next = df.next_ts - df.ts
    df['lost_7d'] = ((df.next_ts.isna()) | (df.next_ts == 0) | (gap_next > 7 * DAY)).astype(int)

    mu = df.src.map(ST['mu'])
    sd = df.src.map(ST['sd']).replace(0, np.nan)
    g = df.groupby('uid', sort=False)
    df['assist'] = ((df.user_do.notna()) & (df.user_do != 1)).astype(int)
    df['used_ratio'] = np.where(df.win == 1, ((df.total_balls - df.remain) / df.total_balls).clip(0, 1), np.nan)
    df['z_attempt'] = np.where(df.win == 1, (df.remain - mu) / sd, np.nan)
    df['attempt_idx'] = g.cumcount() + 1
    df['gap_prev_sec'] = (df.ts - g.ts.shift(1)) / 1e6
    df['max_lvl_so_far'] = g.lvl.cummax()
    df['tries_at_level'] = df.groupby(['uid', 'lvl']).cumcount() + 1
    df['attempts_in_sess'] = df.groupby(['uid', 'sess']).cumcount() + 1
    chg = (df.win != g.win.shift(1)) | (df.uid != df.uid.shift(1))
    streak = df.groupby(chg.cumsum()).cumcount() + 1
    df['consec_loss'] = np.where(df.win == 0, streak, 0)
    df['consec_win'] = np.where(df.win == 1, streak, 0)
    for c in ['win', 'spec_used', 'assist']:
        df[f'roll10_{c}'] = roll_mean(df, c)
    W = df[df.win == 1]
    for c in ['z_attempt', 'used_ratio']:
        r = pd.Series(np.nan, index=df.index)
        r.loc[W.index] = roll_mean(W, c)
        df[f'roll10w_{c}'] = r.groupby(df.uid).ffill()
    nxt = np.where(df.win == 1, src(df.lvl + 1), df.src)
    df['lvl_loss_rate'] = df.src.map(ST['lr'])
    df['next_loss_rate'] = pd.Series(nxt).map(ST['lr']).values
    df['next_jump'] = pd.Series(nxt).map(ST['jump']).values
    df['next_total_balls'] = pd.Series(nxt).map(cfg).values

    for c in S_COLS + ['hsi']:
        ex[c] = pd.to_numeric(ex[c], errors='coerce')
    ex[S_COLS] = ex[S_COLS].fillna(0)
    ex = ex.drop_duplicates(['uid', 'ts'])
    df = df.merge(ex, on=['uid', 'ts'], how='left').sort_values(['uid', 'ts']).reset_index(drop=True)
    g = df.groupby('uid', sort=False)
    sec = df.ts // 1_000_000
    df['hour_utc'] = (sec // 3600) % 24
    df['dow'] = ((sec // 86400) + 4) % 7
    for c in ['s_ad_imps', 's_ad_usd', 's_ad_fail', 's_rate_dialog', 's_engage_sec']:
        df['cum_' + c[2:]] = g[c].cumsum()
    cs = g.s_ad_imps.cumsum()
    df['roll10_ad_imps'] = cs - cs.groupby(df.uid).shift(10).fillna(0)
    df['tier_c'] = pd.Categorical(df.country.map(tier).fillna('Z'), categories=TIERS)
    return df


# --- Bộ feature cho model chạy trên thiết bị (v7+) ---
TIER_CODE = {'T1': 0, 'T2': 1, 'T3': 2, 'Z': 3}
F_DEVICE = FEATS + NEW + ['tier_code']


def add_tier_code(df):
    df['tier_code'] = df.tier_c.astype(str).map(TIER_CODE).fillna(3).astype('int8')
    return df
