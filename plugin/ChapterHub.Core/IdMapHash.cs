using System.Security.Cryptography;
using System.Text;

namespace ChapterHub.Core;

/// <summary>
/// Cross-language id-map hash (hello.id_map_hash, drift gate):
///   sha256( UTF-8( JCS( [[logical_id, element_id], ...] sorted by logical_id ) ) )
/// Pinned by packages/contracts/fixtures/idmap/hash_cases.json in TS, Python, and C#.
/// Ordering is ordinal (UTF-16 code units) — identical to Python sorted() and JS sort
/// for the ASCII logical-id grammar the contracts allow.
/// </summary>
public static class IdMapHash
{
    public static string Compute(IReadOnlyDictionary<string, long> entries)
    {
        var sb = new StringBuilder("[");
        var first = true;
        foreach (var key in entries.Keys.OrderBy(k => k, StringComparer.Ordinal))
        {
            if (!first) sb.Append(',');
            first = false;
            sb.Append("[\"");
            AppendJcsEscaped(sb, key);
            sb.Append("\",").Append(entries[key]).Append(']');
        }
        sb.Append(']');
        var hash = SHA256.HashData(Encoding.UTF8.GetBytes(sb.ToString()));
        return Convert.ToHexString(hash).ToLowerInvariant();
    }

    // RFC 8785 string escaping: the five two-char escapes, \uXXXX for other control
    // chars, backslash and quote escaped, everything else (incl. non-ASCII) literal.
    private static void AppendJcsEscaped(StringBuilder sb, string value)
    {
        foreach (var c in value)
        {
            switch (c)
            {
                case '"': sb.Append("\\\""); break;
                case '\\': sb.Append("\\\\"); break;
                case '\b': sb.Append("\\b"); break;
                case '\t': sb.Append("\\t"); break;
                case '\n': sb.Append("\\n"); break;
                case '\f': sb.Append("\\f"); break;
                case '\r': sb.Append("\\r"); break;
                default:
                    if (c < 0x20) sb.Append("\\u").Append(((int)c).ToString("x4"));
                    else sb.Append(c);
                    break;
            }
        }
    }
}
