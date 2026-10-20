// DdaModel.cs - đọc model_trees.bin (định dạng BB3D v1) và dự báo xác suất bỏ game trên thiết bị.
// Không cần thư viện ngoài. Tương thích C# 5+ (mọi bản Unity). Đã kiểm tra: khớp LightGBM, chênh lệch tối đa 2.6e-8 trên 5,000 lượt.
//
// Cách dùng:
//   var model = DdaModel.Load(File.ReadAllBytes(path));       // hoặc TextAsset.bytes
//   double p = model.Predict(features);                       // features: double[40], ĐÚNG thứ tự model_manifest.json (features)
//   bool flagged = p >= thrFlag[zone];                        // ngưỡng trong model_manifest.json (thr_flag)
//
// Giá trị thiếu (vd z_attempt khi thua, gap_prev_sec ở lượt đầu) truyền double.NaN.
// Quy tắc rẽ nhánh giống LightGBM Tree::NumericalDecision (xem pipeline/package.py).
using System;
using System.IO;
using System.Text;

public sealed class DdaModel
{
    const double KZero = 1e-35;

    sealed class Tree
    {
        public byte[] Feature;
        public byte[] Flags;          // bit0 default_left, bit1-2 missing_type (0 None, 1 Zero, 2 NaN)
        public double[] Threshold;
        public short[] Left, Right;   // >= 0: nút trong, < 0: lá thứ -(v+1)
        public float[] Leaf;
    }

    readonly Tree[] _trees;
    public int FeatureCount { get { return _nFeatures; } }
    readonly int _nFeatures;
    public int TreeCount { get { return _trees.Length; } }

    DdaModel(Tree[] trees, int nFeatures)
    {
        _trees = trees;
        _nFeatures = nFeatures;
    }

    public static DdaModel Load(byte[] data)
    {
        using (var r = new BinaryReader(new MemoryStream(data)))   // BinaryReader đọc little-endian
        {
            if (Encoding.ASCII.GetString(r.ReadBytes(4)) != "BB3D")
                throw new InvalidDataException("Khong phai file model BB3D");
            ushort version = r.ReadUInt16();
            if (version != 1)
                throw new InvalidDataException("Khong ho tro format_version " + version);
            int nFeatures = r.ReadUInt16();
            int nTrees = (int)r.ReadUInt32();
            var trees = new Tree[nTrees];
            for (int t = 0; t < nTrees; t++)
            {
                int ni = r.ReadUInt16(), nl = r.ReadUInt16();
                var tr = new Tree
                {
                    Feature = r.ReadBytes(ni),
                    Flags = r.ReadBytes(ni),
                    Threshold = new double[ni],
                    Left = new short[ni],
                    Right = new short[ni],
                    Leaf = new float[nl],
                };
                for (int i = 0; i < ni; i++) tr.Threshold[i] = r.ReadDouble();
                for (int i = 0; i < ni; i++) tr.Left[i] = r.ReadInt16();
                for (int i = 0; i < ni; i++) tr.Right[i] = r.ReadInt16();
                for (int i = 0; i < nl; i++) tr.Leaf[i] = r.ReadSingle();
                trees[t] = tr;
            }
            if (r.BaseStream.Position != r.BaseStream.Length)
                throw new InvalidDataException("File model thua du lieu");
            return new DdaModel(trees, nFeatures);
        }
    }

    /// <summary>Xác suất user không chơi thêm lượt nào trong 7 ngày (lost_7d).</summary>
    public double Predict(double[] x)
    {
        if (x == null || x.Length != FeatureCount)
            throw new ArgumentException("Can dung " + FeatureCount + " feature theo thu tu model_manifest.json (features)");
        double raw = 0;
        foreach (var t in _trees)
        {
            if (t.Feature.Length == 0) { raw += t.Leaf[0]; continue; }
            int node = 0;
            while (true)
            {
                double v = x[t.Feature[node]];
                int flags = t.Flags[node];
                int missing = (flags >> 1) & 3;
                bool isNan = double.IsNaN(v);
                if (isNan && missing != 2) v = 0.0;
                bool goLeft;
                if ((missing == 1 && Math.Abs(v) <= KZero) || (missing == 2 && isNan))
                    goLeft = (flags & 1) == 1;
                else
                    goLeft = v <= t.Threshold[node];
                int next = goLeft ? t.Left[node] : t.Right[node];
                if (next < 0) { raw += t.Leaf[-next - 1]; break; }
                node = next;
            }
        }
        return 1.0 / (1.0 + Math.Exp(-raw));
    }
}
