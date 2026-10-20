// DdaPackage.cs - đọc cả gói model: model_trees.bin + model_manifest.json + model_levels.json + model_country_tier.json.
// Kiểm tra sha256 từng file theo manifest; sai thì ném lỗi để game giữ gói cũ.
// Tương thích C# 5+.
//
//   var pkg = DdaPackage.Load(treesBytes, manifestBytes, levelsBytes, tierBytes);
//
// Ngưỡng, tham số policy, thứ tự feature đều đọc từ manifest. KHÔNG hard-code trong game: model train lại hằng ngày.
using System;
using System.Collections.Generic;
using System.Security.Cryptography;
using System.Text;

/// <summary>Một dòng của model_levels.json (theo src 1-1000).</summary>
public sealed class DdaLevel
{
    public int TotalBalls;    // số bóng gốc của màn
    public double Mu, Sd;     // trung bình, độ lệch chuẩn số bóng dư khi thắng (null -> NaN)
    public double LossRate;   // tỷ lệ thua của màn
    public double Jump;       // loss_rate trừ trung bình 3 màn trước
}

/// <summary>Tham số policy thêm/bớt bóng (manifest.policy).</summary>
public sealed class DdaPolicyParams
{
    public int MinLevelAdd;            // thêm bóng từ màn này
    public double StepUp;              // mỗi lần thêm: +5% số bóng gốc
    public double RUpMax;              // trần thêm: +20%
    public int WinDecay;               // từ lần thắng liên tiếp thứ 2, mỗi lần thắng giảm StepUp
    public int MinLevelCut;            // bớt bóng từ màn này
    public int CutWins;                // thắng liên tiếp >= 2 mới xét bớt
    public double CutZ;                // trung bình z 10 lượt thắng gần nhất >= 0.3
    public double StepDown;            // mỗi lần thắng dễ: bớt thêm 10% độ dư
    public double GDownMax;            // trần bớt: 50% độ dư
    public double CapDown;             // và không quá 30% số bóng gốc
    public int MarginN;                // số lượt thắng gần nhất dùng tính độ dư
    public int CutMinBalls;            // đang bớt thì bớt tối thiểu 1 quả
    public double StruggleSpecUsed;    // roll10_spec_used >= 1.0 -> đang vật lộn
    public double StruggleAssist;      // roll10_assist >= 0.3 -> đang vật lộn
}

public sealed class DdaPackage
{
    public const int SupportedFormat = 1;
    public const int MaxSrc = 1000;

    public string Version;             // "1.14" - gửi lên tracking dda_model_version
    public string Build;               // mã nội bộ, vd "20261019-t300"
    public DdaModel Model;
    public string[] Features;          // thứ tự 40 feature
    public DdaPolicyParams Policy;
    public int DefaultTier;

    readonly DdaLevel[] _levels = new DdaLevel[MaxSrc + 1];   // chỉ số 1..1000
    readonly Dictionary<string, int> _tier = new Dictionary<string, int>(StringComparer.Ordinal);
    readonly List<Zone> _zones = new List<Zone>();

    sealed class Zone
    {
        public string Name;
        public int Lo, Hi;             // Hi = int.MaxValue nếu không giới hạn
        public double ThrFlag, ThrLow;
    }

    /// <summary>Màn thiết kế dùng để tra bảng: màn > 1000 lặp lại 101-1000.</summary>
    public static int Src(int level)
    {
        return level <= MaxSrc ? level : 100 + (level - 100) % 900;
    }

    public DdaLevel Level(int level)
    {
        int s = Src(level);
        if (s < 1 || s > MaxSrc) throw new ArgumentOutOfRangeException("level", "Man khong hop le: " + level);
        return _levels[s];
    }

    /// <summary>Tier quốc gia: 0 T1, 1 T2, 2 T3, 3 Z. Tên quốc gia theo GA4 (vd "Japan", "Congo - Kinshasa").</summary>
    public int TierCode(string countryName)
    {
        int t;
        return countryName != null && _tier.TryGetValue(countryName, out t) ? t : DefaultTier;
    }

    public string ZoneName(int level) { return FindZone(level).Name; }
    public double ThrFlag(int level) { return FindZone(level).ThrFlag; }
    public double ThrLow(int level) { return FindZone(level).ThrLow; }

    Zone FindZone(int level)
    {
        foreach (var z in _zones)
            if (level >= z.Lo && level <= z.Hi) return z;
        return _zones[_zones.Count - 1];
    }

    public static DdaPackage Load(byte[] trees, byte[] manifest, byte[] levels, byte[] tier)
    {
        return Load(trees, manifest, levels, tier, true);
    }

    public static DdaPackage Load(byte[] trees, byte[] manifest, byte[] levels, byte[] tier, bool verifySha256)
    {
        var m = DdaJson.Obj(DdaJson.Parse(Utf8(manifest)));
        int format = DdaJson.Int(DdaJson.Get(m, "format_version"));
        if (format != SupportedFormat)
            throw new InvalidOperationException("Goi model format_version " + format + ", game chi ho tro " + SupportedFormat);

        if (verifySha256)
        {
            var files = DdaJson.Obj(DdaJson.Get(m, "files"));
            CheckSha(files, "model_trees.bin", trees);
            CheckSha(files, "model_levels.json", levels);
            CheckSha(files, "model_country_tier.json", tier);
        }

        var p = new DdaPackage();
        p.Version = (string)DdaJson.Get(m, "version");
        p.Build = (string)DdaJson.Get(m, "build");
        p.Model = DdaModel.Load(trees);

        var feats = DdaJson.Arr(DdaJson.Get(m, "features"));
        p.Features = new string[feats.Count];
        for (int i = 0; i < feats.Count; i++) p.Features[i] = (string)feats[i];
        if (p.Features.Length != p.Model.FeatureCount)
            throw new InvalidOperationException("manifest co " + p.Features.Length + " feature, model can " + p.Model.FeatureCount);
        DdaFeatures.CheckSupported(p.Features);

        var zones = DdaJson.Obj(DdaJson.Get(m, "zones"));
        var thrFlag = DdaJson.Obj(DdaJson.Get(m, "thr_flag"));
        var thrLow = DdaJson.Obj(DdaJson.Get(m, "thr_low"));
        foreach (var kv in zones)
        {
            var range = DdaJson.Arr(kv.Value);
            p._zones.Add(new Zone
            {
                Name = kv.Key,
                Lo = DdaJson.Int(range[0]),
                Hi = range[1] == null ? int.MaxValue : DdaJson.Int(range[1]),
                ThrFlag = DdaJson.Num(DdaJson.Get(thrFlag, kv.Key)),
                ThrLow = DdaJson.Num(DdaJson.Get(thrLow, kv.Key)),
            });
        }
        p._zones.Sort((a, b) => a.Lo.CompareTo(b.Lo));

        var pol = DdaJson.Obj(DdaJson.Get(m, "policy"));
        p.Policy = new DdaPolicyParams
        {
            MinLevelAdd = DdaJson.Int(DdaJson.Get(pol, "min_level_add")),
            StepUp = DdaJson.Num(DdaJson.Get(pol, "step_up")),
            RUpMax = DdaJson.Num(DdaJson.Get(pol, "r_up_max")),
            WinDecay = DdaJson.Int(DdaJson.Get(pol, "win_decay")),
            MinLevelCut = DdaJson.Int(DdaJson.Get(pol, "min_level_cut")),
            CutWins = DdaJson.Int(DdaJson.Get(pol, "cut_wins")),
            CutZ = DdaJson.Num(DdaJson.Get(pol, "cut_z")),
            StepDown = DdaJson.Num(DdaJson.Get(pol, "step_down")),
            GDownMax = DdaJson.Num(DdaJson.Get(pol, "g_down_max")),
            CapDown = DdaJson.Num(DdaJson.Get(pol, "cap_down")),
            MarginN = DdaJson.Int(DdaJson.Get(pol, "margin_n")),
            CutMinBalls = DdaJson.Int(DdaJson.Get(pol, "cut_min_balls")),
            StruggleSpecUsed = DdaJson.Num(DdaJson.Get(pol, "struggle_spec_used")),
            StruggleAssist = DdaJson.Num(DdaJson.Get(pol, "struggle_assist")),
        };

        foreach (var o in DdaJson.Arr(DdaJson.Parse(Utf8(levels))))
        {
            var r = DdaJson.Obj(o);
            int src = DdaJson.Int(DdaJson.Get(r, "level"));
            if (src < 1 || src > MaxSrc) continue;
            double sd = DdaJson.Num(DdaJson.Get(r, "sd"));
            p._levels[src] = new DdaLevel
            {
                TotalBalls = DdaJson.Int(DdaJson.Get(r, "total_balls")),
                Mu = DdaJson.Num(DdaJson.Get(r, "mu")),
                Sd = sd == 0 ? double.NaN : sd,
                LossRate = DdaJson.Num(DdaJson.Get(r, "loss_rate")),
                Jump = DdaJson.Num(DdaJson.Get(r, "jump")),
            };
        }
        for (int s = 1; s <= MaxSrc; s++)
            if (p._levels[s] == null) throw new InvalidOperationException("model_levels.json thieu man " + s);

        var t = DdaJson.Obj(DdaJson.Parse(Utf8(tier)));
        p.DefaultTier = DdaJson.Int(DdaJson.Get(t, "default"));
        foreach (var kv in DdaJson.Obj(DdaJson.Get(t, "map")))
            p._tier[kv.Key] = DdaJson.Int(kv.Value);
        return p;
    }

    static string Utf8(byte[] b)
    {
        string s = Encoding.UTF8.GetString(b);
        return s.Length > 0 && s[0] == '﻿' ? s.Substring(1) : s;
    }

    static void CheckSha(Dictionary<string, object> files, string name, byte[] data)
    {
        var f = DdaJson.Obj(DdaJson.Get(files, name));
        string want = (string)DdaJson.Get(f, "sha256");
        string got;
        using (var sha = SHA256.Create())
            got = BitConverter.ToString(sha.ComputeHash(data)).Replace("-", "").ToLowerInvariant();
        if (got != want) throw new InvalidOperationException("Sai sha256: " + name);
    }
}
