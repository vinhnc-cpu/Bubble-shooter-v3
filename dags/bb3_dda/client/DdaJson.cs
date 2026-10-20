// DdaJson.cs - đọc/ghi JSON tối giản cho gói model DDA và trạng thái người chơi.
// Không cần thư viện ngoài (JsonUtility của Unity không đọc được dictionary như thr_flag, map quốc gia).
// Tương thích C# 5+.
//   Object -> Dictionary<string, object>, Array -> List<object>, số -> double, null -> null.
//   Khi ghi: double NaN / vô cực -> null (đọc lại bằng Num() thành NaN).
using System;
using System.Collections;
using System.Collections.Generic;
using System.Globalization;
using System.Text;

public static class DdaJson
{
    public static object Parse(string s)
    {
        int i = 0;
        object v = ParseValue(s, ref i);
        SkipWs(s, ref i);
        if (i != s.Length) throw new FormatException("JSON thua ky tu o vi tri " + i);
        return v;
    }

    // ---- truy cập ----
    public static Dictionary<string, object> Obj(object o) { return (Dictionary<string, object>)o; }
    public static List<object> Arr(object o) { return (List<object>)o; }
    public static double Num(object o) { return o == null ? double.NaN : Convert.ToDouble(o, CultureInfo.InvariantCulture); }
    public static int Int(object o) { return (int)Math.Round(Num(o)); }
    public static long Long(object o) { return (long)Math.Round(Num(o)); }

    public static object Get(Dictionary<string, object> d, string key)
    {
        object v;
        return d.TryGetValue(key, out v) ? v : null;
    }

    // ---- ghi ----
    public static string Write(object v)
    {
        var sb = new StringBuilder();
        WriteValue(sb, v);
        return sb.ToString();
    }

    static void WriteValue(StringBuilder sb, object v)
    {
        if (v == null) { sb.Append("null"); return; }
        if (v is string) { WriteString(sb, (string)v); return; }
        if (v is bool) { sb.Append((bool)v ? "true" : "false"); return; }
        if (v is double || v is float)
        {
            double d = Convert.ToDouble(v, CultureInfo.InvariantCulture);
            if (double.IsNaN(d) || double.IsInfinity(d)) sb.Append("null");
            else sb.Append(d.ToString("R", CultureInfo.InvariantCulture));
            return;
        }
        if (v is int || v is long || v is short || v is byte)
        {
            sb.Append(Convert.ToInt64(v, CultureInfo.InvariantCulture).ToString(CultureInfo.InvariantCulture));
            return;
        }
        var dict = v as IDictionary;
        if (dict != null)
        {
            sb.Append('{');
            bool first = true;
            foreach (DictionaryEntry e in dict)
            {
                if (!first) sb.Append(',');
                first = false;
                WriteString(sb, Convert.ToString(e.Key, CultureInfo.InvariantCulture));
                sb.Append(':');
                WriteValue(sb, e.Value);
            }
            sb.Append('}');
            return;
        }
        var list = v as IEnumerable;
        if (list != null)
        {
            sb.Append('[');
            bool first = true;
            foreach (object x in list)
            {
                if (!first) sb.Append(',');
                first = false;
                WriteValue(sb, x);
            }
            sb.Append(']');
            return;
        }
        throw new ArgumentException("Khong ghi duoc kieu " + v.GetType());
    }

    static void WriteString(StringBuilder sb, string s)
    {
        sb.Append('"');
        foreach (char c in s)
        {
            switch (c)
            {
                case '"': sb.Append("\\\""); break;
                case '\\': sb.Append("\\\\"); break;
                case '\n': sb.Append("\\n"); break;
                case '\r': sb.Append("\\r"); break;
                case '\t': sb.Append("\\t"); break;
                default:
                    if (c < 0x20) sb.Append("\\u").Append(((int)c).ToString("x4"));
                    else sb.Append(c);
                    break;
            }
        }
        sb.Append('"');
    }

    // ---- đọc ----
    static void SkipWs(string s, ref int i)
    {
        while (i < s.Length && char.IsWhiteSpace(s[i])) i++;
    }

    static object ParseValue(string s, ref int i)
    {
        SkipWs(s, ref i);
        if (i >= s.Length) throw new FormatException("JSON ket thuc dot ngot");
        char c = s[i];
        if (c == '{') return ParseObject(s, ref i);
        if (c == '[') return ParseArray(s, ref i);
        if (c == '"') return ParseString(s, ref i);
        if (Match(s, ref i, "true")) return true;
        if (Match(s, ref i, "false")) return false;
        if (Match(s, ref i, "null")) return null;
        return ParseNumber(s, ref i);
    }

    static bool Match(string s, ref int i, string word)
    {
        if (i + word.Length <= s.Length && string.CompareOrdinal(s, i, word, 0, word.Length) == 0)
        {
            i += word.Length;
            return true;
        }
        return false;
    }

    static void Expect(string s, int i, char c)
    {
        if (i >= s.Length || s[i] != c) throw new FormatException("Thieu '" + c + "' o vi tri " + i);
    }

    static Dictionary<string, object> ParseObject(string s, ref int i)
    {
        var d = new Dictionary<string, object>();
        i++;
        SkipWs(s, ref i);
        if (i < s.Length && s[i] == '}') { i++; return d; }
        while (true)
        {
            SkipWs(s, ref i);
            string key = ParseString(s, ref i);
            SkipWs(s, ref i);
            Expect(s, i, ':');
            i++;
            d[key] = ParseValue(s, ref i);
            SkipWs(s, ref i);
            if (i < s.Length && s[i] == ',') { i++; continue; }
            Expect(s, i, '}');
            i++;
            return d;
        }
    }

    static List<object> ParseArray(string s, ref int i)
    {
        var a = new List<object>();
        i++;
        SkipWs(s, ref i);
        if (i < s.Length && s[i] == ']') { i++; return a; }
        while (true)
        {
            a.Add(ParseValue(s, ref i));
            SkipWs(s, ref i);
            if (i < s.Length && s[i] == ',') { i++; continue; }
            Expect(s, i, ']');
            i++;
            return a;
        }
    }

    static string ParseString(string s, ref int i)
    {
        Expect(s, i, '"');
        i++;
        var sb = new StringBuilder();
        while (true)
        {
            if (i >= s.Length) throw new FormatException("Chuoi JSON khong dong");
            char c = s[i++];
            if (c == '"') return sb.ToString();
            if (c != '\\') { sb.Append(c); continue; }
            char e = s[i++];
            switch (e)
            {
                case '"': sb.Append('"'); break;
                case '\\': sb.Append('\\'); break;
                case '/': sb.Append('/'); break;
                case 'b': sb.Append('\b'); break;
                case 'f': sb.Append('\f'); break;
                case 'n': sb.Append('\n'); break;
                case 'r': sb.Append('\r'); break;
                case 't': sb.Append('\t'); break;
                case 'u':
                    sb.Append((char)int.Parse(s.Substring(i, 4), NumberStyles.HexNumber, CultureInfo.InvariantCulture));
                    i += 4;
                    break;
                default: throw new FormatException("Escape khong hop le o vi tri " + i);
            }
        }
    }

    static double ParseNumber(string s, ref int i)
    {
        int start = i;
        while (i < s.Length && "+-0123456789.eE".IndexOf(s[i]) >= 0) i++;
        if (i == start) throw new FormatException("Gia tri JSON khong hop le o vi tri " + i);
        return double.Parse(s.Substring(start, i - start), NumberStyles.Float, CultureInfo.InvariantCulture);
    }
}
