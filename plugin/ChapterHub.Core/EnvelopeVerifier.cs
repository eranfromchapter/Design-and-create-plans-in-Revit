using System.Globalization;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using System.Text.RegularExpressions;
using ChapterHub.Core.Contracts;

namespace ChapterHub.Core;

public enum RejectReason
{
    BadSignature,
    ExpiredTtl,
    BadSeq,
    UnknownOp,
    InvalidArgs,
    SchemaInvalid,
}

public sealed record VerifyResult(bool Accepted, RejectReason? Reason, EnvelopeBody? Body)
{
    public static VerifyResult Ok(EnvelopeBody body) => new(true, null, body);
    public static VerifyResult Rejected(RejectReason reason) => new(false, reason, null);
}

/// <summary>
/// Envelope verification — the C# reference implementation of the D3 contract, shared by the
/// Revit add-in. Order: sig (over received payload bytes) → parse → body shape → TTL → seq →
/// op allowlist → per-op args (strict records). Pinned against the same conformance vectors
/// as the TS and Python implementations.
///
/// Threading contract (Part G): sig + TTL run on the network thread at enqueue; seq is
/// re-checked at Execute time against the last-committed seq persisted in Extensible Storage,
/// and TTL is re-checked at dequeue. This class is pure and thread-agnostic.
/// </summary>
public static partial class EnvelopeVerifier
{
    [GeneratedRegex("^[0-9a-f]{64}$")]
    private static partial Regex Sha256HexLower();

    [GeneratedRegex("^[a-z0-9][a-z0-9_-]{0,63}$")]
    private static partial Regex WorkstationIdPattern();

    // RFC 3339 with a required offset; culture-invariant. A bare date or an offset-less
    // local timestamp must NOT parse (the TTL verdict would become machine-local).
    private static readonly string[] IssuedAtFormats =
    [
        "yyyy-MM-dd'T'HH:mm:ssK",
        "yyyy-MM-dd'T'HH:mm:ss.FFFFFFFK",
    ];

    public static string HmacHex(string payload, byte[] key)
    {
        using var hmac = new HMACSHA256(key);
        return Convert.ToHexString(hmac.ComputeHash(Encoding.UTF8.GetBytes(payload))).ToLowerInvariant();
    }

    public static VerifyResult Verify(
        WireEnvelope envelope,
        byte[] key,
        DateTimeOffset verifyAt,
        long lastCommittedSeq)
    {
        // The sig contract is 64 lowercase hex chars (D3). Rejecting other spellings up
        // front keeps the three implementations byte-for-byte agreed on what verifies.
        if (!Sha256HexLower().IsMatch(envelope.Sig))
            return VerifyResult.Rejected(RejectReason.BadSignature);
        var expected = Convert.FromHexString(HmacHex(envelope.Payload, key));
        var given = Convert.FromHexString(envelope.Sig);
        if (!CryptographicOperations.FixedTimeEquals(expected, given))
            return VerifyResult.Rejected(RejectReason.BadSignature);

        EnvelopeBody body;
        try
        {
            body = ContractJson.Deserialize<EnvelopeBody>(envelope.Payload);
        }
        catch (JsonException)
        {
            return VerifyResult.Rejected(RejectReason.SchemaInvalid);
        }

        // System.Text.Json's `required` enforces presence, not non-null — explicit JSON
        // nulls deserialize into null members. Mirror the body schema the way TS (ajv)
        // and Python (jsonschema) do before touching anything.
        if (body.WorkstationId is null || body.IssuedAt is null || body.Ops is null)
            return VerifyResult.Rejected(RejectReason.SchemaInvalid);
        if (!WorkstationIdPattern().IsMatch(body.WorkstationId))
            return VerifyResult.Rejected(RejectReason.SchemaInvalid);
        if (body.CommitLabel is { Length: > 80 })
            return VerifyResult.Rejected(RejectReason.SchemaInvalid);
        if (body.ApprovalRef is not null && !Sha256HexLower().IsMatch(body.ApprovalRef.ContentHash ?? ""))
            return VerifyResult.Rejected(RejectReason.SchemaInvalid);
        if (body.Seq < 1 || body.TtlS < 10 || body.TtlS > 3600 || body.Ops.Count is < 1 or > 1000)
            return VerifyResult.Rejected(RejectReason.SchemaInvalid);
        foreach (var op in body.Ops)
        {
            if (op is null || string.IsNullOrEmpty(op.Op) || op.Args.ValueKind != JsonValueKind.Object)
                return VerifyResult.Rejected(RejectReason.SchemaInvalid);
        }
        if (!DateTimeOffset.TryParseExact(
                body.IssuedAt, IssuedAtFormats, CultureInfo.InvariantCulture,
                DateTimeStyles.None, out var issuedAt))
            return VerifyResult.Rejected(RejectReason.SchemaInvalid);

        if (verifyAt > issuedAt.AddSeconds(body.TtlS))
            return VerifyResult.Rejected(RejectReason.ExpiredTtl);

        if (body.Seq <= lastCommittedSeq)
            return VerifyResult.Rejected(RejectReason.BadSeq);

        foreach (var op in body.Ops)
        {
            if (!OpArgsRegistry.ArgTypes.TryGetValue(op.Op, out var argType))
                return VerifyResult.Rejected(RejectReason.UnknownOp);
            try
            {
                _ = op.Args.Deserialize(argType, ContractJson.Options)
                    ?? throw new JsonException("null args");
            }
            catch (JsonException)
            {
                return VerifyResult.Rejected(RejectReason.InvalidArgs);
            }
        }

        return VerifyResult.Ok(body);
    }
}
