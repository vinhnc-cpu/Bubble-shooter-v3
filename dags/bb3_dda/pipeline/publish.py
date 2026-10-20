# Chốt chất lượng + phát hành gói model: releases/<version>/ và releases/latest/
import os, re, json, shutil, logging
from configs import settings as S

log = logging.getLogger(__name__)


def gate(metrics):
    new, prod = metrics['new'], metrics.get('prod')
    if prod is None:
        ok = new['roc'] >= S.GATE_MIN_ROC
        why = f"lan dau: ROC {new['roc']:.4f} {'>=' if ok else '<'} {S.GATE_MIN_ROC}"
    else:
        ok_roc = new['roc'] >= prod['roc'] - S.GATE_MAX_ROC_DROP
        ok_pr = new['pr'] >= prod['pr'] * S.GATE_MIN_PR_RATIO
        ok = ok_roc and ok_pr
        why = (f"ROC moi {new['roc']:.4f} vs dang dung {prod['roc']:.4f} (cho phep giam {S.GATE_MAX_ROC_DROP}) | "
               f"PR moi {new['pr']:.4f} vs {prod['pr']:.4f} (toi thieu x{S.GATE_MIN_PR_RATIO})")
    return ok, why


def publish(run_dir, version):
    pkg = os.path.join(run_dir, 'package')
    dst = os.path.join(S.RELEASE_DIR, version)
    if os.path.exists(dst):
        shutil.rmtree(dst)
    shutil.copytree(pkg, dst)
    shutil.copy(os.path.join(run_dir, 'model.txt'), os.path.join(dst, 'model.txt'))   # để so sánh lần sau (không đưa vào game)
    tmp = os.path.join(S.RELEASE_DIR, '.latest_tmp')
    if os.path.exists(tmp):
        shutil.rmtree(tmp)
    shutil.copytree(dst, tmp)
    latest = os.path.join(S.RELEASE_DIR, 'latest')
    if os.path.exists(latest):
        shutil.rmtree(latest)
    os.rename(tmp, latest)
    hist = os.path.join(S.RELEASE_DIR, 'history.jsonl')
    man = json.load(open(os.path.join(dst, S.PKG_MANIFEST)))
    with open(hist, 'a') as f:
        f.write(json.dumps(dict(version=version, build=man.get('build'), created=man['created_utc'], roc=man['metrics']['new']['roc'],
                                pr=man['metrics']['new']['pr'], trees=man['n_trees'])) + '\n')
    log.info('phat hanh %s -> %s', version, latest)
    return latest


def cleanup(work_dir):
    if os.path.exists(work_dir):
        shutil.rmtree(work_dir)
    for base in (S.RUNS_DIR, S.RELEASE_DIR):
        if not os.path.exists(base):
            continue
        if base == S.RELEASE_DIR:     # releases/<MAJOR.MINOR>: sắp theo số (1.10 sau 1.9)
            ds = sorted((d for d in os.listdir(base) if re.fullmatch(r'\d+\.\d+', d)),
                        key=lambda d: tuple(map(int, d.split('.'))))
        else:
            ds = sorted(d for d in os.listdir(base) if d[:1].isdigit())
        for d in ds[:-S.KEEP_RUNS]:
            shutil.rmtree(os.path.join(base, d), ignore_errors=True)
