using Autodesk.Revit.DB;
using Autodesk.Revit.UI;
using ChapterHub.Core;
using ChapterHub.Core.Contracts;
using ChapterHub.Core.Execution;
using ChapterHub.Revit.Addin.IdMap;
using ChapterHub.Revit.Addin.Ops;

namespace ChapterHub.Revit.Addin.Execution;

/// <summary>
/// The Part G reference executor, verbatim semantics: ONE envelope per Execute pass in
/// its own TransactionGroup; seq + id-map persisted via Extensible Storage INSIDE the
/// group (rollback releases the seq); TTL re-checked at dequeue; document binding
/// verified before anything runs; re-Raise drains the queue one envelope at a time.
/// Phase 6: errors carry op_index; an `interference` rollback is followed by a
/// `clash_delta` frame naming the clashing pair in logical ids (the sim's frame order).
/// </summary>
public sealed class EnvelopeHandler : IExternalEventHandler
{
    private readonly EnvelopeQueue _queue = new();
    private readonly IReadOnlyDictionary<string, IOpHandler> _handlers = OpHandlerRegistry.Build();
    private readonly Action<object> _send;
    private readonly AddinCatalogs _catalogs;
    private ExternalEvent? _event;

    public EnvelopeHandler(Action<object> sendMessage, AddinCatalogs? catalogs = null)
    {
        _send = sendMessage;
        _catalogs = catalogs ?? AddinCatalogs.Empty;
    }

    /// <summary>Must be created in a valid Revit API context (IExternalApplication.OnStartup).</summary>
    public void Attach(ExternalEvent externalEvent) => _event = externalEvent;

    /// <summary>Network-thread half: the WSS client verified sig/TTL/shape via
    /// ChapterHub.Core.EnvelopeVerifier before calling this.</summary>
    public void Enqueue(EnvelopeBody verified)
    {
        _queue.Enqueue(verified);
        _event?.Raise();
    }

    public string GetName() => "Chapter HUB Executor";

    public void Execute(UIApplication app)
    {
        var uidoc = app.ActiveUIDocument;
        if (uidoc is null)
        {
            // No document open: leave the queue intact; the WSS client reports busy and
            // re-Raises on Idling. (Gateway timeout policy covers the deferred case.)
            return;
        }
        var doc = uidoc.Document;

        var outcome = _queue.TryDequeue(DateTimeOffset.UtcNow, new HubStateStore(doc), out var body);
        if (outcome == EnvelopeQueue.DequeueOutcome.Empty || body is null) return;

        if (outcome == EnvelopeQueue.DequeueOutcome.ExpiredTtl)
        {
            SendCommitResult(body, committed: false, delta: [], errors: [Error("expired_ttl", "expired before execution")]);
            RaiseIfPending();
            return;
        }
        if (outcome == EnvelopeQueue.DequeueOutcome.BadSeq)
        {
            _send(new { type = "ack", envelope_id = body.EnvelopeId, status = "rejected", reason = "bad_seq" });
            RaiseIfPending();
            return;
        }

        using var group = new TransactionGroup(doc, $"HUB {body.EnvelopeId}");
        group.Start();
        try
        {
            var store = new HubStateStore(doc);
            if (store.BoundProjectId is not null && store.BoundProjectId != body.ProjectId.ToString())
            {
                group.RollBack();
                _send(new { type = "ack", envelope_id = body.EnvelopeId, status = "rejected", reason = "wrong_document" });
                RaiseIfPending();
                return;
            }

            var context = new OpContext(doc, store, _catalogs);
            var done = 0;
            foreach (var batch in body.Ops.Chunk(200))
            {
                using var transaction = new Transaction(doc, $"HUB batch {done}");
                transaction.Start();
                foreach (var call in batch)
                {
                    try
                    {
                        _handlers[call.Op].Execute(context, call.Args);
                    }
                    catch (OpFailure failure)
                    {
                        throw new IndexedOpFailure(failure, done);
                    }
                    done++;
                }
                transaction.Commit();
                _send(new { type = "progress", envelope_id = body.EnvelopeId, ops_done = done, ops_total = body.Ops.Count });
            }

            using (var transaction = new Transaction(doc, "HUB state"))
            {
                transaction.Start();
                if (store.BoundProjectId is null) store.BindProject(body.ProjectId.ToString());
                store.CommitEnvelope(body.Seq, context.Delta); // rolls back WITH the ops
                transaction.Commit();
            }

            group.Assimilate();
            SendCommitResult(body, committed: true,
                delta: context.Delta.Select(d => new { logical_id = d.LogicalId, element_id = d.ElementId }).ToArray(),
                errors: []);
        }
        catch (IndexedOpFailure indexed)
        {
            group.RollBack();
            var failure = indexed.Failure;
            SendCommitResult(body, committed: false, delta: [],
                errors: [Error(failure.Code, failure.Detail, indexed.OpIndex)]);
            if (failure.Code == "interference" && ClashPairs.Parse(failure.Detail) is { } pair)
            {
                _send(new
                {
                    type = "clash_delta",
                    envelope_id = body.EnvelopeId,
                    pairs = new[] { new { a_id = pair.AId, b_id = pair.BId, kind = "hard_interference" } },
                });
            }
        }
        catch (OpFailure failure)
        {
            group.RollBack();
            SendCommitResult(body, committed: false, delta: [], errors: [Error(failure.Code, failure.Detail)]);
        }
        catch (Exception ex)
        {
            group.RollBack();
            SendCommitResult(body, committed: false, delta: [], errors: [Error("internal", ex.Message)]);
        }

        RaiseIfPending(); // drain one envelope at a time
    }

    private void RaiseIfPending()
    {
        if (_queue.Count > 0) _event?.Raise();
    }

    private static object Error(string code, string message) => new { code, message };

    private static object Error(string code, string message, int opIndex) =>
        new { code, message, op_index = opIndex };

    private sealed class IndexedOpFailure(OpFailure failure, int opIndex) : Exception(failure.Message)
    {
        public OpFailure Failure { get; } = failure;
        public int OpIndex { get; } = opIndex;
    }

    private void SendCommitResult(EnvelopeBody body, bool committed, object[] delta, object[] errors) =>
        _send(new
        {
            type = "commit_result",
            envelope_id = body.EnvelopeId,
            status = committed ? "committed" : "rolled_back",
            id_map_delta = delta,
            errors,
        });
}
