# Cấu hình project bb3_dda (Bubble Shooter 3 - DDA: dự báo bỏ game sau mỗi lượt + thêm/bớt bóng)
import os

PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(PROJECT_DIR, 'data')            # level_config.csv, country_tier.csv
WORK_DIR = os.path.join(PROJECT_DIR, 'work')            # dữ liệu tạm theo ngày chạy (tự xóa sau khi xong)
RUNS_DIR = os.path.join(PROJECT_DIR, 'runs')            # model ứng viên + metrics mỗi ngày
RELEASE_DIR = os.path.join(PROJECT_DIR, 'releases')     # gói model đã được chấp nhận; releases/latest = bản đang dùng
KEEP_RUNS = 14                                          # giữ 14 ngày gần nhất
# Version model dạng MAJOR.MINOR (giống app_version): mỗi lần phát hành MINOR + 1.
# Tăng MAJOR (MINOR về 0) khi đổi feature / định dạng model_trees.bin (client phải cập nhật code).
MODEL_MAJOR = 1

# Tên file trong gói model đưa vào game (tiền tố model_ để không nhầm với file của hệ thống / game)
PKG_MODEL = 'model_trees.bin'                 # cây quyết định, định dạng BB3D (bản nén: + '.gz')
PKG_MANIFEST = 'model_manifest.json'          # version, thứ tự feature, ngưỡng, policy, sha256
PKG_LEVELS = 'model_levels.json'              # bảng 1000 màn
PKG_TIER = 'model_country_tier.json'          # quốc gia -> tier_code

# ClickHouse: HTTP 8123 (TCP 9000 bị chặn từ subnet Docker)
# Thông tin kết nối lấy từ biến môi trường BB3_CH_*; nếu không có thì đọc configs/local_secrets.py (không đưa lên git).
try:
    from configs import local_secrets as _ls
except ImportError:
    _ls = None
CH = dict(host=os.environ.get('BB3_CH_HOST', getattr(_ls, 'CH_HOST', '')),
          port=int(os.environ.get('BB3_CH_PORT', getattr(_ls, 'CH_PORT', 8123))),
          username=os.environ.get('BB3_CH_USER', getattr(_ls, 'CH_USER', '')),
          password=os.environ.get('BB3_CH_PASSWORD', getattr(_ls, 'CH_PASSWORD', '')))
SOURCE_TABLE = 'bubble_shooter_v3.bubble_shooter_v3_ga4_staging_flat'
# Lọc event_timestamp tương lai: dùng mốc động = hết ngày data_end (xem build_dataset.windows).
# KHÔNG dùng hằng số 1790000000000000 (= 2026-09-21 13:46 UTC) vì dữ liệu đã vượt mốc này.

# Cửa sổ dữ liệu (tính theo ngày chạy D, dữ liệu đầy đủ đến D-1)
LABEL_DAYS = 7                     # nhãn lost_7d: không có level_up trong 7 ngày sau lượt
COHORT_DAYS = 240                  # user cài trong 240 ngày trước mốc nhãn
VALID_DAYS = 35                    # 35 ngày cài gần nhất: valid (dừng sớm + đánh giá + ngưỡng)
MAX_DSI = 60                       # chỉ lấy 60 ngày đầu sau cài
N_CHUNKS = 40                      # chia user theo hash để vừa 16 GB RAM của worker
NEG_SAMPLE = 0.20                  # train: giữ toàn bộ lượt dương + 20% lượt âm (trọng số x5)
MIN_ROWS_D1 = 500_000              # số level_up tối thiểu để coi 1 ngày là đã về đủ
MAX_LAG_DAYS = 4                   # dữ liệu mới nhất trễ quá 4 ngày -> fail (bảng staging thường trễ 1-2 ngày)

# Model
LGB_PARAMS = dict(objective='binary', metric='average_precision', learning_rate=0.05, num_leaves=127,
                  min_data_in_leaf=500, feature_fraction=0.8, bagging_fraction=0.8, bagging_freq=1,
                  verbose=-1, num_threads=12, seed=1)
MAX_TREES = 300                    # giới hạn số cây để gói model nhỏ (~0.6 MB)
EARLY_STOP = 30

# Chốt chất lượng: model mới chỉ thay model đang dùng nếu không kém hơn trên cùng tập đánh giá
GATE_MIN_ROC = 0.80                # lần đầu (chưa có model đang dùng). Tập đánh giá là user cài 35 ngày gần nhất
                                   # nên ROC thấp hơn tập test v6: v6 đạt 0.8414 trên tập này (model mới 0.8416)
GATE_MAX_ROC_DROP = 0.005
GATE_MIN_PR_RATIO = 0.95

# Ngưỡng theo vùng màn (1-5 / 6-10 / 11+), tính trên tập đánh giá
FLAG_BUDGET = 0.15                 # 15% lượt rủi ro cao nhất -> gắn cờ
LOW_RISK_Q = 0.70                  # 70% lượt rủi ro thấp nhất -> đủ điều kiện bớt bóng

# Tham số policy v6 đóng gói kèm model (client đọc từ manifest)
POLICY = dict(
    min_level_add=1, step_up=0.05, r_up_max=0.20, win_decay=2,
    min_level_cut=1, cut_wins=2, cut_z=0.3, step_down=0.10, g_down_max=0.50, cap_down=0.30, margin_n=10,
    cut_min_balls=1,      # khi r < 0: bớt tối thiểu 1 quả
    struggle_spec_used=1.0, struggle_assist=0.3,
)
