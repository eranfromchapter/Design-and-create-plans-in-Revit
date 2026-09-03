using System.Text.Json;
using Autodesk.Revit.DB;
using ChapterHub.Core;
using ChapterHub.Revit.Addin.IdMap;

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

public sealed class OpContext(Document doc, HubStateStore store, AddinCatalogs catalogs)
{
    public Document Doc { get; } = doc;
    public HubStateStore Store { get; } = store;
    public AddinCatalogs Catalogs { get; } = catalogs;

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
}

/// <summary>One handler per allowlisted op (ops/registry.json). Args arrive already
/// shape-verified by ChapterHub.Core (strict records); handlers re-deserialize the typed
/// record and own the Revit API mapping. Value-range validation lands here in Phase 1+
/// per the D4 phasing note.</summary>
public interface IOpHandler
{
    string Op { get; }
    void Execute(OpContext context, JsonElement args);
}
