// DdaFeatures.cs - tính 40 feature sau mỗi lượt chơi, GIỐNG HỆT core/fe_lib.py (bản dùng để train).
// Lệch một feature thì model đoán sai mà không báo lỗi, nên không sửa công thức ở đây nếu server chưa đổi.
// Tương thích C# 5+.
//
// Quy ước:
//   - Feature tính KỂ CẢ lượt vừa chơi (cập nhật lịch sử trước rồi mới tính).
//   - "10 lượt gần nhất": theo người chơi, mọi màn; ít hơn 10 thì chia cho số đang có.
//   - Giờ, ngày, thứ theo UTC.
//   - remain dùng remainAdj (số bóng dư quy về số bóng gốc, xem DdaPolicy.RemainAdj).
using System;
using System.Collections.Generic;

/// <summary>Kết quả một lượt chơi, game truyền vào lúc gửi level_up.</summary>
public struct DdaAttempt
{
    public int Level;        // số màn thật (ep_level_up_level), có thể > 1000
    public bool Win;         // ep_level_up_value: thắng = 1
    public int Stars;        // ep_level_up_stars (thua = 0)
    public int Remain;       // số bóng dư thật (ep_level_up_numball_remain)
    public int SpecUsed;     // số bóng đặc biệt đã dùng (ep_level_up_numballspec_used)
    public int UserDo;       // ep_level_up_user_do: 1 = tự chơi, 2/3 = có trợ giúp; 0 = không gửi
}

public static class DdaFeatures
{
    static readonly string[] Known =
    {
        "src", "win", "stars", "remain", "spec_used", "assist", "used_ratio", "total_balls", "z_attempt",
        "roll10w_z_attempt", "roll10_win", "roll10_spec_used", "roll10_assist", "roll10w_used_ratio",
        "consec_loss", "consec_win", "tries_at_level", "attempt_idx", "dsi", "sess", "attempts_in_sess",
        "gap_prev_sec", "max_lvl_so_far", "lvl_loss_rate", "next_loss_rate", "next_jump", "next_total_balls",
        "hsi", "cum_engage_sec", "s_ad_usd", "cum_ad_usd", "cum_ad_imps", "s_engage_sec", "hour_utc",
        "roll10_ad_imps", "s_screen_views", "cum_rate_dialog", "s_ad_imps", "dow", "tier_code",
    };

    /// <summary>Manifest có feature game chưa biết tính -> gói model mới hơn code (tăng MAJOR), không dùng được.</summary>
    public static void CheckSupported(string[] features)
    {
        var known = new HashSet<string>(Known);
        foreach (var f in features)
            if (!known.Contains(f)) throw new InvalidOperationException("Game chua ho tro feature '" + f + "', can cap nhat code DDA");
    }

    /// <summary>
    /// Cập nhật lịch sử bằng lượt vừa chơi rồi tính feature. Gọi đúng 1 lần mỗi lượt.
    /// Không đặt lại bộ đếm Seg* (DdaEngine làm sau khi xong).
    /// </summary>
    public static Dictionary<string, double> Update(DdaState st, DdaPackage pkg, DdaAttempt a, int remainAdj, long nowMs)
    {
        const double NaN = double.NaN;
        var f = new Dictionary<string, double>(48);
        DdaLevel lv = pkg.Level(a.Level);
        int src = DdaPackage.Src(a.Level);
        double T = lv.TotalBalls > 0 ? lv.TotalBalls : NaN;
        double win = a.Win ? 1 : 0;
        double remain = remainAdj;
        double assist = (a.UserDo != 0 && a.UserDo != 1) ? 1 : 0;

        // --- lượt vừa chơi ---
        double usedRatio = a.Win ? Clamp01((T - remain) / T) : NaN;
        double z = a.Win ? (remain - lv.Mu) / lv.Sd : NaN;       // Sd = 0 đã đổi thành NaN khi đọc gói
        f["src"] = src;
        f["win"] = win;
        f["stars"] = a.Stars;
        f["remain"] = remain;
        f["spec_used"] = a.SpecUsed;
        f["assist"] = assist;
        f["used_ratio"] = usedRatio;
        f["total_balls"] = T;
        f["z_attempt"] = z;

        // --- bộ đếm theo người chơi ---
        st.AttemptCount++;
        double gap = st.LastAttemptMs > 0 ? (nowMs - st.LastAttemptMs) / 1000.0 : NaN;
        st.LastAttemptMs = nowMs;
        st.MaxLevel = Math.Max(st.MaxLevel, a.Level);
        int tries;
        st.TriesByLevel.TryGetValue(a.Level, out tries);
        st.TriesByLevel[a.Level] = ++tries;
        st.AttemptsInSession++;
        int w = a.Win ? 1 : 0;
        if (st.StreakWin == w) st.StreakLen++;
        else { st.StreakWin = w; st.StreakLen = 1; }

        // --- 10 lượt gần nhất (mọi lượt) ---
        Push(st.Last10, new[] { win, (double)a.SpecUsed, assist, st.SegAdImps });
        f["roll10_win"] = Mean(st.Last10, 0);
        f["roll10_spec_used"] = Mean(st.Last10, 1);
        f["roll10_assist"] = Mean(st.Last10, 2);
        double adSum = 0;
        foreach (var r in st.Last10) adSum += r[3];
        f["roll10_ad_imps"] = adSum;

        // --- 10 lượt THẮNG gần nhất; lượt thua giữ giá trị cũ ---
        if (a.Win)
        {
            Push(st.Last10Wins, new[] { z, usedRatio });
            double mz = Mean(st.Last10Wins, 0), mu = Mean(st.Last10Wins, 1);
            if (!double.IsNaN(mz)) st.RollWZ = mz;
            if (!double.IsNaN(mu)) st.RollWUsed = mu;
        }
        f["roll10w_z_attempt"] = st.RollWZ;
        f["roll10w_used_ratio"] = st.RollWUsed;

        f["consec_loss"] = w == 0 ? st.StreakLen : 0;
        f["consec_win"] = w == 1 ? st.StreakLen : 0;
        f["tries_at_level"] = tries;
        f["attempt_idx"] = st.AttemptCount;
        f["dsi"] = Math.Floor(nowMs / 86400000.0) - Math.Floor(st.FirstOpenMs / 86400000.0);
        f["sess"] = st.SessionNumber;
        f["attempts_in_sess"] = st.AttemptsInSession;
        f["gap_prev_sec"] = gap;
        f["max_lvl_so_far"] = st.MaxLevel;

        // --- độ khó màn (model_levels.json): thắng -> màn kế, thua -> chơi lại màn này ---
        DdaLevel nx = a.Win ? pkg.Level(a.Level + 1) : lv;
        f["lvl_loss_rate"] = lv.LossRate;
        f["next_loss_rate"] = nx.LossRate;
        f["next_jump"] = nx.Jump;
        f["next_total_balls"] = nx.TotalBalls > 0 ? nx.TotalBalls : NaN;

        // --- thời gian, quảng cáo, tương tác ---
        long sec = nowMs / 1000;
        st.CumEngageSec += st.SegEngageSec;
        st.CumAdUsd += st.SegAdUsd;
        st.CumAdImps += st.SegAdImps;
        st.CumRateDialog += st.SegRateDialog;
        f["hsi"] = Math.Max(0, Math.Floor((nowMs - st.FirstOpenMs) / 3600000.0));
        f["cum_engage_sec"] = st.CumEngageSec;
        f["s_ad_usd"] = st.SegAdUsd;
        f["cum_ad_usd"] = st.CumAdUsd;
        f["cum_ad_imps"] = st.CumAdImps;
        f["s_engage_sec"] = st.SegEngageSec;
        f["hour_utc"] = (sec / 3600) % 24;
        f["s_screen_views"] = st.SegScreenViews;
        f["cum_rate_dialog"] = st.CumRateDialog;
        f["s_ad_imps"] = st.SegAdImps;
        f["dow"] = (sec / 86400 + 4) % 7;                         // 0 = Chủ nhật ... 6 = Thứ bảy
        f["tier_code"] = pkg.TierCode(st.Country);
        return f;
    }

    /// <summary>Xếp feature theo đúng thứ tự manifest thành mảng cho DdaModel.Predict.</summary>
    public static double[] ToArray(Dictionary<string, double> f, string[] order)
    {
        var x = new double[order.Length];
        for (int i = 0; i < order.Length; i++) x[i] = f[order[i]];
        return x;
    }

    static void Push(List<double[]> buf, double[] row)
    {
        buf.Add(row);
        if (buf.Count > DdaState.Window) buf.RemoveAt(0);
    }

    /// <summary>Trung bình bỏ qua NaN (giống pandas); toàn NaN -> NaN.</summary>
    static double Mean(List<double[]> buf, int col)
    {
        double s = 0;
        int n = 0;
        foreach (var r in buf)
        {
            if (double.IsNaN(r[col])) continue;
            s += r[col];
            n++;
        }
        return n > 0 ? s / n : double.NaN;
    }

    static double Clamp01(double v)
    {
        if (double.IsNaN(v)) return v;
        return v < 0 ? 0 : (v > 1 ? 1 : v);
    }
}
