using System.Security.Cryptography;
using System.Text.RegularExpressions;

namespace ChapterHub.Core;

/// <summary>
/// Content-addressed blob refs (Phase 7, P7-02): the lowercase sha256 hex of the bytes —
/// 64 chars, inside the wss-messages blobRef charset. The gateway recomputes the hash on
/// upload and refuses a mismatch, so the executor names a blob by its content or not at all.
/// </summary>
public static partial class BlobRef
{
    [GeneratedRegex("^[0-9a-f]{64}$")]
    private static partial Regex Pattern();

    public static string Of(ReadOnlySpan<byte> bytes) =>
        Convert.ToHexString(SHA256.HashData(bytes)).ToLowerInvariant();

    public static bool IsValid(string? candidate) => candidate is not null && Pattern().IsMatch(candidate);
}
