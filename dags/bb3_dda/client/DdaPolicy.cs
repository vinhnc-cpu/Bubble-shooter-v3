// DdaPolicy.cs - chính sách thêm/bớt bóng v6, GIỐNG HỆT client/dda_policy_v6.py.
// Tham số lấy từ manifest.policy (DdaPolicyParams), không hard-code.
// Tương thích C# 5+.
//
//   THÊM: cộng dồn theo tỷ lệ số bóng gốc khi bị gắn cờ rủi ro cao và đang vật lộn.
//   BỚT : theo độ dư của chính người chơi khi thắng dễ liên tiếp và rủi ro thấp.
//   r > 0: thêm r x số bóng gốc (vd 0.10 = +10%); r < 0: bớt |r| x độ dư (vd -0.20 = bớt 20% độ dư).
using System;
using System.Collections.Generic;

public static class DdaPolicy
{
    const double Eps = 1e-9;

    /// <summary>Đang vật lộn: thua, hoặc gần đây dùng nhiều bóng đặc biệt / hay cần trợ giúp.</summary>
    public static bool IsStruggling(DdaPolicyParams p, bool win, double roll10SpecUsed, double roll10Assist)
    {
        return !win || roll10SpecUsed >= p.StruggleSpecUsed || roll10Assist >= p.StruggleAssist;
    }

    /// <summary>Thắng dễ: thắng liên tiếp đủ số lần, dư bóng nhiều hơn người chơi khác, và rủi ro thấp.</summary>
    public static bool IsEasy(DdaPolicyParams p, bool win, double consecWin, double roll10wZ, bool lowRisk)
    {
        return win && consecWin >= p.CutWins && roll10wZ >= p.CutZ && lowRisk;
    }

    /// <summary>
    /// Số bóng dư quy về số bóng gốc T (lượt đã được thêm/bớt bóng).
    /// Dùng cho feature remain, used_ratio, z_attempt, roll10w_* và độ dư của policy.
    /// Không điều chỉnh -> remain thật; thua -> 0.
    /// </summary>
    public static int RemainAdj(int remain, bool win, int ballsGiven, int totalBalls)
    {
        int delta = ballsGiven - totalBalls;
        if (delta == 0) return remain;
        return win ? Math.Max(0, remain - delta) : 0;
    }

    /// <summary>Gọi sau MỖI lượt: lưu tỷ lệ bóng dư của lượt thắng (giữ MarginN lượt thắng gần nhất).</summary>
    public static void UpdateMargins(DdaPolicyParams p, List<double> winMargins, bool win, int remainAdj, int totalBalls)
    {
        if (!win || totalBalls <= 0) return;
        winMargins.Add(Math.Max(remainAdj, 0) / (double)totalBalls);
        while (winMargins.Count > p.MarginN) winMargins.RemoveAt(0);
    }

    /// <summary>Gọi sau MỖI lượt. Trả về r cho lượt chơi kế tiếp (thắng: màn mới, thua: chơi lại màn đó).</summary>
    public static double UpdateR(DdaPolicyParams p, double r, int level, bool win, bool flagged, bool struggling,
                                 bool easy, double consecWin)
    {
        if (level < Math.Min(p.MinLevelAdd, p.MinLevelCut))
            return 0.0;
        // 1) bị gắn cờ: bỏ phần bớt bóng; nếu đang vật lộn thì cộng dồn thêm
        if (flagged)
        {
            r = Math.Max(r, 0.0);
            if (struggling && level >= p.MinLevelAdd)
                r = Math.Min(r + p.StepUp, p.RUpMax);
            return r;
        }
        // 2) đang bớt bóng mà thua -> trả về số bóng gốc ngay
        if (r < 0 && !win)
            return 0.0;
        // 3) đang thêm bóng: giảm dần khi thắng liên tiếp
        if (r > 0)
        {
            if (win && consecWin >= p.WinDecay)
                r = Math.Max(r - p.StepUp, 0.0);
            return r;
        }
        // 4) r <= 0: bớt cộng dồn theo độ dư khi thắng dễ và rủi ro thấp
        if (level >= p.MinLevelCut && easy)
            r = Math.Max(r - p.StepDown, -p.GDownMax);
        return r;
    }

    /// <summary>Số bóng cộng (+) / trừ (-) so với số bóng gốc của lượt chơi kế tiếp.</summary>
    public static int BallDelta(DdaPolicyParams p, double r, List<double> winMargins, int totalBallsNext)
    {
        if (r > 0)
            return (int)Math.Ceiling(r * totalBallsNext - Eps);
        if (r < 0 && winMargins.Count > 0)
        {
            double margin = 0;
            foreach (var m in winMargins) margin += m;
            margin /= winMargins.Count;
            int k = (int)Math.Ceiling(-r * margin * totalBallsNext - Eps);   // làm tròn lên (giống phía thêm)
            k = Math.Min(k, (int)Math.Floor(p.CapDown * totalBallsNext + Eps));
            return -Math.Max(p.CutMinBalls, k);      // đang ở trạng thái bớt: bớt tối thiểu CutMinBalls quả
        }
        return 0;
    }
}
