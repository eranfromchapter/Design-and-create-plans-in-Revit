using System.Collections.Concurrent;
using ChapterHub.Core.Contracts;

namespace ChapterHub.Core.Execution;

/// <summary>Persisted last-committed seq (Extensible Storage on the real plugin; rolls
/// back WITH the TransactionGroup, so a rolled-back envelope never consumes its seq).</summary>
public interface ISeqStore
{
    long LastCommittedSeq { get; }
}

/// <summary>logical id → ElementId map (Extensible Storage twin of the gateway's id_map).</summary>
public interface IIdMapStore
{
    IReadOnlyDictionary<string, long> Entries { get; }
}

/// <summary>
/// The pure half of Part G's EnvelopeHandler: verified envelopes queue on the network
/// thread; Execute (Revit UI thread) dequeues ONE per pass and re-checks TTL at dequeue
/// (SI-3) plus seq against the persisted store. Everything Revit-flavored (TransactionGroup,
/// Extensible Storage, ExternalEvent.Raise) stays in the Addin.
/// </summary>
public sealed class EnvelopeQueue
{
    private readonly ConcurrentQueue<EnvelopeBody> _queue = new();

    public int Count => _queue.Count;

    /// <summary>Network-thread half: sig + TTL + shape were checked by EnvelopeVerifier.Verify;
    /// only verified bodies may enter the queue.</summary>
    public void Enqueue(EnvelopeBody verified) => _queue.Enqueue(verified);

    public enum DequeueOutcome
    {
        Empty,
        Ready,
        ExpiredTtl,
        BadSeq,
    }

    /// <summary>Execute-time half: one envelope per pass, TTL re-checked at dequeue,
    /// seq checked against the PERSISTED last-committed value.</summary>
    public DequeueOutcome TryDequeue(DateTimeOffset now, ISeqStore seqStore, out EnvelopeBody? body)
    {
        body = null;
        if (!_queue.TryDequeue(out var candidate)) return DequeueOutcome.Empty;
        body = candidate;
        if (!DateTimeOffset.TryParse(candidate.IssuedAt, out var issuedAt) ||
            now > issuedAt.AddSeconds(candidate.TtlS))
        {
            return DequeueOutcome.ExpiredTtl;
        }
        if (candidate.Seq <= seqStore.LastCommittedSeq) return DequeueOutcome.BadSeq;
        return DequeueOutcome.Ready;
    }
}
