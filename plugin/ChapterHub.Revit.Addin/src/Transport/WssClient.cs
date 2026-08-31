using System.Net.WebSockets;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using ChapterHub.Core;
using ChapterHub.Core.Contracts;
using ChapterHub.Revit.Addin.Execution;

namespace ChapterHub.Revit.Addin.Transport;

/// <summary>
/// Outbound WSS client on a background thread (the Revit API is never touched here):
/// bearer-token connect, hello with the model's persisted seq + id-map hash, TOFU pin of
/// the delivered signing public key (DPAPI-protected at rest), enqueue-time verification
/// via ChapterHub.Core, reconnect with backoff. Outbound messages are queued by the
/// executor (UI thread) and drained here.
/// </summary>
public sealed class WssClient(WssClientOptions options, EnvelopeHandler handler) : IDisposable
{
    private readonly CancellationTokenSource _cts = new();
    private readonly System.Collections.Concurrent.ConcurrentQueue<string> _outbound = new();
    private byte[]? _publicKey;
    private Thread? _thread;

    public void Start()
    {
        _thread = new Thread(() => RunLoop().GetAwaiter().GetResult())
        {
            IsBackground = true,
            Name = "ChapterHub.Wss",
        };
        _thread.Start();
    }

    /// <summary>Called by the executor (any thread) to send acks/commit_results/progress.</summary>
    public void Send(object message) =>
        _outbound.Enqueue(JsonSerializer.Serialize(message, ContractJson.Options));

    private async Task RunLoop()
    {
        var backoffSeconds = 1;
        while (!_cts.IsCancellationRequested)
        {
            try
            {
                await ConnectAndPump();
                backoffSeconds = 1;
            }
            catch when (!_cts.IsCancellationRequested)
            {
                await Task.Delay(TimeSpan.FromSeconds(backoffSeconds), _cts.Token);
                backoffSeconds = Math.Min(backoffSeconds * 2, 60);
            }
        }
    }

    private async Task ConnectAndPump()
    {
        using var ws = new ClientWebSocket();
        ws.Options.SetRequestHeader("Authorization", $"Bearer {options.Token}");
        await ws.ConnectAsync(options.GatewayUri, _cts.Token);

        await SendRaw(ws, JsonSerializer.Serialize(new
        {
            type = "hello",
            workstation_id = options.WorkstationId,
            plugin_version = options.PluginVersion,
            last_committed_seq = options.ReadLastCommittedSeq(),
            id_map_hash = options.ReadIdMapHash(),
        }));

        var authOk = JsonDocument.Parse(await Receive(ws)).RootElement;
        if (authOk.GetProperty("type").GetString() != "auth_ok")
            throw new InvalidOperationException("gateway refused hello");
        _publicKey = PinPublicKey(authOk.GetProperty("signing_public_key").GetString()!);

        var pump = PumpOutbound(ws);
        while (ws.State == WebSocketState.Open && !_cts.IsCancellationRequested)
        {
            var frame = JsonDocument.Parse(await Receive(ws)).RootElement;
            if (frame.GetProperty("type").GetString() != "envelope") continue;

            var wire = new WireEnvelope
            {
                Payload = frame.GetProperty("payload").GetString()!,
                Sig = frame.GetProperty("sig").GetString()!,
            };
            // Enqueue-time verification (SI-3): sig over received payload bytes, shape,
            // TTL; seq is re-checked at Execute time against Extensible Storage.
            var result = EnvelopeVerifier.Verify(
                wire, _publicKey!, DateTimeOffset.UtcNow, lastCommittedSeq: 0);
            if (!result.Accepted || result.Body is null)
            {
                Send(new
                {
                    type = "ack",
                    envelope_id = TryEnvelopeId(wire.Payload),
                    status = "rejected",
                    reason = ReasonName(result.Reason),
                });
                continue;
            }
            Send(new { type = "ack", envelope_id = result.Body.EnvelopeId, status = "accepted" });
            handler.Enqueue(result.Body);
        }
        await pump;
    }

    private async Task PumpOutbound(ClientWebSocket ws)
    {
        while (ws.State == WebSocketState.Open && !_cts.IsCancellationRequested)
        {
            while (_outbound.TryDequeue(out var message)) await SendRaw(ws, message);
            await Task.Delay(25, _cts.Token);
        }
    }

    private async Task SendRaw(ClientWebSocket ws, string json) =>
        await ws.SendAsync(Encoding.UTF8.GetBytes(json), WebSocketMessageType.Text, true, _cts.Token);

    private async Task<string> Receive(ClientWebSocket ws)
    {
        var buffer = new byte[1 << 20];
        var builder = new StringBuilder();
        while (true)
        {
            var result = await ws.ReceiveAsync(buffer, _cts.Token);
            if (result.MessageType == WebSocketMessageType.Close)
                throw new WebSocketException("gateway closed");
            builder.Append(Encoding.UTF8.GetString(buffer, 0, result.Count));
            if (result.EndOfMessage) return builder.ToString();
        }
    }

    /// <summary>TOFU pin (D3): the public key delivered at enrollment is stored
    /// DPAPI-protected per user; a silently changed key is refused.</summary>
    private byte[] PinPublicKey(string deliveredHex)
    {
        var pinPath = options.PinFilePath;
        if (File.Exists(pinPath))
        {
            var pinnedHex = Encoding.UTF8.GetString(
                ProtectedData.Unprotect(File.ReadAllBytes(pinPath), null, DataProtectionScope.CurrentUser));
            if (pinnedHex != deliveredHex)
                throw new InvalidOperationException("gateway signing key changed — refusing (re-enroll to rotate)");
            return Convert.FromHexString(pinnedHex);
        }
        Directory.CreateDirectory(Path.GetDirectoryName(pinPath)!);
        File.WriteAllBytes(pinPath,
            ProtectedData.Protect(Encoding.UTF8.GetBytes(deliveredHex), null, DataProtectionScope.CurrentUser));
        return Convert.FromHexString(deliveredHex);
    }

    private static string TryEnvelopeId(string payload)
    {
        try
        {
            return JsonDocument.Parse(payload).RootElement.GetProperty("envelope_id").GetString()
                ?? "00000000-0000-0000-0000-000000000000";
        }
        catch
        {
            return "00000000-0000-0000-0000-000000000000";
        }
    }

    private static string ReasonName(RejectReason? reason) => reason switch
    {
        RejectReason.BadSignature => "bad_signature",
        RejectReason.ExpiredTtl => "expired_ttl",
        RejectReason.BadSeq => "bad_seq",
        RejectReason.UnknownOp => "unknown_op",
        RejectReason.InvalidArgs => "invalid_args",
        _ => "schema_invalid",
    };

    public void Dispose()
    {
        _cts.Cancel();
        _cts.Dispose();
    }
}

public sealed record WssClientOptions
{
    public required Uri GatewayUri { get; init; }
    public required string Token { get; init; }
    public required string WorkstationId { get; init; }
    public required string PluginVersion { get; init; }
    public required string PinFilePath { get; init; }
    public required Func<long> ReadLastCommittedSeq { get; init; }
    public required Func<string> ReadIdMapHash { get; init; }
}
