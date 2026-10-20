# Đóng gói model cho thiết bị: model_trees.bin (cây quyết định dạng mảng) + model_manifest.json + model_levels.json + model_country_tier.json
#
# Định dạng model_trees.bin (little-endian), đọc bởi client/DdaModel.cs:
#   header : char[4] 'BB3D' | uint16 format_version (=1) | uint16 n_features | uint32 n_trees
#   mỗi cây: uint16 n_internal | uint16 n_leaves
#            uint8  feature[n_internal]
#            uint8  flags[n_internal]      bit0 = default_left; bit1-2 = missing_type (0 None, 1 Zero, 2 NaN)
#            float64 threshold[n_internal]
#            int16  left[n_internal], right[n_internal]   (>= 0: nút trong; < 0: lá thứ -(v+1))
#            float32 leaf[n_leaves]
#   dự báo = sigmoid( tổng giá trị lá của mọi cây )
# Quy tắc đi xuống nhánh giống LightGBM (Tree::NumericalDecision):
#   x = NaN và missing_type != NaN -> x = 0
#   (missing_type = Zero và |x| <= 1e-35) hoặc (missing_type = NaN và x = NaN) -> theo default_left
#   ngược lại: x <= threshold -> trái, x > threshold -> phải
import os, re, io, json, gzip, struct, hashlib, logging
from datetime import datetime, timezone
import numpy as np, pandas as pd, lightgbm as lgb

from configs import settings as S
from core.fe_lib import F_DEVICE, level_tables, TIER_CODE

log = logging.getLogger(__name__)
MAGIC, FORMAT_VERSION = b'BB3D', 1
MISSING = {'None': 0, 'Zero': 1, 'NaN': 2}
K_ZERO = 1e-35


def flatten(tree):
    """Cây LightGBM (dict lồng nhau) -> mảng nút trong + mảng lá."""
    feat, flags, thr, left, right, leaves = [], [], [], [], [], []
    root = tree['tree_structure']
    if 'leaf_value' in root:                      # cây chỉ có 1 lá
        return dict(feat=feat, flags=flags, thr=thr, left=left, right=right, leaves=[root['leaf_value']])

    def visit(node):
        if 'leaf_value' in node:
            leaves.append(node['leaf_value'])
            return -len(leaves)                   # lá thứ k -> -(k+1)
        assert node['decision_type'] == '<=', node['decision_type']
        i = len(feat)
        feat.append(node['split_feature'])
        flags.append(int(node['default_left']) | (MISSING[node['missing_type']] << 1))
        thr.append(float(node['threshold']))
        left.append(0); right.append(0)
        left[i] = visit(node['left_child'])
        right[i] = visit(node['right_child'])
        return i

    visit(root)
    return dict(feat=feat, flags=flags, thr=thr, left=left, right=right, leaves=leaves)


def write_bin(trees, n_features):
    b = io.BytesIO()
    b.write(MAGIC); b.write(struct.pack('<HHI', FORMAT_VERSION, n_features, len(trees)))
    for t in trees:
        ni, nl = len(t['feat']), len(t['leaves'])
        assert ni < 32768 and nl < 32768 and n_features < 256
        b.write(struct.pack('<HH', ni, nl))
        b.write(np.asarray(t['feat'], '<u1').tobytes()); b.write(np.asarray(t['flags'], '<u1').tobytes())
        b.write(np.asarray(t['thr'], '<f8').tobytes())
        b.write(np.asarray(t['left'], '<i2').tobytes()); b.write(np.asarray(t['right'], '<i2').tobytes())
        b.write(np.asarray(t['leaves'], '<f4').tobytes())
    return b.getvalue()


def read_bin(buf):
    """Bộ đọc tham chiếu (numpy) - cùng logic với client/DdaModel.cs."""
    assert buf[:4] == MAGIC
    ver, nf, nt = struct.unpack_from('<HHI', buf, 4)
    o, trees = 12, []
    for _ in range(nt):
        ni, nl = struct.unpack_from('<HH', buf, o); o += 4
        f = np.frombuffer(buf, '<u1', ni, o); o += ni
        fl = np.frombuffer(buf, '<u1', ni, o); o += ni
        th = np.frombuffer(buf, '<f8', ni, o); o += 8 * ni
        le = np.frombuffer(buf, '<i2', ni, o).astype(np.int64); o += 2 * ni
        ri = np.frombuffer(buf, '<i2', ni, o).astype(np.int64); o += 2 * ni
        lv = np.frombuffer(buf, '<f4', nl, o).astype(np.float64); o += 4 * nl
        trees.append((f, fl, th, le, ri, lv))
    assert o == len(buf)
    return nf, trees


def predict_bin(trees, X):
    X = np.asarray(X, dtype=np.float64)
    raw = np.zeros(len(X))
    rows = np.arange(len(X))
    for f, fl, th, le, ri, lv in trees:
        if len(f) == 0:
            raw += lv[0]; continue
        node = np.zeros(len(X), np.int64)
        active = np.ones(len(X), bool)
        while active.any():
            a = np.where(active)[0]
            nd = node[a]
            x = X[a, f[nd]]
            mt = (fl[nd] >> 1) & 3
            dl = (fl[nd] & 1) == 1
            nan = np.isnan(x)
            x = np.where(nan & (mt != 2), 0.0, x)
            use_def = ((mt == 1) & (np.abs(x) <= K_ZERO)) | ((mt == 2) & nan)
            go_left = np.where(use_def, dl, x <= th[nd])
            nxt = np.where(go_left, le[nd], ri[nd])
            leaf = nxt < 0
            raw[a[leaf]] += lv[-nxt[leaf] - 1]
            node[a[~leaf]] = nxt[~leaf]
            active[a[leaf]] = False
    return 1 / (1 + np.exp(-raw))


def sha(b):
    return hashlib.sha256(b).hexdigest()


def next_version():
    """MAJOR.MINOR: MINOR = bản phát hành gần nhất cùng MAJOR + 1 (chưa có -> MAJOR.0)."""
    hist = os.path.join(S.RELEASE_DIR, 'history.jsonl')
    minors = []
    if os.path.exists(hist):
        for line in open(hist):
            m = re.fullmatch(r'(\d+)\.(\d+)', json.loads(line).get('version', ''))
            if m and int(m.group(1)) == S.MODEL_MAJOR:
                minors.append(int(m.group(2)))
    return f"{S.MODEL_MAJOR}.{max(minors) + 1 if minors else 0}"


def package(run_dir, run_date, windows, metrics):
    m = lgb.Booster(model_file=os.path.join(run_dir, 'model.txt'))
    assert m.feature_name() == F_DEVICE, 'thu tu feature khong khop F_DEVICE'
    dump = m.dump_model()
    assert dump['objective'].startswith('binary'), dump['objective']
    trees = [flatten(t) for t in dump['tree_info']]
    blob = write_bin(trees, len(F_DEVICE))

    # parity: bộ đọc tham chiếu vs LightGBM
    X = pd.read_parquet(os.path.join(run_dir, 'parity_sample.parquet'))[F_DEVICE]
    X = pd.DataFrame({c: X[c].astype('Float64').to_numpy(dtype='float64', na_value=np.nan) for c in F_DEVICE})
    nf, tr = read_bin(blob)
    p_bin, p_lgb = predict_bin(tr, X.values), m.predict(X)
    max_diff = float(np.abs(p_bin - p_lgb).max())
    log.info('parity %s luot: chenh lech lon nhat %.2e', f'{len(X):,}', max_diff)
    if max_diff > 1e-5:
        raise RuntimeError(f'{S.PKG_MODEL} khong khop LightGBM (max diff {max_diff:.2e})')

    pkg = os.path.join(run_dir, 'package')
    os.makedirs(pkg, exist_ok=True)
    st = pd.read_csv(os.path.join(run_dir, 'level_stats.csv'))
    LT = level_tables(st)
    cfg = pd.read_csv(os.path.join(S.DATA_DIR, 'level_config.csv')).set_index('level').total_balls
    num = lambda v: None if pd.isna(v) else round(float(v), 6)
    levels = [dict(level=int(L), total_balls=int(cfg.get(L, 0)), mu=num(LT['mu'].get(L)), sd=num(LT['sd'].get(L)),
                   loss_rate=num(LT['lr'].get(L)), jump=num(LT['jump'].get(L))) for L in range(1, 1001)]
    tier = pd.read_csv(os.path.join(S.DATA_DIR, 'country_tier.csv'))
    country = {r.country: TIER_CODE[r.tier] for r in tier.itertuples() if isinstance(r.country, str)}
    files = {S.PKG_MODEL: blob,
             S.PKG_LEVELS: json.dumps(levels, separators=(',', ':')).encode(),
             S.PKG_TIER: json.dumps(dict(default=TIER_CODE['Z'], map=country), separators=(',', ':')).encode()}
    for name, b in files.items():
        open(os.path.join(pkg, name), 'wb').write(b)
    open(os.path.join(pkg, S.PKG_MODEL + '.gz'), 'wb').write(gzip.compress(blob, 9))

    version = next_version()
    build = f"{run_date.strftime('%Y%m%d')}-t{len(trees)}"     # mã nội bộ: ngày dữ liệu + số cây
    manifest = dict(
        version=version, build=build, created_utc=datetime.now(timezone.utc).isoformat(timespec='seconds'),
        format_version=FORMAT_VERSION, objective='binary_logistic', n_trees=len(trees),
        features=F_DEVICE,
        feature_notes={'z_attempt': 'NaN neu luot thua', 'used_ratio': 'NaN neu luot thua',
                       'gap_prev_sec': 'NaN o luot dau', 'roll10w_*': 'NaN neu chua co luot thang',
                       'tier_code': 'tra ' + S.PKG_TIER + ', mac dinh 3 (Z)',
                       'src': 'level neu <= 1000, nguoc lai 100 + (level - 100) % 900',
                       'level tables': 'mu, sd, loss_rate, jump, total_balls theo src trong ' + S.PKG_LEVELS},
        zones={'1-5': [1, 5], '6-10': [6, 10], '11+': [11, None]},
        thr_flag=metrics['thr_flag'], thr_low=metrics['thr_low'],
        flag_budget=S.FLAG_BUDGET, low_risk_quantile=S.LOW_RISK_Q, policy=S.POLICY,
        data_window=windows, metrics=dict(new=metrics['new'], prod=metrics.get('prod')),
        parity_max_abs_diff=max_diff,
        files={n: dict(bytes=len(b), sha256=sha(b)) for n, b in files.items()},
    )
    json.dump(manifest, open(os.path.join(pkg, S.PKG_MANIFEST), 'w'), indent=2, ensure_ascii=False)
    log.info('dong goi %s: ' + S.PKG_MODEL + ' %.0f KB (gzip %.0f KB)', version, len(blob) / 1024,
             os.path.getsize(os.path.join(pkg, S.PKG_MODEL + '.gz')) / 1024)
    return dict(version=version, build=build, bytes=len(blob), parity=max_diff, pkg=pkg)
