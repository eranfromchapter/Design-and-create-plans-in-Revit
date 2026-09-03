using System.Text.Json;
using Autodesk.Revit.DB;
using ChapterHub.Core;
using ChapterHub.Core.Contracts;
using ChapterHub.Revit.Addin.IdMap;
using ChapterHub.Revit.Addin.Transport;

namespace ChapterHub.Revit.Addin.Ops;

/// <summary>Raised by handlers for the model-level failures the sim mirrors
/// (unknown_revit_type, unknown_host, duplicate_id, interference, …); fails the whole envelope.</summary>
public sealed class OpFailure(string code, string message) : Exception($"{code}: {message}")
{
    public string Code { get; } = code;

    /// <summary>The raw wire message (the sim's OpError.message) — for an interference this
    /// is exactly "A~B"; the exception text above carries the code prefix for logs only.</summary>
    public string Detail { get; } = message;
}

public sealed class OpContext(
    Document doc,
    HubStateStore store,
    AddinCatalogs catalogs,
    EnvelopeBody? envelope = null,
    IBlobUploader? uploader = null)
{
    private readonly List<object> _sideMessages = [];

    public Document Doc { get; } = doc;
    public HubStateStore Store { get; } = store;
    public AddinCatalogs Catalogs { get; } = catalogs;

    /// <summary>Phase 7: the envelope being executed (project id for blob uploads).</summary>
    public EnvelopeBody? Envelope { get; } = envelope;

    /// <summary>Phase 7: where exported bytes go before they are announced.</summary>
    public IBlobUploader Uploader { get; } = uploader ?? NullBlobUploader.Instance;

    /// <summary>The id-map delta this envelope commits: one entry per op that creates.</summary>
    public List<(string LogicalId, long ElementId)> Delta { get; } = [];

    /// <summary>Elements created under an ALREADY mapped logical id (PIN-35: the extra
    /// segments and fittings of a multi-segment pipe/conduit). They roll back with the
    /// envelope and take part in the interference check, but never enter the id-map.</summary>
    public List<(string LogicalId, long ElementId)> Extras { get; } = [];

    public void MapCreated(string logicalId, ElementId elementId)
    {
        if (Store.Entries.ContainsKey(logicalId) || Delta.Any(d => d.LogicalId == logicalId))
            throw new OpFailure("duplicate_id", logicalId);
        Delta.Add((logicalId, elementId.Value));
    }

    public void MapExtra(string logicalId, ElementId elementId) => Extras.Add((logicalId, elementId.Value));

    /// <summary>Everything this envelope created, in creation order (delta + extras).</summary>
    public IReadOnlyList<(string LogicalId, long ElementId)> Created() =>
        Delta.Concat(Extras).ToList();

    /// <summary>Logical id of any element: this envelope's delta/extras, then the persisted
    /// id-map, else revit:&lt;ElementId&gt; (an element the HUB never created).</summary>
    public string LogicalIdOf(ElementId elementId) =>
        ClashPairs.LogicalId(elementId.Value, Store.Entries, Created());

    public Element ResolveTarget(string logicalId)
    {
        var mapped = Store.Resolve(logicalId)
            ?? throw new OpFailure("unknown_target", logicalId);
        return Doc.GetElement(mapped) ?? throw new OpFailure("unknown_target", logicalId);
    }

    /// <summary>Phase 7: queue a frame (export_ready) that must reach the gateway ONLY after
    /// the envelope's commit_result — a rolled-back envelope announces nothing. Drained by
    /// the EnvelopeHandler after Assimilate, in emission order.</summary>
    public void Emit(object message) => _sideMessages.Add(message);

    public IReadOnlyList<object> DrainSideMessages()
    {
        var drained = _sideMessages.ToList();
        _sideMessages.Clear();
        return drained;
    }
}

/// <summary>One handler per allowlisted op (ops/registry.json). Args arrive already
/// shape-verified by ChapterHub.Core (strict records); handlers re-deserialize the typed
/// record and own the Revit API mapping. Value-range validation lands here in Phase 1+
/// per the D4 phasing note.</summary>
public interface IOpHandler
{
    string Op { get; }

    /// <summary>Phase 7: a handler that creates and deletes transient elements (temporary
    /// export views) runs OUTSIDE the batch transactions and opens its own — still inside the
    /// envelope's TransactionGroup, so a rollback undoes everything it did.</summary>
    bool NeedsOwnTransactions => false;

    void Execute(OpContext context, JsonElement args);
}
