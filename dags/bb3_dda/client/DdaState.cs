// DdaState.cs - dữ liệu DDA lưu bền trên máy, theo từng người chơi (qua các lần mở app).
// Lưu: string json = state.ToJson();   Đọc: var state = DdaState.FromJson(json);
// Nên lưu sau mỗi lượt chơi và khi app chuyển nền (cỡ 2-3 KB).
// Tương thích C# 5+.
using System;
using System.Collections.Generic;

public sealed class DdaState
{
    public const int Window = 10;           // "10 lượt gần nhất"

    // --- người chơi ---
    public long FirstOpenMs;                // lần mở app đầu tiên, UTC ms (mốc tính dsi, hsi)
    public string Country;                  // tên quốc gia theo GA4, tra model_country_tier.json

    // --- lịch sử lượt chơi ---
    public int AttemptCount;                // tổng số lượt từ khi cài
    public int MaxLevel;                    // màn cao nhất từng chơi (số màn thật)
    public Dictionary<int, int> TriesByLevel = new Dictionary<int, int>();  // số màn thật -> số lượt đã chơi
    public long LastAttemptMs;              // lúc kết thúc lượt gần nhất (0 = chưa có)
    public int StreakWin = -1;              // kết quả của chuỗi hiện tại (1 thắng, 0 thua, -1 chưa có)
    public int StreakLen;                   // độ dài chuỗi hiện tại
    public List<double[]> Last10 = new List<double[]>();       // mỗi lượt: {win, specUsed, assist, adImps}
    public List<double[]> Last10Wins = new List<double[]>();   // mỗi lượt thắng: {z, usedRatio}
    public double RollWZ = double.NaN;      // roll10w_z_attempt gần nhất (giữ nguyên khi thua)
    public double RollWUsed = double.NaN;   // roll10w_used_ratio gần nhất
    public List<double> WinMargins = new List<double>();       // policy: remainAdj / T của các lượt thắng gần nhất

    // --- phiên chơi ---
    public int SessionNumber;               // giống ga_session_number: tăng khi quay lại sau >= 30 phút
    public int AttemptsInSession;
    public long LastActiveMs;               // lần cuối app hoạt động (vào nền / kết thúc lượt)
    public long ForegroundSinceMs;          // đang ở foreground từ lúc này (0 = đang ở nền)

    // --- cộng dồn từ khi cài ---
    public double CumAdImps, CumAdUsd, CumEngageSec, CumRateDialog;

    // --- bộ đếm "trong lượt": từ level_up trước đến level_up này, đặt về 0 sau mỗi lượt ---
    public double SegAdImps, SegAdUsd, SegEngageSec, SegScreenViews, SegRateDialog;

    // --- policy ---
    public double R;                        // > 0: thêm r x số bóng gốc; < 0: bớt |r| x độ dư
    public int NextLevel;                   // màn đã tính sẵn số bóng cho lượt kế tiếp (0 = chưa có)
    public int NextBallsGiven;              // số bóng cấp cho NextLevel
    public int CurrentLevel;                // màn đang chơi (GetBallsForLevel gần nhất)
    public int CurrentBallsGiven;           // số bóng đã cấp cho màn đang chơi

    public string ToJson()
    {
        var tries = new Dictionary<string, object>();
        foreach (var kv in TriesByLevel) tries[kv.Key.ToString()] = kv.Value;
        var d = new Dictionary<string, object>();
        d["v"] = 1;
        d["first_open_ms"] = FirstOpenMs;
        d["country"] = Country;
        d["attempt_count"] = AttemptCount;
        d["max_level"] = MaxLevel;
        d["tries"] = tries;
        d["last_attempt_ms"] = LastAttemptMs;
        d["streak_win"] = StreakWin;
        d["streak_len"] = StreakLen;
        d["last10"] = Last10;
        d["last10_wins"] = Last10Wins;
        d["roll_w_z"] = RollWZ;
        d["roll_w_used"] = RollWUsed;
        d["win_margins"] = WinMargins;
        d["session"] = SessionNumber;
        d["attempts_in_session"] = AttemptsInSession;
        d["last_active_ms"] = LastActiveMs;
        d["fg_since_ms"] = ForegroundSinceMs;
        d["cum"] = new[] { CumAdImps, CumAdUsd, CumEngageSec, CumRateDialog };
        d["seg"] = new[] { SegAdImps, SegAdUsd, SegEngageSec, SegScreenViews, SegRateDialog };
        d["r"] = R;
        d["next"] = new[] { NextLevel, NextBallsGiven, CurrentLevel, CurrentBallsGiven };
        return DdaJson.Write(d);
    }

    public static DdaState FromJson(string json)
    {
        var s = new DdaState();
        if (string.IsNullOrEmpty(json)) return s;
        var d = DdaJson.Obj(DdaJson.Parse(json));
        s.FirstOpenMs = DdaJson.Long(DdaJson.Get(d, "first_open_ms"));
        s.Country = (string)DdaJson.Get(d, "country");
        s.AttemptCount = DdaJson.Int(DdaJson.Get(d, "attempt_count"));
        s.MaxLevel = DdaJson.Int(DdaJson.Get(d, "max_level"));
        foreach (var kv in DdaJson.Obj(DdaJson.Get(d, "tries")))
            s.TriesByLevel[int.Parse(kv.Key)] = DdaJson.Int(kv.Value);
        s.LastAttemptMs = DdaJson.Long(DdaJson.Get(d, "last_attempt_ms"));
        s.StreakWin = DdaJson.Int(DdaJson.Get(d, "streak_win"));
        s.StreakLen = DdaJson.Int(DdaJson.Get(d, "streak_len"));
        s.Last10 = Rows(DdaJson.Get(d, "last10"));
        s.Last10Wins = Rows(DdaJson.Get(d, "last10_wins"));
        s.RollWZ = DdaJson.Num(DdaJson.Get(d, "roll_w_z"));
        s.RollWUsed = DdaJson.Num(DdaJson.Get(d, "roll_w_used"));
        foreach (var x in DdaJson.Arr(DdaJson.Get(d, "win_margins"))) s.WinMargins.Add(DdaJson.Num(x));
        s.SessionNumber = DdaJson.Int(DdaJson.Get(d, "session"));
        s.AttemptsInSession = DdaJson.Int(DdaJson.Get(d, "attempts_in_session"));
        s.LastActiveMs = DdaJson.Long(DdaJson.Get(d, "last_active_ms"));
        s.ForegroundSinceMs = DdaJson.Long(DdaJson.Get(d, "fg_since_ms"));
        var cum = DdaJson.Arr(DdaJson.Get(d, "cum"));
        s.CumAdImps = DdaJson.Num(cum[0]); s.CumAdUsd = DdaJson.Num(cum[1]);
        s.CumEngageSec = DdaJson.Num(cum[2]); s.CumRateDialog = DdaJson.Num(cum[3]);
        var seg = DdaJson.Arr(DdaJson.Get(d, "seg"));
        s.SegAdImps = DdaJson.Num(seg[0]); s.SegAdUsd = DdaJson.Num(seg[1]); s.SegEngageSec = DdaJson.Num(seg[2]);
        s.SegScreenViews = DdaJson.Num(seg[3]); s.SegRateDialog = DdaJson.Num(seg[4]);
        s.R = DdaJson.Num(DdaJson.Get(d, "r"));
        var nx = DdaJson.Arr(DdaJson.Get(d, "next"));
        s.NextLevel = DdaJson.Int(nx[0]); s.NextBallsGiven = DdaJson.Int(nx[1]);
        s.CurrentLevel = DdaJson.Int(nx[2]); s.CurrentBallsGiven = DdaJson.Int(nx[3]);
        return s;
    }

    static List<double[]> Rows(object o)
    {
        var res = new List<double[]>();
        foreach (var r in DdaJson.Arr(o))
        {
            var a = DdaJson.Arr(r);
            var row = new double[a.Count];
            for (int i = 0; i < a.Count; i++) row[i] = DdaJson.Num(a[i]);
            res.Add(row);
        }
        return res;
    }
}
