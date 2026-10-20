// DdaEngine.cs - điểm gọi duy nhất của game: ghi nhận sự kiện, tính số bóng cho màn, xử lý sau mỗi lượt.
// Tương thích C# 5+. Không phụ thuộc Unity: game tự đọc file và lưu DdaState (xem README.md).
//
// Luồng một lượt chơi:
//   1. Vào màn:        int balls = dda.GetBallsForLevel(level);          // số bóng cấp cho màn
//   2. Trong lượt:     dda.OnAdImpression(valueMicros); dda.OnScreenView(); dda.OnRateDialog();
//   3. Kết thúc lượt:  DdaResult res = dda.OnAttemptEnd(attempt, DateTime.UtcNow);
//                      gửi level_up kèm res.TrackingParams() (nếu res.Track), rồi lưu dda.State.ToJson()
//   Vòng đời app:      dda.OnAppForeground(now) khi mở / quay lại app, dda.OnAppBackground(now) khi chuyển nền.
using System;
using System.Collections.Generic;

/// <summary>
/// Off: user nhóm đối chứng - chỉ cập nhật lịch sử, không gọi model, không đổi bóng, không gửi tracking.
/// Shadow: tính điểm và gửi tracking nhưng KHÔNG đổi số bóng (chạy ngầm để kiểm tra khớp với server).
/// On: user nhóm treatment - đổi số bóng theo policy và gửi tracking.
/// </summary>
public enum DdaMode { Off, Shadow, On }

public sealed class DdaResult
{
    public bool Track;            // true: gửi TrackingParams() kèm event level_up của lượt này
    public string ModelVersion;   // dda_model_version
    public double P = double.NaN; // dda_p_value: xác suất không chơi thêm lượt nào trong 7 ngày
    public string Zone;           // vùng màn: "1-5" / "6-10" / "11+"
    public bool Flagged;          // p >= thr_flag: rủi ro cao
    public bool LowRisk;          // p <= thr_low: rủi ro thấp
    public int BallsBase;         // balls_base: số bóng gốc của màn vừa chơi
    public int BallsDelta;        // balls_delta: số bóng đã cấp cho màn vừa chơi trừ số bóng gốc
    public string Action;         // dda_action: add / keep / cut (theo BallsDelta của màn vừa chơi)
    public int NextLevel;         // màn kế tiếp (thắng: level + 1, thua: chơi lại)
    public int NextBalls;         // số bóng sẽ cấp cho NextLevel
    public double R;              // trạng thái policy sau lượt này
    public double[] Features;     // 40 feature đã đưa vào model (để debug / so khớp)

    public Dictionary<string, object> TrackingParams()
    {
        var d = new Dictionary<string, object>();
        d["dda_model_version"] = ModelVersion;
        d["dda_p_value"] = Math.Round(P, 6);
        d["balls_base"] = BallsBase;
        d["balls_delta"] = BallsDelta;
        d["dda_action"] = Action;
        return d;
    }
}

public sealed class DdaEngine
{
    public const long SessionTimeoutMs = 30L * 60 * 1000;   // giống Firebase: quay lại sau >= 30 phút = phiên mới

    public DdaPackage Package { get; private set; }
    public DdaState State { get; private set; }
    public DdaMode Mode;

    public DdaEngine(DdaPackage package, DdaState state, DdaMode mode)
    {
        if (state == null) state = new DdaState();
        Package = package;
        State = state;
        Mode = mode;
    }

    /// <summary>Thay gói model mới (tải về, đã kiểm tra sha256). Lịch sử người chơi giữ nguyên.</summary>
    public void SetPackage(DdaPackage package)
    {
        if (package != null) Package = package;
    }

    /// <summary>Tên quốc gia tiếng Anh theo GA4 (vd "Japan", "Vietnam", "South Korea" - xem README). Gọi khi biết quốc gia.</summary>
    public void SetCountry(string countryName)
    {
        State.Country = countryName;
    }

    // ---------------- vòng đời app ----------------

    /// <summary>Gọi khi app mở hoặc quay lại từ nền.</summary>
    public void OnAppForeground(DateTime nowUtc)
    {
        long now = ToMs(nowUtc);
        if (State.FirstOpenMs == 0) State.FirstOpenMs = now;
        if (State.SessionNumber == 0 || (State.LastActiveMs > 0 && now - State.LastActiveMs >= SessionTimeoutMs))
        {
            State.SessionNumber++;
            State.AttemptsInSession = 0;
        }
        State.ForegroundSinceMs = now;
        State.LastActiveMs = now;
    }

    /// <summary>Gọi khi app chuyển nền (OnApplicationPause(true)).</summary>
    public void OnAppBackground(DateTime nowUtc)
    {
        long now = ToMs(nowUtc);
        AddEngagement(now);
        State.ForegroundSinceMs = 0;
        State.LastActiveMs = now;
    }

    // ---------------- sự kiện trong lượt ----------------

    /// <summary>Mỗi lần hiển thị quảng cáo có doanh thu (mọi loại), giống event paid_ad_impression.</summary>
    public void OnAdImpression(long valueMicros)
    {
        State.SegAdImps += 1;
        State.SegAdUsd += valueMicros / 1e6;
    }

    /// <summary>Mỗi lần game gửi screen_view.</summary>
    public void OnScreenView()
    {
        State.SegScreenViews += 1;
    }

    /// <summary>Mỗi lần hiện hộp thoại đánh giá app (rate_dialog_ev).</summary>
    public void OnRateDialog()
    {
        State.SegRateDialog += 1;
    }

    // ---------------- số bóng ----------------

    /// <summary>Số bóng cấp khi vào màn. Gọi một lần lúc bắt đầu mỗi lượt (kể cả chơi lại).</summary>
    public int GetBallsForLevel(int level)
    {
        int baseBalls = Package.Level(level).TotalBalls;
        int balls = baseBalls;
        if (Mode == DdaMode.On && State.NextLevel == level && State.NextBallsGiven > 0)
            balls = State.NextBallsGiven;
        State.CurrentLevel = level;
        State.CurrentBallsGiven = balls;
        return balls;
    }

    // ---------------- kết thúc lượt ----------------

    /// <summary>Gọi khi lượt kết thúc có kết quả thắng / thua (cùng lúc gửi level_up). Bỏ dở giữa chừng thì không gọi.</summary>
    public DdaResult OnAttemptEnd(DdaAttempt a, DateTime nowUtc)
    {
        long now = ToMs(nowUtc);
        if (State.FirstOpenMs == 0 || State.ForegroundSinceMs == 0) OnAppForeground(nowUtc);
        AddEngagement(now);
        State.ForegroundSinceMs = now;
        State.LastActiveMs = now;

        var pkg = Package;
        var pol = pkg.Policy;
        int T = pkg.Level(a.Level).TotalBalls;
        int given = State.CurrentLevel == a.Level && State.CurrentBallsGiven > 0 ? State.CurrentBallsGiven : T;
        int remainAdj = DdaPolicy.RemainAdj(a.Remain, a.Win, given, T);

        var f = DdaFeatures.Update(State, pkg, a, remainAdj, now);
        DdaPolicy.UpdateMargins(pol, State.WinMargins, a.Win, remainAdj, T);

        var res = new DdaResult
        {
            ModelVersion = pkg.Version,
            Zone = pkg.ZoneName(a.Level),
            BallsBase = T,
            BallsDelta = given - T,
            NextLevel = a.Win ? a.Level + 1 : a.Level,
        };
        res.Action = res.BallsDelta > 0 ? "add" : (res.BallsDelta < 0 ? "cut" : "keep");

        if (Mode != DdaMode.Off)
        {
            res.Features = DdaFeatures.ToArray(f, pkg.Features);
            res.P = pkg.Model.Predict(res.Features);
            res.Flagged = res.P >= pkg.ThrFlag(a.Level);
            res.LowRisk = res.P <= pkg.ThrLow(a.Level);
            bool struggling = DdaPolicy.IsStruggling(pol, a.Win, f["roll10_spec_used"], f["roll10_assist"]);
            bool easy = DdaPolicy.IsEasy(pol, a.Win, f["consec_win"], f["roll10w_z_attempt"], res.LowRisk);
            State.R = DdaPolicy.UpdateR(pol, State.R, a.Level, a.Win, res.Flagged, struggling, easy, f["consec_win"]);
            res.Track = true;
        }

        int tNext = pkg.Level(res.NextLevel).TotalBalls;
        res.R = State.R;
        res.NextBalls = Mode == DdaMode.On ? tNext + DdaPolicy.BallDelta(pol, State.R, State.WinMargins, tNext) : tNext;
        State.NextLevel = res.NextLevel;
        State.NextBallsGiven = res.NextBalls;
        State.CurrentLevel = 0;
        State.CurrentBallsGiven = 0;

        State.SegAdImps = State.SegAdUsd = State.SegEngageSec = State.SegScreenViews = State.SegRateDialog = 0;
        return res;
    }

    void AddEngagement(long now)
    {
        if (State.ForegroundSinceMs > 0 && now > State.ForegroundSinceMs)
            State.SegEngageSec += (now - State.ForegroundSinceMs) / 1000.0;
    }

    static readonly DateTime Epoch = new DateTime(1970, 1, 1, 0, 0, 0, DateTimeKind.Utc);

    public static long ToMs(DateTime utc)
    {
        if (utc.Kind == DateTimeKind.Local) utc = utc.ToUniversalTime();
        return (long)(utc - Epoch).TotalMilliseconds;
    }
}
