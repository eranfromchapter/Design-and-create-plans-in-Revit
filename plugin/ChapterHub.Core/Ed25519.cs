using System.Text;
using Org.BouncyCastle.Crypto.Parameters;
using Org.BouncyCastle.Crypto.Signers;

namespace ChapterHub.Core;

/// <summary>
/// Ed25519 over raw 32-byte keys via BouncyCastle (fully managed — no native libsodium
/// inside Revit's process; version-collision note in docs/MANUAL_REVIT_TEST.md).
/// Production signing happens only in the gateway; SignHex exists for tests and
/// gateway-parity checks against the shared conformance vectors.
/// </summary>
public static class Ed25519
{
    public static bool Verify(string payload, byte[] signature, byte[] publicKey)
    {
        var verifier = new Ed25519Signer();
        verifier.Init(false, new Ed25519PublicKeyParameters(publicKey, 0));
        var data = Encoding.UTF8.GetBytes(payload);
        verifier.BlockUpdate(data, 0, data.Length);
        return verifier.VerifySignature(signature);
    }

    public static string SignHex(string payload, byte[] privateSeed)
    {
        var signer = new Ed25519Signer();
        signer.Init(true, new Ed25519PrivateKeyParameters(privateSeed, 0));
        var data = Encoding.UTF8.GetBytes(payload);
        signer.BlockUpdate(data, 0, data.Length);
        return Convert.ToHexString(signer.GenerateSignature()).ToLowerInvariant();
    }

    public static string PublicKeyHexFromSeed(byte[] privateSeed) =>
        Convert.ToHexString(
            new Ed25519PrivateKeyParameters(privateSeed, 0).GeneratePublicKey().GetEncoded()
        ).ToLowerInvariant();
}
