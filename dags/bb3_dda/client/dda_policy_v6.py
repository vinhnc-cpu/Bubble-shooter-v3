# Chính sách điều chỉnh số bóng (bản tham chiếu cho client). Client đọc tham số từ manifest.policy.
#   v7 (04/11/2026, sau A/B 1.82.1): chỉ thêm +10% số bóng gốc cho lượt chơi lại sau khi thua và bị gắn cờ,
#       thắng là hết phần thêm; tắt bớt bóng (g_down_max = 0); "vật lộn" = thua (struggle_* = 999).
#   v6: THÊM cộng dồn 5%/lần đến 20%; BỚT theo độ dư khi thắng dễ, ngưỡng rủi ro thấp 70%.
# Trạng thái mỗi user:
#   r              > 0: tỷ lệ thêm (vd 0.10 = +10% số bóng gốc), < 0: phần độ dư bị bớt (vd -0.20 = bớt 20% độ dư)
#   win_margins    tỷ lệ bóng dư (remain / TotalBalls) của 10 lượt THẮNG gần nhất
import math

# --- Gắn cờ / rủi ro thấp (ngưỡng tính trên tập valid, model v6; client dùng thr_flag / thr_low trong manifest) ---
THR_FLAG = {'1-5': 0.1100, '6-10': 0.0754, '11+': 0.0173}   # 15% lượt rủi ro cao nhất
THR_LOW = {'1-5': 0.0777, '6-10': 0.0464, '11+': 0.0078}    # 70% lượt rủi ro thấp nhất

# --- Thêm bóng ---
MIN_LEVEL_ADD = 1
STEP_UP = 0.10        # mỗi lần bị gắn cờ và đang vật lộn: +10% số bóng gốc (v6: 0.05)
R_UP_MAX = 0.10       # trần +10%, không cộng dồn (v6: 0.20)
WIN_DECAY = 1         # thắng 1 lần là trừ STEP_UP -> về số bóng gốc (v6: 2)
STRUGGLE_SPEC_USED = 999.0   # vật lộn chỉ khi thua (v6: roll10_spec_used >= 1.0)
STRUGGLE_ASSIST = 999.0      # (v6: roll10_assist >= 0.3)

# --- Bớt bóng ---
MIN_LEVEL_CUT = 1     # bớt bóng từ màn 1 (trước: màn 11)
CUT_WINS = 2          # thắng liên tiếp >= 2 lần
CUT_Z = 0.3           # trung bình z của 10 lượt thắng gần nhất >= 0.3
STEP_DOWN = 0.10      # mỗi lần thắng dễ: bớt thêm 10% độ dư
G_DOWN_MAX = 0.0      # trần bớt; 0 = tắt bớt bóng (v6: 0.50 độ dư)
CAP_DOWN = 0.30       # và không quá 30% số bóng gốc của màn sắp chơi
CUT_MIN_BALLS = 1     # khi r < 0: bớt tối thiểu 1 quả (giống phía thêm luôn >= 1)
MARGIN_N = 10

EPS = 1e-9


def zone(level):
    return '1-5' if level <= 5 else ('6-10' if level <= 10 else '11+')


def is_flagged(p, level):
    return p >= THR_FLAG[zone(level)]


def is_low_risk(p, level):
    return p <= THR_LOW[zone(level)]


def is_struggling(win, roll10_spec_used, roll10_assist):
    return win != 1 or roll10_spec_used >= STRUGGLE_SPEC_USED or roll10_assist >= STRUGGLE_ASSIST


def is_easy(win, consec_win, roll10w_z_attempt, low_risk):
    return win == 1 and consec_win >= CUT_WINS and roll10w_z_attempt >= CUT_Z and low_risk


def remain_adj(remain, win, balls_given, total_balls):
    """Số bóng dư quy về số bóng gốc T (lượt đã được thêm/bớt bóng). Dùng cho feature remain, used_ratio,
    z_attempt, roll10w_* và độ dư của policy. Thua -> 0; không điều chỉnh -> remain thật."""
    delta = balls_given - total_balls
    if delta == 0:
        return remain
    return max(0, remain - delta) if win == 1 else 0


def update_margins(win_margins, win, remain, total_balls):
    """Gọi sau MỖI lượt: lưu tỷ lệ bóng dư của lượt thắng (giữ 10 lượt thắng gần nhất).
    remain truyền vào là remain_adj(...) nếu lượt đã được thêm/bớt bóng."""
    if win == 1 and total_balls > 0:
        win_margins = (win_margins + [max(remain, 0) / total_balls])[-MARGIN_N:]
    return win_margins


def update_r(r, level, win, flagged, struggling, easy, consec_win):
    """Gọi sau MỖI lượt chơi. Trả về trạng thái r cho lượt chơi kế tiếp (thắng: màn mới, thua: chơi lại màn đó)."""
    if level < min(MIN_LEVEL_ADD, MIN_LEVEL_CUT):
        return 0.0
    # 1) bị gắn cờ: bỏ phần bớt bóng; nếu đang vật lộn thì cộng dồn thêm.
    #    Bị gắn cờ mà thắng (không vật lộn) và đang được thêm -> xuống bước 3 để giảm phần thêm như bình thường.
    if flagged:
        r = max(r, 0.0)
        if struggling and level >= MIN_LEVEL_ADD:
            return min(r + STEP_UP, R_UP_MAX)
        if not (win == 1 and r > 0):
            return r
    # 2) đang bớt bóng mà thua -> trả về số bóng gốc ngay
    if r < 0 and win == 0:
        return 0.0
    # 3) đang thêm bóng: giảm dần khi thắng liên tiếp
    if r > 0:
        if win == 1 and consec_win >= WIN_DECAY:
            r = max(r - STEP_UP, 0.0)
        return r
    # 4) r <= 0: bớt cộng dồn theo độ dư khi thắng dễ và rủi ro thấp
    if level >= MIN_LEVEL_CUT and easy:
        r = max(r - STEP_DOWN, -G_DOWN_MAX)
    return r


def ball_delta(r, win_margins, total_balls_next):
    """Số bóng cộng/trừ cho lượt chơi kế tiếp (thắng: màn mới, thua: chơi lại màn đó)."""
    if r > 0:
        return math.ceil(r * total_balls_next - EPS)
    if r < 0 and win_margins:
        margin = sum(win_margins) / len(win_margins)
        k = math.ceil(-r * margin * total_balls_next - EPS)      # làm tròn lên (giống phía thêm)
        k = min(k, math.floor(CAP_DOWN * total_balls_next + EPS))
        return -max(CUT_MIN_BALLS, k)       # bớt tối thiểu 1 quả khi đang ở trạng thái bớt (r < 0)
    return 0
