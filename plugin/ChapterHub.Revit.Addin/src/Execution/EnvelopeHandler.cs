using Autodesk.Revit.DB;
using Autodesk.Revit.UI;
using ChapterHub.Core;
using ChapterHub.Core.Contracts;
using ChapterHub.Core.Execution;
using ChapterHub.Revit.Addin.IdMap;
using ChapterHub.Revit.Addin.Ops;
using ChapterHub.Revit.Addin.Transport;

namespace ChapterHub.Revit.Addin.Execution;

/// <summary>
/// The Part G reference executor, verbatim semantics: ONE envelope per Execute pass in
/// its own TransactionGroup; seq + id-map persisted via Extensible Storage INSIDE the
/// group (rollback releases the seq); TTL re-checked at dequeue; document binding
/// verified before anything runs; re-Raise drains the queue one envelope at a time.
/// Phase 6: errors carry op_index; an `interference` rollback is followed by a
/// `clash_delta` frame naming the clashing pair in logical ids (the sim's frame order).
/// Phase 7: handlers that need their own transactions (export_views creates and deletes
/// temporary views) run between the committed batch transactions, still inside the group;
/// their side messages (export_ready) are sent ONLY after a committed commit_result, in
/// emission order — a rolled-back envelope announces nothing.
/// </summary>
public sealed class EnvelopeHandler : IExternalEventHandler
{
    private readonly EnvelopeQueue _queue = new();
    private readonly IReadOnlyDictionary<string, IOpHandler> _handlers = OpHandlerRegistry.Build();
    private readonly Action<object> _send;
    private readonly AddinCatalogs _catalogs;
    private readonly IBlobUploader _uploader;
    private ExternalEvent? _event;

    public EnvelopeHandler(Action<object> sendMessage, AddinCatalogs? catalogs = null, IBlobUploader? uploader = null)
    {
        _send = sendMessage;
        _catalogs = catalogs ?? AddinCatalogs.Empty;
        _uploader = uploader ?? NullBlobUploader.Instance;
    }

    /// <summary>Batches of up to this many ops share one Transaction (progress granularity).</summary>
    private const int BatchSize = 200;

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

            var context = new OpContext(doc, store, _catalogs, body, _uploader);
            var done = 0;
            Transaction? batch = null;
            var inBatch = 0;
            void CommitBatch()
            {
                if (batch is null) return;
                batch.Commit();
                batch.Dispose();
                batch = null;
                inBatch = 0;
                _send(new { type = "progress", envelope_id = body.EnvelopeId, ops_done = done, ops_total = body.Ops.Count });
            }
            try
            {
                foreach (var call in body.Ops)
                {
                    var handler = _handlers[call.Op];
                    if (handler.NeedsOwnTransactions)
                    {
                        // close the running batch first: the handler owns its transactions
                        CommitBatch();
                    }
                    else if (batch is null)
                    {
                        batch = new Transaction(doc, $"HUB batch {done}");
                        batch.Start();
                    }
                    try
                    {
                        handler.Execute(context, call.Args);
                    }
                    catch (OpFailure failure)
                    {
                        throw new IndexedOpFailure(failure, done);
                    }
                    done++;
                    if (!handler.NeedsOwnTransactions && ++inBatch >= BatchSize) CommitBatch();
                }
                CommitBatch();
            }
            finally
            {
                batch?.Dispose(); // a started, uncommitted batch rolls back here (the group follows)
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
            // Phase 7: export_ready frames follow the commit_result, in views order
            foreach (var message in context.DrainSideMessages()) _send(message);
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
