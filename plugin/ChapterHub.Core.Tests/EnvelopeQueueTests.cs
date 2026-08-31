using System.Text.Json;
using ChapterHub.Core.Contracts;
using ChapterHub.Core.Execution;
using Xunit;

namespace ChapterHub.Core.Tests;

public sealed class EnvelopeQueueTests
{
    private sealed class FakeSeqStore(long last) : ISeqStore
    {
        public long LastCommittedSeq { get; } = last;
    }

    private static EnvelopeBody Body(long seq, string issuedAt = "2026-01-01T00:00:00Z", int ttlS = 600) =>
        new()
        {
            EnvelopeId = Guid.Parse("0b5e7a1c-2d3f-4a5b-8c9d-0e1f2a3b4c5d"),
            ProjectId = Guid.Parse("6f1c2a3e-9b4d-4c5e-8f70-123456789abc"),
            WorkstationId = "ws-design-01",
            Seq = seq,
            IssuedAt = issuedAt,
            TtlS = ttlS,
            Ops = [new OpCall { Op = "create_level", Args = JsonDocument.Parse("{}").RootElement }],
        };

    [Fact]
    public void Ttl_is_rechecked_at_dequeue_boundary_inclusive()
    {
        var queue = new EnvelopeQueue();
        queue.Enqueue(Body(1));
        queue.Enqueue(Body(2));

        // exactly at expiry → still runs (matches TS/Python/manifest boundary semantics)
        var atBoundary = queue.TryDequeue(
            DateTimeOffset.Parse("2026-01-01T00:10:00Z"), new FakeSeqStore(0), out _);
        Assert.Equal(EnvelopeQueue.DequeueOutcome.Ready, atBoundary);

        // one second later → expired, never executed
        var expired = queue.TryDequeue(
            DateTimeOffset.Parse("2026-01-01T00:10:01Z"), new FakeSeqStore(0), out var body);
        Assert.Equal(EnvelopeQueue.DequeueOutcome.ExpiredTtl, expired);
        Assert.NotNull(body); // reported so the Addin can send its rolled_back result
    }

    [Fact]
    public void Seq_is_checked_against_the_persisted_store_at_execute_time()
    {
        var queue = new EnvelopeQueue();
        queue.Enqueue(Body(2));
        var replay = queue.TryDequeue(
            DateTimeOffset.Parse("2026-01-01T00:01:00Z"), new FakeSeqStore(2), out _);
        Assert.Equal(EnvelopeQueue.DequeueOutcome.BadSeq, replay);
    }

    [Fact]
    public void One_envelope_per_pass()
    {
        var queue = new EnvelopeQueue();
        queue.Enqueue(Body(1));
        queue.Enqueue(Body(2));
        Assert.Equal(EnvelopeQueue.DequeueOutcome.Ready,
            queue.TryDequeue(DateTimeOffset.Parse("2026-01-01T00:01:00Z"), new FakeSeqStore(0), out _));
        Assert.Equal(1, queue.Count); // the second stays queued for the next Execute pass
    }
}
