# Train LightGBM giới hạn số cây + đánh giá + ngưỡng, so với model đang dùng trên CÙNG tập đánh giá
import os, gc, glob, json, time, shutil, logging
import numpy as np, pandas as pd, lightgbm as lgb
import pyarrow.dataset as ds
from sklearn.metrics import roc_auc_score, average_precision_score

from configs import settings as S
from core.fe_lib import F_DEVICE

log = logging.getLogger(__name__)
T = 'lost_7d'
ZONES = ['1-5', '6-10', '11+']


def zone_of(lvl):
    return np.select([lvl <= 5, lvl <= 10], ['1-5', '6-10'], '11+')


def within_tenure_roc(y, p, attempt_idx):
    q = pd.qcut(pd.Series(attempt_idx).rank(method='first'), 5, labels=False).values
    return float(np.mean([roc_auc_score(y[q == i], p[q == i]) for i in range(5) if len(np.unique(y[q == i])) > 1]))


def evaluate(y, p, lvl, attempt_idx):
    z = zone_of(lvl)
    m = dict(roc=float(roc_auc_score(y, p)), pr=float(average_precision_score(y, p)),
             roc_tenure=within_tenure_roc(y, p, attempt_idx), base_rate=float(y.mean()), n=int(len(y)))
    m['zones'] = {k: dict(roc=float(roc_auc_score(y[z == k], p[z == k])), pr=float(average_precision_score(y[z == k], p[z == k])),
                          rate=float(y[z == k].mean())) for k in ZONES if len(np.unique(y[z == k])) > 1}
    return m


def train_model(work_dir, run_dir):
    os.makedirs(run_dir, exist_ok=True)
    t0 = time.time()
    D = ds.dataset(sorted(glob.glob(os.path.join(work_dir, 'chunk_*.parquet'))), format='parquet')
    tr = D.to_table(filter=ds.field('split') == 'train', columns=F_DEVICE + [T, 'w']).to_pandas()
    n_tr = len(tr)
    dtr = lgb.Dataset(tr[F_DEVICE], tr[T], weight=tr.w, params=S.LGB_PARAMS, free_raw_data=True).construct()
    del tr; gc.collect()
    va = D.to_table(filter=ds.field('split') == 'valid', columns=F_DEVICE + [T, 'uid', 'lvl']).to_pandas()
    half = (pd.util.hash_pandas_object(va.uid, index=False).values % 2) == 0     # 1/2 user: dừng sớm, 1/2: đánh giá
    dva = lgb.Dataset(va.loc[half, F_DEVICE], va.loc[half, T], reference=dtr, free_raw_data=True).construct()
    ev = va.loc[~half].reset_index(drop=True)
    del va; gc.collect()
    log.info('train %s luot | danh gia %s luot (%.0fs)', f'{n_tr:,}', f'{len(ev):,}', time.time() - t0)

    m = lgb.train(S.LGB_PARAMS, dtr, S.MAX_TREES, valid_sets=[dva],
                  callbacks=[lgb.early_stopping(S.EARLY_STOP, verbose=False)])
    best = m.best_iteration or S.MAX_TREES
    m.save_model(os.path.join(run_dir, 'model.txt'), num_iteration=best)
    del dtr, dva; gc.collect()
    log.info('train xong: %d cay (%.1f phut)', best, (time.time() - t0) / 60)

    y, lvl, ai = ev[T].values, ev.lvl.values, ev.attempt_idx.values
    m = lgb.Booster(model_file=os.path.join(run_dir, 'model.txt'))
    p = m.predict(ev[F_DEVICE])
    z = zone_of(lvl)
    thr_flag = {k: float(np.quantile(p[z == k], 1 - S.FLAG_BUDGET)) for k in ZONES}
    thr_low = {k: float(np.quantile(p[z == k], S.LOW_RISK_Q)) for k in ZONES}
    res = dict(trees=int(m.num_trees()), n_train=int(n_tr), new=evaluate(y, p, lvl, ai),
               thr_flag=thr_flag, thr_low=thr_low, gain=_gain(m))

    prod = os.path.join(S.RELEASE_DIR, 'latest', 'model.txt')
    if os.path.exists(prod):
        pm = lgb.Booster(model_file=prod)
        if pm.feature_name() == F_DEVICE:
            res['prod'] = evaluate(y, pm.predict(ev[F_DEVICE]), lvl, ai)
            res['prod_version'] = json.load(open(os.path.join(S.RELEASE_DIR, 'latest', S.PKG_MANIFEST)))['version']
        else:
            log.warning('model dang dung co bo feature khac -> bo qua so sanh')
    shutil.copy(os.path.join(work_dir, 'level_stats.csv'), os.path.join(run_dir, 'level_stats.csv'))
    # mẫu nhỏ để kiểm tra parity khi đóng gói
    ev.sample(min(200_000, len(ev)), random_state=0)[F_DEVICE].to_parquet(os.path.join(run_dir, 'parity_sample.parquet'), index=False)
    json.dump(res, open(os.path.join(run_dir, 'metrics.json'), 'w'), indent=2)
    log.info('danh gia: ROC %.4f PR %.4f | model dang dung: %s', res['new']['roc'], res['new']['pr'],
             f"ROC {res['prod']['roc']:.4f} PR {res['prod']['pr']:.4f}" if 'prod' in res else 'chua co')
    return res


def _gain(m):
    g = pd.Series(m.feature_importance('gain'), index=m.feature_name())
    return (g / g.sum() * 100).round(2).sort_values(ascending=False).head(10).to_dict()
