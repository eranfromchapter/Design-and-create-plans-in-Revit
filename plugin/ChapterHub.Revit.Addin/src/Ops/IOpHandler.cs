using System.Text.Json;
using Autodesk.Revit.DB;
using ChapterHub.Revit.Addin.IdMap;

namespace ChapterHub.Revit.Addin.Ops;

/// <summary>Raised by handlers for the model-level failures the sim mirrors
/// (unknown_revit_type, unknown_host, duplicate_id, …); fails the whole envelope.</summary>
public sealed class OpFailure(string code, string message) : Exception($"{code}: {message}")
{
    public string Code { get; } = code;
}

public sealed class OpContext(Document doc, HubStateStore store)
{
    public Document Doc { get; } = doc;
    public HubStateStore Store { get; } = store;
    public List<(string LogicalId, long ElementId)> Delta { get; } = [];

    public void MapCreated(string logicalId, ElementId elementId)
    {
        if (Store.Entries.ContainsKey(logicalId) || Delta.Any(d => d.LogicalId == logicalId))
            throw new OpFailure("duplicate_id", logicalId);
        Delta.Add((logicalId, elementId.Value));
    }

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
